// Luna Atlas globe: an imperative three.js engine that React mounts once (see GlobeView.tsx).
// Why not react-three-fiber here: camera choreography, per-frame marker projection and lighting
// all run inside one render loop with no React re-renders, and the engine has no React dependency,
// so it can be rendered headless on its own. React owns the HUD; this owns the canvas.
//
// Scene unit = 1 Moon radius (1737.4 km). three.js +Y = lunar north (MOON_ME +Z).
// Everything physical (Sun, Earth direction and phase, terminator) comes from opts.sky(), which
// the app feeds from /api/sky-geometry. Camera motion (opening, drift, flights) is presentation.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createLunarMaterial, loadLolaHeights, meToThree, updateLunarMaterial } from '../scene/lunarMaterial';
import { createStars } from './stars';
import { createEarth, EARTH_MEAN_DISTANCE, MOON_RADIUS_KM } from './earth';
import { createSunGlare } from './glare';
import { PinLayer, latLonToThree, type PinSite } from './pins';
import { Tweens, ease } from './tween';

type Vec3 = [number, number, number];

export type SkySample = {
  sunDir: Vec3;            // MOON_ME unit vector, Moon -> Sun
  earthDir: Vec3;          // MOON_ME unit vector, Moon -> Earth
  earthIllumFrac: number;  // 0..1
  earthDistanceKm?: number;
};

export type EngineOptions = {
  sites: PinSite[];
  sky: (ms: number) => SkySample;
  cursorMs: () => number;
  textures: {
    moonColor: string;
    moonHeights: { url: string; width: number; height: number };
    /** Polar stereographic height caps (lola_to_f16.py --caps); removes radial streaks near the poles. */
    moonCaps?: { south: string; north: string; size: number; latDeg: number };
    earthDay?: string;
  };
  reducedMotion?: boolean;
  /** 1 = true LOLA relief. Anything else must be labelled on screen. */
  reliefExaggeration?: number;
  /** Sphere detail (longitude segments; latitude gets half). 512 default; 256 for weak GPUs. */
  sphereSegments?: number;
  /** Device pixel ratio cap (2 default; 1 for weak GPUs). */
  maxPixelRatio?: number;
  onSelect?: (site: PinSite | null) => void;
  onIntroDone?: () => void;
  onError?: (message: string) => void;
};

const HOME_DISTANCE = 4.6;   // whole disc between the top bar and the time rail (fov 35 deg)
const EXPOSURE = 1.2;
const INTRO_EXPOSURE = 0.7;  // opening shot: the lit Earth and the star field read, the night side stays dark
const HOME_SHIFT = 0.15;     // default framing before the HUD reports its panels (setInsets)
const D2R = Math.PI / 180;
const UP = new THREE.Vector3(0, 1, 0);

export class GlobeEngine {
  readonly renderer: THREE.WebGLRenderer;
  readonly scene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  private moon: THREE.Mesh;
  private moonMat: THREE.ShaderMaterial | null = null;
  private stars = createStars();
  private earth = createEarth(null);
  private glare = createSunGlare();
  private pins: PinLayer;
  private tweens = new Tweens();
  private raf = 0;
  private last = performance.now();
  private drifting = false;
  private lastInput = performance.now();
  private flying = false;
  private mode: 'globe' | 'site' = 'globe';
  private resizeObs: ResizeObserver;
  private sunWorld = new THREE.Vector3(1, 0, 0);
  private earthWorld = new THREE.Vector3(1, 0, 0);
  private shift = 0;          // horizontal framing offset, fraction of width
  private homeShift = HOME_SHIFT; // centre of the area the HUD panels leave free
  private grid: THREE.LineSegments;
  private ray = new THREE.Raycaster();
  private introPut: ((k: number) => void) | null = null;
  private skipRequested = false;
  private disposed = false;
  private readonly onKey = (e: KeyboardEvent) => {
    // Keys typed into the HUD (search box, sliders) or meant for an open sheet are not for the camera.
    const t = e.target as HTMLElement | null;
    if (e.defaultPrevented || t?.closest?.('input, textarea, select') || document.querySelector('.la-sheet, .la-scrim')) return;
    if (this.tweens.active && !e.repeat) { this.tweens.finishAll(); if (e.key !== 'Escape') return; } // any key skips
    if (e.key === 'Escape' && this.mode === 'site') this.flyHome();
  };
  private readonly onInput = () => { this.drifting = false; this.lastInput = performance.now(); };

