// Site markers as real DOM buttons (Tab / Enter work, screen readers see names), positioned from
// the 3D scene every frame. Hidden behind the limb, faded near it, and grouped where they crowd
// (the south pole has nine sites inside 6 deg); clicking a group zooms in until it splits.
import * as THREE from 'three';

export type PinSite = {
  site_id: string;
  name: string;
  latitude_deg: number;   // planetocentric
  longitude_deg: number;  // east-positive, 0..360
  group?: string | null;
  kind?: string | null;
};

/** MOON_ME lat/lon -> three.js unit vector (three Y = lunar north; see lunarMaterial.meToThree). */
export function latLonToThree(latDeg: number, lonDeg: number): THREE.Vector3 {
  const la = THREE.MathUtils.degToRad(latDeg), lo = THREE.MathUtils.degToRad(lonDeg);
  const x = Math.cos(la) * Math.cos(lo), y = Math.cos(la) * Math.sin(lo), z = Math.sin(la);
  return new THREE.Vector3(x, z, -y);
}

const CSS = `
.la-pins{position:absolute;inset:0;overflow:hidden;pointer-events:none;font-family:var(--font-ui,system-ui),sans-serif}
.la-pin,.la-cluster{position:absolute;left:0;top:0;pointer-events:auto;border:0;background:none;padding:0;
  width:40px;height:40px;margin:-20px 0 0 -20px;display:flex;align-items:center;justify-content:center;cursor:pointer;
  will-change:transform,opacity;outline:none}
.la-mk{position:relative;width:11px;height:11px;border-radius:50%;box-sizing:border-box;border:1.5px solid #e9edf2;
  background:rgba(6,8,12,.55);box-shadow:0 0 0 1px rgba(0,0,0,.55);transition:transform .15s ease}
.la-mk::after{content:'';position:absolute;left:50%;top:50%;width:3px;height:3px;margin:-1.5px 0 0 -1.5px;border-radius:50%;background:#e9edf2}
.la-pin.day .la-mk{border-color:#f2b84b}.la-pin.day .la-mk::after{background:#f2b84b}
.la-pin.night .la-mk{border-color:#7d8796}.la-pin.night .la-mk::after{background:#7d8796}
.la-pin:hover .la-mk,.la-pin:focus-visible .la-mk{transform:scale(1.35)}
.la-pin.sel .la-mk{width:15px;height:15px;border-width:2px;border-color:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.6),0 0 0 6px rgba(255,255,255,.12)}
.la-pin.sel .la-mk::after{background:#fff}
.la-pin:focus-visible .la-mk,.la-cluster:focus-visible .la-count{outline:2px solid #fff;outline-offset:4px}
.la-label{position:absolute;left:24px;top:50%;transform:translateY(-50%);white-space:nowrap;
  font:500 12px/1.25 var(--font-cond,system-ui),sans-serif;letter-spacing:.02em;color:#eef1f5;
  background:rgba(7,9,13,.82);border-left:2px solid rgba(233,237,242,.6);padding:3px 7px 3px 6px;
  opacity:0;transition:opacity .15s ease;pointer-events:none}
.la-pin.day .la-label{border-left-color:#f2b84b}.la-pin.night .la-label{border-left-color:#7d8796}
.la-label small{display:block;font:400 11px/1.3 var(--font-mono,monospace);color:#9aa5b4;letter-spacing:0}
.la-pin:hover .la-label,.la-pin:focus-visible .la-label,.la-pin.sel .la-label,.la-pins.near .la-pin .la-label{opacity:1}
.la-count{min-width:22px;height:22px;padding:0 5px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;
  font:500 12px/1 var(--font-mono,monospace);color:#eef1f5;background:rgba(7,9,13,.85);border:1.5px solid #e9edf2;
  box-shadow:0 0 0 1px rgba(0,0,0,.5)}
`;

type PinEl = { site: PinSite; dir: THREE.Vector3; el: HTMLButtonElement };

