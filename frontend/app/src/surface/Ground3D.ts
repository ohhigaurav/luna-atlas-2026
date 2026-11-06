// Standing on the ground at a site (PRD F20 surface view, "Real 3D on the ground").
//
// What is real: the skyline. Its elevation angle in every direction is the site's horizon
// profile from the backend run (LOLA terrain where it exists, flat elsewhere), so a ridge hides
// the Sun exactly where the analysis says it does. The Sun and Earth sit at the run's azimuth and
// elevation for the clock's time, and Earth is lit from the Sun's direction, so its phase is right.
// What is illustrative: the ground between you and the skyline (we know the horizon angle per
// azimuth, not the distance to each ridge), the small bumps on it, and Earth's rotation. The HUD
// says so. Sunlight on the ground follows the run's visibility flag, not this mesh.
//
// Local frame: x = east, y = up, z = south (three's -z is north). Units: metres.
import * as THREE from 'three';

const D = 3000;            // distance to the skyline ring
const SKY = 40000;         // Sun and Earth distance
const EYE = 1.7;
const SUN_RADIUS_DEG = 0.2666;
const EARTH_RADIUS_DEG = 0.95;
const D2R = Math.PI / 180;

export type SkyState = {
  sunAz: number; sunEl: number; sunVisible: boolean;
  earthAz: number; earthEl: number; earthVisible: boolean;
};