  private container: HTMLElement;
  private opts: EngineOptions;

  constructor(container: HTMLElement, opts: EngineOptions) {
    this.container = container;
    this.opts = opts;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, opts.maxPixelRatio ?? 2));
    this.renderer.toneMapping = THREE.AgXToneMapping;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMappingExposure = opts.reducedMotion ? EXPOSURE : INTRO_EXPOSURE;
    this.renderer.setClearColor(0x020308, 1);
    const cv = this.renderer.domElement;
    cv.style.display = 'block';
    cv.style.width = '100%';
    cv.style.height = '100%';
    cv.setAttribute('aria-label', 'The Moon. Drag to turn, scroll to zoom, Tab to reach landing sites.');
    container.appendChild(cv);

    this.camera = new THREE.PerspectiveCamera(35, 1, 0.0005, 5000);
    this.scene.add(this.stars, this.glare.group, this.earth.group);
    this.moon = new THREE.Mesh(new THREE.SphereGeometry(1, opts.sphereSegments ?? 512, Math.round((opts.sphereSegments ?? 512) / 2)), new THREE.MeshBasicMaterial({ color: 0x15181f }));
    this.scene.add(this.moon);
    this.grid = createGraticule();
    this.scene.add(this.grid);

    this.controls = new OrbitControls(this.camera, cv);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.enablePan = false;
    this.controls.minDistance = 1.02;
    this.controls.maxDistance = 16;
    this.controls.zoomSpeed = 0.9;
    this.controls.addEventListener('start', this.onInput);
    cv.addEventListener('wheel', this.onInput, { passive: true });
    window.addEventListener('keydown', this.onKey);

    this.pins = new PinLayer(container, opts.sites, (s) => this.flyToSite(s), (dir) => this.flyToPoint(dir, 1.1, 20));

    this.resizeObs = new ResizeObserver(() => this.resize());
    this.resizeObs.observe(container);
    this.resize();
    this.updateSky();
    this.placeIntroCamera();
    // The opening move waits for the Moon maps: no flight over a placeholder sphere.
    this.loadTextures().finally(() => { if (!this.disposed) this.startIntro(); });
    this.raf = requestAnimationFrame(this.frame);
  }

  // ---------------------------------------------------------------- assets

  private async loadTextures(): Promise<void> {
    const t = this.opts.textures;
    try {
      const capsP = t.moonCaps
        ? Promise.all([
            loadLolaHeights(t.moonCaps.south, t.moonCaps.size, t.moonCaps.size),
            loadLolaHeights(t.moonCaps.north, t.moonCaps.size, t.moonCaps.size),
          ]).catch(() => null) // caps are an improvement, not a requirement
        : Promise.resolve(null);
      const [color, heights, caps] = await Promise.all([
        new THREE.TextureLoader().loadAsync(t.moonColor),
        loadLolaHeights(t.moonHeights.url, t.moonHeights.width, t.moonHeights.height),
        capsP,
      ]);
      if (caps) for (const c of caps) { c.wrapS = c.wrapT = THREE.ClampToEdgeWrapping; c.needsUpdate = true; }
      if (this.disposed) return;
      color.colorSpace = THREE.SRGBColorSpace;
      color.wrapS = THREE.RepeatWrapping;
      color.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
      const s = this.opts.sky(this.opts.cursorMs());
      this.moonMat = createLunarMaterial({
        colorMap: color, dispMap: heights, sunDirMe: s.sunDir, earthDirMe: s.earthDir, earthIllumFrac: s.earthIllumFrac,
        caps: caps && t.moonCaps ? { south: caps[0], north: caps[1], latDeg: t.moonCaps.latDeg } : undefined,
      });
      this.moonMat.uniforms.heightScale.value = (this.opts.reliefExaggeration ?? 1) / MOON_RADIUS_KM;
      (this.moon.material as THREE.Material).dispose();
      this.moon.material = this.moonMat;
    } catch (e) {
      this.opts.onError?.(`Moon maps failed to load (${(e as Error).message}). Run "npm run textures".`);
    }
    if (t.earthDay) {
      new THREE.TextureLoader().loadAsync(t.earthDay).then((m) => { if (!this.disposed) this.earth.setMap(m); }, () => { /* plain Earth is fine */ });
    }
  }

  /** Skip whatever camera move is running (the opening or a flight) and land at its end. */
  skip(): void {
    if (this.tweens.active) this.tweens.finishAll();
    else this.skipRequested = true;                 // maps still loading: land home when they arrive
  }

  setReliefExaggeration(x: number): void {
    this.opts.reliefExaggeration = x;
    if (this.moonMat) this.moonMat.uniforms.heightScale.value = x / MOON_RADIUS_KM;
  }

  // ---------------------------------------------------------------- camera choreography

  /**
   * Opening: an Earthrise. Start far out behind the Moon so Earth hangs beside it in its true
   * direction and phase; once the maps are loaded, swing round and glide in to the home view while
   * the exposure comes up; then drift. Camera motion is presentation; the lighting is data.
   */
  private placeIntroCamera(): void {
    const h = new THREE.Vector3(this.sunWorld.x, 0, this.sunWorld.z);
    if (h.lengthSq() < 1e-6) h.set(1, 0, 0);
    const az = Math.atan2(h.z, h.x) + 62 * D2R;   // terminator in view, ~70% of the disc lit
    const lat = -24 * D2R;                        // south pole tilted toward the viewer
    const home = new THREE.Vector3(Math.cos(lat) * Math.cos(az), Math.sin(lat), Math.cos(lat) * Math.sin(az));
    const e = this.earthWorld.clone();
    const north = UP.clone().sub(e.clone().multiplyScalar(e.dot(UP)));
    if (north.lengthSq() < 1e-6) north.set(1, 0, 0);
    // Opposite Earth, nudged 11 deg so Earth clears the Moon's disc (5 deg wide from 11 radii).
    const startDir = e.clone().negate().add(north.normalize().multiplyScalar(0.2)).normalize();
    if (this.opts.reducedMotion) {
      this.camera.position.copy(home).multiplyScalar(HOME_DISTANCE);
      this.camera.lookAt(0, 0, 0);
      this.introDone();
      return;
    }
    this.pins.root.style.opacity = '0';
    this.controls.enabled = false;
    const q = new THREE.Quaternion().setFromUnitVectors(startDir, home), qk = new THREE.Quaternion(), I = new THREE.Quaternion();
    this.introPut = (k: number) => {
      qk.slerpQuaternions(I, q, ease.inOutSine(Math.min(1, k * 1.15)));
      this.camera.position.copy(startDir).applyQuaternion(qk).multiplyScalar(THREE.MathUtils.lerp(11, HOME_DISTANCE, ease.outCubic(k)));
      this.camera.lookAt(0, 0, 0);
    };
    this.introPut(0);
    // Start partly exposed so the lit Earth already hangs beside the Moon's dark limb (the
    // Earthrise), then open up to full exposure as the camera swings onto the day side.
    this.renderer.toneMappingExposure = INTRO_EXPOSURE;
    (this.stars.material as THREE.ShaderMaterial).uniforms.opacity.value = 0;
  }

  private startIntro(): void {
    const put = this.introPut;
    this.introPut = null;
    if (!put) return;                               // reduced motion: already home
    if (this.skipRequested) { put(1); this.introDone(); return; }
    const now = performance.now();
    const starMat = this.stars.material as THREE.ShaderMaterial;
    this.tweens.add({ duration: 1600, easing: ease.inOutSine, step: (k) => { starMat.uniforms.opacity.value = k; } }, now);
    this.tweens.add({ delay: 1200, duration: 3600, easing: ease.inOutSine, step: (k) => { this.renderer.toneMappingExposure = THREE.MathUtils.lerp(INTRO_EXPOSURE, EXPOSURE, k); } }, now);
    this.tweens.add({ delay: 2500, duration: 5500, easing: ease.inOutSine, step: (k) => { this.setShift(k * this.homeShift); } }, now);
    this.tweens.add({ duration: 8000, easing: ease.linear, step: put, done: () => this.introDone() }, now);
  }

  private introDone(): void {
    this.renderer.toneMappingExposure = EXPOSURE;
    this.setShift(this.homeShift);
    this.pins.root.style.transition = 'opacity .6s ease';
    this.pins.root.style.opacity = '1';
    (this.stars.material as THREE.ShaderMaterial).uniforms.opacity.value = 1;
    this.controls.target.set(0, 0, 0);
    this.controls.enabled = true;
    this.controls.update();
    this.drifting = !this.opts.reducedMotion;
    this.opts.onIntroDone?.();
  }

  /**
   * The HUD reports how much of the left and right edges its panels cover; the globe is framed in
   * the space between (desktop only; phones keep the vertical framing).
   */
  setInsets(leftPx: number, rightPx: number): void {
    const w = this.container.clientWidth || 1;
    const next = (leftPx - rightPx) / (2 * w);
    if (Math.abs(next - this.homeShift) < 1e-4) return;
    this.homeShift = next;
    if (this.introPut || this.flying) return;   // the running move ends on the new framing
    const s0 = this.shift;
    this.tweens.add({ duration: this.opts.reducedMotion ? 0 : 450, easing: ease.inOutCubic,
      step: (k) => this.setShift(THREE.MathUtils.lerp(s0, next, k)) }, performance.now());
  }

  /** Planetocentric latitude / east longitude under a screen point (CSS px in the container), or null. */
  pick(x: number, y: number): { lat: number; lon: number } | null {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.ray.setFromCamera(new THREE.Vector2((x / w) * 2 - 1, 1 - (y / h) * 2), this.camera);
    const o = this.ray.ray.origin, d = this.ray.ray.direction;
    const b = o.dot(d), c = o.lengthSq() - 1, disc = b * b - c;
    if (disc < 0) return null;
    const t = -b - Math.sqrt(disc);
    if (t < 0) return null;
    const p = o.clone().addScaledVector(d, t);
    const lat = Math.asin(Math.max(-1, Math.min(1, p.y))) / D2R;
    let lon = Math.atan2(-p.z, p.x) / D2R;
    if (lon < 0) lon += 360;
    return { lat, lon };
  }

  /** Latitude/longitude lines every 15 deg (equator and prime meridian brighter). */
  setGrid(on: boolean): void { this.grid.visible = on; }

  /** Live state per site (e.g. 'day' / 'night'), shown on its marker. */
  setPinStates(states: Record<string, string>): void { this.pins.setStates(states); }
  setPinNotes(notes: Record<string, string>): void { this.pins.setNotes(notes); }

  /** Screen position (CSS px) of a surface point and whether it faces the camera. */
  project(latDeg: number, lonDeg: number): { x: number; y: number; facing: boolean } {
    return this.screenOf({ site_id: '', name: '', latitude_deg: latDeg, longitude_deg: lonDeg });
  }

  /** Where a site is on screen right now (CSS px in the container), and whether it faces us. */
  screenOf(site: PinSite): { x: number; y: number; facing: boolean } {
    const p = latLonToThree(site.latitude_deg, site.longitude_deg);
    const toCam = this.camera.position.clone().sub(p);
    const facing = p.dot(toCam) > 0;
    const ndc = p.clone().project(this.camera);
    return { x: (ndc.x + 1) / 2 * this.container.clientWidth, y: (1 - ndc.y) / 2 * this.container.clientHeight, facing };
  }

  flyToSite(site: PinSite): void {
    this.pins.selectedId = site.site_id;
    this.opts.onSelect?.(site);
    // Orbital oblique view ~1800 km out: the closest the global 4k/8k maps stay sharp. Standing on
    // the surface is the SurfaceSky view (from the run's horizon), not a closer zoom of these maps.
    this.flyToPoint(latLonToThree(site.latitude_deg, site.longitude_deg), 1.05, 50, 1);
  }

  /** Google Earth-style hop: rise, swing over the surface, descend into an oblique view. */
  flyToPoint(dir: THREE.Vector3, distance: number, tiltDeg: number, targetRadius = 0): void {
    const n = dir.clone().normalize();
    const T1 = n.clone().multiplyScalar(targetRadius);
    let north = UP.clone().sub(n.clone().multiplyScalar(n.dot(UP)));
    if (north.lengthSq() < 1e-6) north = this.camera.position.clone().sub(n.clone().multiplyScalar(n.dot(this.camera.position)));
    if (north.lengthSq() < 1e-6) north.set(1, 0, 0);
    north.normalize();
    // Camera sits on the equator side of the site looking poleward, so polar sites show the pole.
    const side = n.y < 0 ? north : north.clone().negate();
    const tilt = tiltDeg * D2R;
    const offset = n.clone().multiplyScalar(Math.cos(tilt)).add(side.multiplyScalar(Math.sin(tilt))).multiplyScalar(distance);
    const C1 = T1.clone().add(offset);
    this.mode = targetRadius > 0 ? 'site' : 'globe';
    this.fly(C1, T1);
  }

  /** Look at the Moon from Earth's direction: the phase you would see in the sky at this moment. */
  viewFromEarth(): void {
    this.pins.selectedId = null;
    this.opts.onSelect?.(null);
    this.mode = 'globe';
    this.fly(this.earthWorld.clone().setLength(HOME_DISTANCE), new THREE.Vector3());
  }

  flyHome(): void {
    this.pins.selectedId = null;
    this.opts.onSelect?.(null);
    this.mode = 'globe';
    this.fly(this.camera.position.clone().setLength(HOME_DISTANCE), new THREE.Vector3());
  }

  private fly(C1: THREE.Vector3, T1: THREE.Vector3): void {
    this.drifting = false;
    this.lastInput = performance.now();
    this.tweens.finishAll();
    const C0 = this.camera.position.clone(), T0 = this.controls.target.clone();
    const d0 = C0.length(), d1 = C1.length();
    const u0 = C0.clone().normalize(), u1 = C1.clone().normalize();
    const angle = u0.angleTo(u1);
    const q = new THREE.Quaternion().setFromUnitVectors(u0, u1), qk = new THREE.Quaternion(), I = new THREE.Quaternion();
    const hop = Math.min(1.4, angle * 0.75) * (d0 < 2 || d1 < 2 ? 1 : 0.25);
    const duration = this.opts.reducedMotion ? 0 : Math.min(2000, 1100 + 520 * angle);
    this.flying = true;
    this.controls.enabled = false;
    const tgt = new THREE.Vector3();
    const s0 = this.shift;  // ends on homeShift as it is at each step (panels may open mid-flight)
    this.tweens.add({
      duration, easing: ease.inOutCubic,
      step: (k) => {
        qk.slerpQuaternions(I, q, k);
        const r = THREE.MathUtils.lerp(d0, d1, k) + hop * Math.sin(Math.PI * k);
        this.camera.position.copy(u0).applyQuaternion(qk).multiplyScalar(r);
        tgt.lerpVectors(T0, T1, ease.inOutSine(k));
        this.camera.lookAt(tgt);
        this.setShift(THREE.MathUtils.lerp(s0, this.homeShift, k));
      },
      done: () => {
        this.flying = false;
        this.camera.position.copy(C1);
        this.controls.target.copy(T1);
        const site = this.mode === 'site';
        this.controls.minDistance = site ? 0.015 : 1.02;
        this.controls.maxDistance = site ? 4 : 16;
        this.controls.rotateSpeed = site ? 0.35 : 0.6;
        this.controls.enabled = true;
        this.controls.update();
      },
    }, performance.now());
  }

  // ---------------------------------------------------------------- per frame

  private updateSky(): void {
    const s = this.opts.sky(this.opts.cursorMs());
    this.sunWorld.copy(meToThree(s.sunDir)).normalize();
    const earthDir = this.earthWorld.copy(meToThree(s.earthDir)).normalize();
    this.earth.place(earthDir, s.earthDistanceKm ? s.earthDistanceKm / MOON_RADIUS_KM : EARTH_MEAN_DISTANCE);
    this.earth.setSun(this.sunWorld);
    this.glare.place(this.sunWorld);
    if (this.moonMat) updateLunarMaterial(this.moonMat, this.moon, this.camera, s.sunDir, s.earthDir, s.earthIllumFrac);
  }

  private frame = (now: number): void => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.frame);
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    this.tweens.update(now);
    if (!this.drifting && !this.flying && this.mode === 'globe' && !this.opts.reducedMotion && now - this.lastInput > 45000) this.drifting = true;
    if (this.drifting && this.mode === 'globe' && !this.flying) {
      this.camera.position.applyAxisAngle(UP, 0.7 * D2R * dt); // slow turn about the lunar axis
    }
    if (!this.flying && this.controls.enabled) this.controls.update();
    if (this.camera.position.length() < 1.008) this.camera.position.setLength(1.008); // never inside the Moon
    this.updateSky();
    // Eye adaptation: the bright, sunlit Moon filling the view washes faint stars out.
    const angR = Math.asin(Math.min(1, 1 / this.camera.position.length()));
    const cover = Math.min(1, Math.pow(angR / ((this.camera.fov * D2R) / 2), 2));
    const starMat = this.stars.material as THREE.ShaderMaterial;
    if (!this.tweens.active) starMat.uniforms.opacity.value = 1 - 0.8 * cover;
    this.stars.position.copy(this.camera.position); // stars at infinity
    this.renderer.render(this.scene, this.camera);
    const sz = this.renderer.getSize(new THREE.Vector2());
    this.pins.update(this.camera, sz.x, sz.y);
  };

  /** Off-centre framing via a projection view offset (orbiting still pivots on the target). */
  private setShift(f: number): void {
    this.shift = f;
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    if (w < 760) {
      // Phones: the title block takes the lower half, so the globe moves into the upper part.
      this.camera.setViewOffset(w, h, 0, 0.24 * h, w, h);
      return;
    }
    // Desktop: centre on the area between the panels (f) and between the top bar (44 px) and the
    // time rail (~70 px), so the disc never sits under the HUD.
    this.camera.setViewOffset(w, h, -f * w, 13, w, h);
  }

  private resize(): void {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // Keep at least 35 deg across in portrait too, so the whole disc fits a phone's width.
    this.camera.fov = w >= h ? 35 : THREE.MathUtils.radToDeg(2 * Math.atan(Math.tan(17.5 * D2R) * (h / w)));
    this.setShift(this.shift);
    this.camera.updateProjectionMatrix();
    (this.stars.material as THREE.ShaderMaterial).uniforms.pixelRatio.value = this.renderer.getPixelRatio();
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    this.resizeObs.disconnect();
    window.removeEventListener('keydown', this.onKey);
    this.controls.dispose();
    this.pins.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

/** A cartographic graticule just above the mean surface, faint enough not to fight the terrain. */
function createGraticule(): THREE.LineSegments {
  const R = 1.0012, pts: number[] = [], major: number[] = [];
  const push = (a: THREE.Vector3, b: THREE.Vector3, m: boolean) => { (m ? major : pts).push(a.x, a.y, a.z, b.x, b.y, b.z); };
  for (let lat = -75; lat <= 75; lat += 15) {
    for (let lon = 0; lon < 360; lon += 2) push(latLonToThree(lat, lon).multiplyScalar(R), latLonToThree(lat, lon + 2).multiplyScalar(R), lat === 0);
  }
  for (let lon = 0; lon < 360; lon += 15) {
    for (let lat = -88; lat < 88; lat += 2) push(latLonToThree(lat, lon).multiplyScalar(R), latLonToThree(lat + 2, lon).multiplyScalar(R), lon === 0);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute([...pts, ...major], 3));
  const n = pts.length / 3;
  geo.addGroup(0, n, 0);
  geo.addGroup(n, major.length / 3, 1);
  const mat = (o: number) => new THREE.LineBasicMaterial({ color: 0xb8c6d8, transparent: true, opacity: o, depthWrite: false, toneMapped: false });
  const lines = new THREE.LineSegments(geo, [mat(0.09), mat(0.2)]);
  lines.renderOrder = 1;
  lines.visible = false;
  return lines;
}
