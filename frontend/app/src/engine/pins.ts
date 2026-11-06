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

// Chart style: markers are small symbols, names are set like a printed lunar chart (serif italic
// with a dark halo, no boxes). Green = a landing window within 30 days (from the API), amber = Sun
// up now, hollow = night; the word under the name says the same thing, so colour is never alone.
const CSS = `
.la-pins{position:absolute;inset:0;overflow:hidden;pointer-events:none}
.la-pin,.la-cluster{position:absolute;left:0;top:0;pointer-events:auto;border:0;background:none;padding:0;
  width:36px;height:36px;margin:-18px 0 0 -18px;display:flex;align-items:center;justify-content:center;cursor:pointer;
  will-change:transform,opacity;outline:none;color:#ece7dc}
.la-mk{position:relative;width:8px;height:8px;border-radius:50%;box-sizing:border-box;border:1.5px solid #9aa0a8;background:#000;
  transition:transform .15s ease}
.la-pin.day .la-mk{border-color:#f2b84b;background:#f2b84b}
.la-pin.window .la-mk{width:10px;height:10px;border:2px solid #000;background:#5ed394;
  box-shadow:0 0 0 1.5px #5ed394,0 0 14px 3px rgba(94,211,148,.55);animation:la-breathe 3.2s ease-in-out infinite}
@keyframes la-breathe{50%{box-shadow:0 0 0 1.5px #5ed394,0 0 22px 7px rgba(94,211,148,.28)}}
@media (prefers-reduced-motion:reduce){.la-pin.window .la-mk{animation:none}}
.la-pin:hover .la-mk,.la-pin:focus-visible .la-mk{transform:scale(1.4)}
.la-pin.sel .la-mk{transform:scale(1.5);outline:1.5px solid #ece7dc;outline-offset:4px}
.la-pin:focus-visible .la-mk,.la-cluster:focus-visible .la-count{outline:2px solid #fff;outline-offset:5px}
.la-label{position:absolute;left:24px;top:50%;transform:translateY(-52%);white-space:nowrap;text-align:left;
  font:600 15px/1.15 'Instrument Sans',system-ui,sans-serif;color:#ece7dc;
  text-shadow:0 0 3px #000,0 0 6px #000,0 1px 2px #000;opacity:0;transition:opacity .15s ease;pointer-events:none}
.la-label small{display:block;margin-top:1px;font:500 11.5px/1.2 'Instrument Sans',system-ui,sans-serif;font-style:normal;
  letter-spacing:.02em;color:#b9b4aa;font-variant-numeric:tabular-nums}
.la-pin.day .la-label small{color:#f2c46f}
.la-pin.window .la-label small{color:#7fe0aa}
.la-pin:hover .la-label,.la-pin:focus-visible .la-label,.la-pin.sel .la-label,.la-pin.window .la-label,.la-pins.near .la-pin .la-label{opacity:1}
.la-pin.quiet:not(:hover):not(:focus-visible) .la-label{opacity:0}
.la-pin:hover,.la-pin:focus-visible{z-index:2}
.la-count{position:relative;min-width:24px;height:24px;padding:0 6px;box-sizing:border-box;border-radius:12px;display:flex;align-items:center;justify-content:center;
  font:600 12.5px/1 'Instrument Sans',system-ui,sans-serif;font-variant-numeric:tabular-nums;color:#ece7dc;background:rgba(0,0,0,.78);
  border:1.5px solid #ece7dc}
.la-count i{position:absolute;top:-7px;right:-11px;min-width:16px;height:16px;padding:0 4px;box-sizing:border-box;border-radius:8px;font:600 11px/16px 'Instrument Sans',system-ui,sans-serif;
  font-style:normal;color:#00170b;background:#5ed394;box-shadow:0 0 10px rgba(94,211,148,.7)}
`;

type PinEl = { site: PinSite; dir: THREE.Vector3; el: HTMLButtonElement; labelW?: number };

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
    // Labels that would overlap one already placed stay hidden until hovered (selected first).
    const boxes: [number, number, number, number][] = [];
    const singles = groups.filter((g) => g.length === 1).map((g) => vis[g[0]])
      .sort((a, b) => Number(b.p.site.site_id === this.selectedId) - Number(a.p.site.site_id === this.selectedId));
    for (const v of singles) {
      const lab = v.p.el.lastElementChild as HTMLElement;
      const lw = (v.p.labelW ||= lab.offsetWidth || 120);
      const box: [number, number, number, number] = [v.x + 14, v.y - 18, v.x + 24 + lw, v.y + 18];
      const hit = boxes.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
      v.p.el.classList.toggle('quiet', hit && v.p.site.site_id !== this.selectedId);
      if (!hit) boxes.push(box);
    }
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
      const green = g.filter((k) => vis[k].p.el.classList.contains('window')).length;
      const badge = btn.firstChild as HTMLElement;
      badge.textContent = String(g.length);
      if (green) { const i = document.createElement('i'); i.textContent = String(green); badge.appendChild(i); }
      btn.setAttribute('aria-label', `${g.length} sites close together${green ? `, ${green} with a landing window within 30 days` : ''}: ${members.map((m) => shortName(m.name)).join(', ')}. Zoom in`);
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
      for (const c of (p.el.dataset.state ?? '').split(' ')) if (c) p.el.classList.remove(c);
      for (const c of want.split(' ')) if (c) p.el.classList.add(c);
      p.el.dataset.state = want;
    }
  }

  /** The small line under each name (status from the API); empty restores the coordinates. */
  setNotes(notes: Record<string, string>): void {
    for (const p of this.pins) {
      const sm = p.el.querySelector('small');
      const text = notes[p.site.site_id] || coordText(p.site.latitude_deg, p.site.longitude_deg);
      if (sm && sm.textContent !== text) { sm.textContent = text; p.labelW = 0; }
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