export class PinLayer {
  readonly root: HTMLDivElement;
  private pins: PinEl[] = [];
  private clusters: HTMLButtonElement[] = [];
  private tmp = new THREE.Vector3();
  private toCam = new THREE.Vector3();
  selectedId: string | null = null;
  private onPick: (site: PinSite) => void;
  private onCluster: (dirWorld: THREE.Vector3, members: PinSite[]) => void;
  private radius: number;

  constructor(
    container: HTMLElement,
    sites: PinSite[],
    onPick: (site: PinSite) => void,
    onCluster: (dirWorld: THREE.Vector3, members: PinSite[]) => void,
    radius = 1.0065, // above the highest LOLA relief (~10.7 km = 0.006 radii)
  ) {
    this.onPick = onPick;
    this.onCluster = onCluster;
    this.radius = radius;
    if (!document.getElementById('la-pins-css')) {
      const st = document.createElement('style');
      st.id = 'la-pins-css';
      st.textContent = CSS;
      document.head.appendChild(st);
    }
    this.root = document.createElement('div');
    this.root.className = 'la-pins';
    container.appendChild(this.root);
    for (const site of sites) {
      const el = document.createElement('button');
      el.type = 'button';
      el.className = 'la-pin';
      el.setAttribute('aria-label', `${site.name}${site.group ? `, ${site.group}` : ''}. Fly there`);
      const dot = document.createElement('span'); dot.className = 'la-mk';
      const label = document.createElement('span'); label.className = 'la-label';
      label.textContent = shortName(site.name);
      { const sm = document.createElement('small'); sm.textContent = coordText(site.latitude_deg, site.longitude_deg); label.appendChild(sm); }
      el.append(dot, label);
      el.addEventListener('click', () => this.onPick(site));
      this.root.appendChild(el);
      this.pins.push({ site, el, dir: latLonToThree(site.latitude_deg, site.longitude_deg) });
    }
  }