export function dirOf(azDeg: number, elDeg: number, out = new THREE.Vector3()): THREE.Vector3 {
  const a = azDeg * D2R, e = elDeg * D2R;
  return out.set(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
}

/** Horizon elevation (deg) at any azimuth from the profile bins (linear, wraps at 360). */
export function horizonAt(profile: { az: number; el: number }[], azDeg: number): number {
  if (!profile.length) return 0;
  const a = ((azDeg % 360) + 360) % 360;
  let i = 0;
  while (i < profile.length && profile[i].az <= a) i++;
  const p0 = profile[(i - 1 + profile.length) % profile.length], p1 = profile[i % profile.length];
  let span = p1.az - p0.az; if (span <= 0) span += 360;
  let d = a - p0.az; if (d < 0) d += 360;
  return p0.el + (p1.el - p0.el) * (span > 0 ? d / span : 0);
}

function hash(x: number, y: number) {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}
function noise(x: number, y: number) {
  const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
  const u = xf * xf * (3 - 2 * xf), v = yf * yf * (3 - 2 * yf);
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * u + (c - a) * v + (a - b - c + d) * u * v;
}

function regolithTexture(): THREE.Texture {
  const N = 256, cv = document.createElement('canvas');
  cv.width = cv.height = N;
  const g = cv.getContext('2d')!, img = g.createImageData(N, N);
  for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
    let v = 0, amp = 0.5, f = 1 / 32;
    for (let o = 0; o < 5; o++) { v += amp * noise((x * f) % (N * f), (y * f) % (N * f)); amp *= 0.5; f *= 2; }
    const c = 118 + (v - 0.5) * 70, i = (y * N + x) * 4;
    img.data[i] = c; img.data[i + 1] = c * 0.985; img.data[i + 2] = c * 0.96; img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 8;
  return t;
}

function glowTexture(): THREE.Texture {
  const N = 256, cv = document.createElement('canvas');
  cv.width = cv.height = N;
  const g = cv.getContext('2d')!, r = g.createRadialGradient(N / 2, N / 2, 0, N / 2, N / 2, N / 2);
  r.addColorStop(0, 'rgba(255,255,250,1)');
  r.addColorStop(0.06, 'rgba(255,250,235,0.95)');
  r.addColorStop(0.16, 'rgba(255,236,200,0.35)');
  r.addColorStop(0.45, 'rgba(255,220,170,0.08)');
  r.addColorStop(1, 'rgba(255,220,170,0)');
  g.fillStyle = r; g.fillRect(0, 0, N, N);
  const t = new THREE.CanvasTexture(cv);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class Ground3D {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(60, 1, 0.1, SKY * 2);
  private sunLight = new THREE.DirectionalLight(0xfff6e8, 3.2);
  private ambient = new THREE.HemisphereLight(0x8fa3c0, 0x1a1a1a, 0.06);  // earthshine-ish floor, so night is not pure black
  private ground: THREE.Mesh | null = null;
  private sun: THREE.Group;
  private earth: THREE.Mesh;
  private stars: THREE.Points;
  private raf = 0;
  private yaw = 0;    // radians, 0 = north, clockwise
  private pitch = 0.06;
  private fov = 60;
  private drag: { x: number; y: number; yaw: number; pitch: number } | null = null;
  private ro: ResizeObserver;
  onHeading: (deg: number, pitchDeg: number) => void = () => {};

  private host: HTMLElement;

  constructor(host: HTMLElement) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.appendChild(this.renderer.domElement);
    this.scene.background = new THREE.Color(0x000000);

    this.camera.position.set(0, EYE, 0);
    this.scene.add(this.camera);

    // Sun light with a shadow camera over the terrain, so ridges throw long shadows at low Sun.
    this.sunLight.castShadow = true;
    const sc = this.sunLight.shadow.camera as THREE.OrthographicCamera;
    sc.left = -D; sc.right = D; sc.top = D; sc.bottom = -D; sc.near = 10; sc.far = 4 * D;
    this.sunLight.shadow.mapSize.set(4096, 4096);
    this.sunLight.shadow.bias = -0.0004;
    this.scene.add(this.sunLight, this.sunLight.target, this.ambient);

    // Stars: fixed random field (illustrative, like the globe view's).
    const n = 2500, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const u = hash(i, 1) * 2 - 1, t = hash(i, 2) * Math.PI * 2, r = Math.sqrt(1 - u * u);
      pos.set([r * Math.cos(t) * SKY * 1.2, u * SKY * 1.2, r * Math.sin(t) * SKY * 1.2], i * 3);
      const b = 0.35 + 0.65 * hash(i, 3) ** 3;
      col.set([b, b, b * (0.9 + 0.2 * hash(i, 4))], i * 3);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    sg.setAttribute('color', new THREE.BufferAttribute(col, 3));
    this.stars = new THREE.Points(sg, new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, depthWrite: false }));
    this.scene.add(this.stars);

    // Sun: a bright disc of the right size plus a glow (the camera's glare, not an atmosphere).
    this.sun = new THREE.Group();
    const disc = new THREE.Mesh(new THREE.CircleGeometry(SKY * Math.tan(SUN_RADIUS_DEG * D2R), 48),
      new THREE.MeshBasicMaterial({ color: 0xffffff, toneMapped: false }));
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: 0xffffff, depthWrite: false, transparent: true, blending: THREE.AdditiveBlending, toneMapped: false }));
    glow.scale.setScalar(SKY * Math.tan(9 * D2R));
    this.sun.add(glow, disc);
    this.scene.add(this.sun);

    // Earth: a sphere of the right apparent size, lit by the same Sun light (its phase is real).
    this.earth = new THREE.Mesh(new THREE.SphereGeometry(SKY * Math.tan(EARTH_RADIUS_DEG * D2R), 64, 48),
      new THREE.MeshStandardMaterial({ color: 0x5b86c9, roughness: 0.9, metalness: 0 }));
    this.scene.add(this.earth);

    const cv = this.renderer.domElement;
    cv.style.cursor = 'grab';
    cv.addEventListener('pointerdown', this.onDown);
    window.addEventListener('pointermove', this.onMove);
    window.addEventListener('pointerup', this.onUp);
    cv.addEventListener('wheel', this.onWheel, { passive: false });
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(host);
    this.resize();
    this.loop();
  }

  setEarthTexture(url: string) {
    new THREE.TextureLoader().load(url, (t) => {
      t.colorSpace = THREE.SRGBColorSpace;
      const m = this.earth.material as THREE.MeshStandardMaterial;
      m.map = t; m.color.set(0xffffff); m.needsUpdate = true;
    });
  }

  /** Build the ground from the horizon profile (azimuth bins, elevation in degrees). */
  setHorizon(profile: { az: number; el: number }[]) {
    if (this.ground) { this.scene.remove(this.ground); this.ground.geometry.dispose(); }
    const AZ = 360, RINGS = 90;
    const radii: number[] = [];
    for (let i = 0; i <= RINGS; i++) radii.push(2 * Math.pow(D / 2, i / RINGS));   // 2 m .. D, log spaced
    const pos = new Float32Array((AZ + 1) * (RINGS + 1) * 3), uv = new Float32Array((AZ + 1) * (RINGS + 1) * 2);
    for (let j = 0; j <= AZ; j++) {
      const az = (j / AZ) * 360, e = horizonAt(profile, az) * D2R;
      const top = EYE + D * Math.tan(e);                 // height that puts the rim at the horizon angle
      const sx = Math.sin(az * D2R), sz = -Math.cos(az * D2R);
      for (let i = 0; i <= RINGS; i++) {
        const r = radii[i], f = r / D;
        // Rises gently near you, to the real skyline at D; bumps grow with distance (illustrative).
        let h = top * Math.pow(f, 2.4);
        // Rolling ground: broad swells (hundreds of m), smaller bumps nearby; fades out toward the
        // skyline so the far field stays smooth (illustrative, see the header).
        const px = sx * r, pz = sz * r;
        h += (noise(px / 420 + 50, pz / 420 + 50) - 0.5) * Math.min(14, 0.02 * r) * (1 - f);
        h += (noise(px / 70 + 7, pz / 70 + 7) - 0.5) * Math.min(2.5, 0.015 * r) * (1 - f) * (1 - f);
        h += (noise(px / 6 + 9, pz / 6 + 9) - 0.5) * Math.min(0.35, 0.05 * r) * Math.max(0, 1 - r / 300);
        if (i === RINGS) h = top;                          // the rim is exactly the horizon
        const k = (j * (RINGS + 1) + i);
        pos.set([sx * r, h, sz * r], k * 3);
        uv.set([sx * r / 12, sz * r / 12], k * 2);
      }
    }
    const idx: number[] = [];
    for (let j = 0; j < AZ; j++) for (let i = 0; i < RINGS; i++) {
      const a = j * (RINGS + 1) + i, b = (j + 1) * (RINGS + 1) + i;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(idx);
    g.computeVertexNormals();
    // Fill the hole under your feet.
    const mat = new THREE.MeshStandardMaterial({ map: regolithTexture(), roughness: 1, metalness: 0, color: 0xd8d4cc, side: THREE.DoubleSide });
    this.ground = new THREE.Mesh(g, mat);
    this.ground.castShadow = true;
    this.ground.receiveShadow = true;
    const pad = new THREE.Mesh(new THREE.CircleGeometry(2.2, 32).rotateX(-Math.PI / 2), mat);
    pad.position.y = -0.02; pad.receiveShadow = true;
    this.ground.add(pad);
    this.scene.add(this.ground);
  }

  setSky(s: SkyState) {
    const sd = dirOf(s.sunAz, s.sunEl), ed = dirOf(s.earthAz, s.earthEl);
    this.sun.position.copy(sd).multiplyScalar(SKY);
    this.sun.lookAt(0, EYE, 0);
    this.earth.position.copy(ed).multiplyScalar(SKY);
    // Sunlight on the ground follows the analysis (terrain visibility), dimming over the last
    // fraction of a degree as the disc sinks behind the ridge.
    this.sunLight.position.copy(sd).multiplyScalar(2 * D);
    this.sunLight.target.position.set(0, 0, 0);
    this.sunLight.intensity = s.sunVisible ? 3.2 * Math.min(1, Math.max(0.15, (s.sunEl + 0.5) / 1.5)) : 0;
    // Earth stays lit by the Sun even when the ground is in shadow: use a separate light layer.
    const em = this.earth.material as THREE.MeshStandardMaterial;
    em.emissive.set(0x000000);
    this.earthLightDir.copy(sd);
    this.earthLit = true;
  }
  private earthLightDir = new THREE.Vector3(1, 0, 0);
  private earthLit = false;

  look(azDeg: number, elDeg = 6, fovDeg?: number) {
    this.yaw = azDeg * D2R;
    this.pitch = Math.max(-0.5, Math.min(1.2, elDeg * D2R));
    if (fovDeg) { this.fov = fovDeg; this.camera.fov = fovDeg; this.camera.updateProjectionMatrix(); }
  }

  private onDown = (e: PointerEvent) => {
    this.drag = { x: e.clientX, y: e.clientY, yaw: this.yaw, pitch: this.pitch };
    this.renderer.domElement.style.cursor = 'grabbing';
  };
  private onMove = (e: PointerEvent) => {
    if (!this.drag) return;
    const k = (this.fov * D2R) / this.host.clientHeight;
    this.yaw = this.drag.yaw - (e.clientX - this.drag.x) * k;
    this.pitch = Math.max(-0.6, Math.min(1.4, this.drag.pitch + (e.clientY - this.drag.y) * k));
  };
  private onUp = () => { this.drag = null; this.renderer.domElement.style.cursor = 'grab'; };
  private onWheel = (e: WheelEvent) => {
    e.preventDefault();
    this.fov = Math.max(12, Math.min(80, this.fov * Math.exp(e.deltaY * 0.001)));
    this.camera.fov = this.fov;
    this.camera.updateProjectionMatrix();
  };

  private resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = `${w}px`;
    this.renderer.domElement.style.height = `${h}px`;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private loop = () => {
    this.raf = requestAnimationFrame(this.loop);
    const f = dirOf(this.yaw / D2R, this.pitch / D2R);
    this.camera.lookAt(this.camera.position.clone().add(f));
    // Earth: lit by the Sun regardless of ground shadow. Render it with the light at full strength.
    const keep = this.sunLight.intensity;
    this.renderer.render(this.scene, this.camera);
    if (this.earthLit && keep === 0) {
      // Ground is in shadow but Earth is still sunlit: draw Earth again on top with the light on.
      this.sunLight.intensity = 3.2;
      this.renderer.autoClear = false;
      const vis = this.scene.children.map((c) => c.visible);
      this.scene.children.forEach((c) => { c.visible = c === this.earth || c === this.sunLight || c === this.sunLight.target || c === this.camera; });
      this.sunLight.castShadow = false;
      this.renderer.render(this.scene, this.camera);
      this.sunLight.castShadow = true;
      this.scene.children.forEach((c, i) => { c.visible = vis[i]; });
      this.renderer.autoClear = true;
      this.sunLight.intensity = keep;
    }
    this.onHeading(((this.yaw / D2R) % 360 + 360) % 360, this.pitch / D2R);
  };

  dispose() {
    cancelAnimationFrame(this.raf);
    this.ro.disconnect();
    window.removeEventListener('pointermove', this.onMove);
    window.removeEventListener('pointerup', this.onUp);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
