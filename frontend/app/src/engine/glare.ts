// The Sun as seen from lunar orbit: a small white disc with a wide soft glare, placed in the true
// Sun direction far behind everything. Depth-tested, so the Moon occults it at the limb.
import * as THREE from 'three';

function radialTexture(stops: [number, string][], size = 256): THREE.CanvasTexture {
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const g = c.getContext('2d')!;
  const grd = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  for (const [o, col] of stops) grd.addColorStop(o, col);
  g.fillStyle = grd;
  g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export type SunGlare = { group: THREE.Group; place: (dirWorld: THREE.Vector3) => void };

export function createSunGlare(distance = 1800): SunGlare {
  const group = new THREE.Group();
  const mk = (tex: THREE.Texture, scale: number, opacity: number) => {
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({
      map: tex, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: true,
      transparent: true, opacity, toneMapped: false,
    }));
    sp.scale.setScalar(scale);
    return sp;
  };
  // True angular radius of the Sun ~0.267 deg -> disc radius at `distance`.
  const discR = distance * Math.tan((0.267 * Math.PI) / 180);
  const disc = mk(radialTexture([[0, '#ffffff'], [0.45, '#fffaf0'], [0.5, 'rgba(255,240,220,0)'], [1, 'rgba(0,0,0,0)']]), discR * 4, 1);
  const glow = mk(radialTexture([[0, 'rgba(255,244,225,0.9)'], [0.08, 'rgba(255,214,150,0.35)'], [0.3, 'rgba(246,185,74,0.08)'], [1, 'rgba(0,0,0,0)']]), distance * 0.22, 0.9);
  group.add(glow, disc);
  return { group, place: (dir) => { group.position.copy(dir).normalize().multiplyScalar(distance); } };
}