  /** Project, cull behind the limb, and group crowded markers. Call once per frame. */
  update(camera: THREE.PerspectiveCamera, width: number, height: number): void {
    const camPos = camera.position;
    const vis: { p: PinEl; x: number; y: number; a: number }[] = [];
    for (const p of this.pins) {
      const w = this.tmp.copy(p.dir).multiplyScalar(this.radius);
      const facing = this.toCam.copy(camPos).sub(w).normalize().dot(p.dir);
      const ndc = w.project(camera);
      if (facing <= 0.015 || ndc.z > 1 || Math.abs(ndc.x) > 1.2 || Math.abs(ndc.y) > 1.2) {
        p.el.style.display = 'none';
        p.el.tabIndex = -1;
        continue;
      }
      const a = THREE.MathUtils.smoothstep(facing, 0.015, 0.16);
      vis.push({ p, x: (ndc.x + 1) * 0.5 * width, y: (1 - ndc.y) * 0.5 * height, a });
    }
    // Greedy screen-space grouping; the selected site always stands alone.
    const R = 26, used = new Set<number>(), groups: number[][] = [];
    for (let i = 0; i < vis.length; i++) {
      if (used.has(i)) continue;
      const g = [i]; used.add(i);
      if (vis[i].p.site.site_id !== this.selectedId) {
        for (let j = i + 1; j < vis.length; j++) {
          if (used.has(j) || vis[j].p.site.site_id === this.selectedId) continue;
          if (Math.hypot(vis[i].x - vis[j].x, vis[i].y - vis[j].y) < R) { g.push(j); used.add(j); }
        }
      }
      groups.push(g);
    }
    // Merge groups whose centres now overlap (greedy seeding can leave two badges touching).
    const centre = (g: number[]) => [g.reduce((a, k) => a + vis[k].x, 0) / g.length, g.reduce((a, k) => a + vis[k].y, 0) / g.length];
    const hasSel = (g: number[]) => g.some((k) => vis[k].p.site.site_id === this.selectedId);
    for (let merged = true; merged;) {
      merged = false;
      outer: for (let a = 0; a < groups.length; a++) for (let b = a + 1; b < groups.length; b++) {
        if (hasSel(groups[a]) || hasSel(groups[b])) continue;
        const [ax, ay] = centre(groups[a]), [bx, by] = centre(groups[b]);
        if (Math.hypot(ax - bx, ay - by) < R * 1.3) { groups[a] = groups[a].concat(groups[b]); groups.splice(b, 1); merged = true; break outer; }
      }
    }
    let ci = 0, spread = Infinity;
    for (const g of groups) {
      if (g.length === 1) {
        const v = vis[g[0]];
        const el = v.p.el;
        el.style.display = 'flex';
        el.tabIndex = 0;
        el.style.opacity = v.a.toFixed(3);
        el.style.transform = `translate(${v.x.toFixed(1)}px,${v.y.toFixed(1)}px)`;
        el.classList.toggle('sel', v.p.site.site_id === this.selectedId);
        continue;
      }
      let cx = 0, cy = 0, a = 0;
      const members: PinSite[] = [], dir = new THREE.Vector3();
      for (const k of g) { const v = vis[k]; cx += v.x; cy += v.y; a = Math.max(a, v.a); members.push(v.p.site); dir.add(v.p.dir); v.p.el.style.display = 'none'; v.p.el.tabIndex = -1; }
      cx /= g.length; cy /= g.length;
      const btn = this.clusterButton(ci++);
      btn.style.display = 'flex';
      btn.style.opacity = a.toFixed(3);
      btn.style.transform = `translate(${cx.toFixed(1)}px,${cy.toFixed(1)}px)`;
      btn.setAttribute('aria-label', `${g.length} sites close together: ${members.map((m) => shortName(m.name)).join(', ')}. Zoom in`);
      (btn.firstChild as HTMLElement).textContent = String(g.length);
      btn.onclick = () => this.onCluster(dir.normalize(), members);
    }
    for (let k = ci; k < this.clusters.length; k++) this.clusters[k].style.display = 'none';
    // Show every label once markers are far apart (zoomed in), so close-ups read like a map.
    for (let i = 0; i < vis.length; i++) for (let j = i + 1; j < vis.length; j++) {
      spread = Math.min(spread, Math.hypot(vis[i].x - vis[j].x, vis[i].y - vis[j].y));
    }
    this.root.classList.toggle('near', groups.every((g) => g.length === 1) && spread > 150 && vis.length <= 6);
  }

  private clusterButton(i: number): HTMLButtonElement {
    while (this.clusters.length <= i) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'la-cluster';
      const c = document.createElement('span'); c.className = 'la-count';
      b.appendChild(c);
      this.root.appendChild(b);
      this.clusters.push(b);
    }
    return this.clusters[i];
  }

  /** Add a state class ('day', 'night', ...) to each site's marker; unknown ids are cleared. */
  setStates(states: Record<string, string>): void {
    for (const p of this.pins) {
      const want = states[p.site.site_id] ?? '';
      if (p.el.dataset.state === want) continue;
      if (p.el.dataset.state) p.el.classList.remove(p.el.dataset.state);
      if (want) p.el.classList.add(want);
      p.el.dataset.state = want;
    }
  }

  dispose(): void { this.root.remove(); }
}

function coordText(lat: number, lon: number): string {
  const e = lon > 180 ? lon - 360 : lon;
  return `${Math.abs(lat).toFixed(2)}°${lat < 0 ? 'S' : 'N'} ${Math.abs(e).toFixed(2)}°${e < 0 ? 'W' : 'E'}`;
}

/** "Apollo 11 (Tranquility Base)" -> "Apollo 11"; keeps names short on the globe. */
export function shortName(name: string): string {
  return name.replace(/\s*\(.*\)\s*$/, '').replace(/ reference point$/, '');
}
