// Earth at its true distance and size (scene unit = 1 Moon radius = 1737.4 km), lit by the same
// Sun direction as the Moon, so its phase is right by construction. The day map is decoration
// (Earth's own rotation is not modelled); its direction and phase come from /api/sky-geometry.
import * as THREE from 'three';

export const MOON_RADIUS_KM = 1737.4;
export const EARTH_RADIUS = 6378.1366 / MOON_RADIUS_KM;   // ~3.67 Moon radii
export const EARTH_MEAN_DISTANCE = 384400 / MOON_RADIUS_KM; // ~221 Moon radii

export type EarthObject = {
  group: THREE.Group;
  setSun: (sunWorld: THREE.Vector3) => void;
  place: (dirWorld: THREE.Vector3, distance: number) => void;
  setMap: (map: THREE.Texture) => void;
};

export function createEarth(dayMap: THREE.Texture | null): EarthObject {
  const group = new THREE.Group();
  const sun = { value: new THREE.Vector3(1, 0, 0) };
  const map = { value: dayMap }, hasMap = { value: dayMap ? 1 : 0 };
  const surface = new THREE.Mesh(
    new THREE.SphereGeometry(EARTH_RADIUS, 96, 48),
    new THREE.ShaderMaterial({
      uniforms: { dayMap: map, hasMap, sunDir: sun },
      vertexShader: /* glsl */ `
        varying vec3 vN; varying vec2 vUv; varying vec3 vW;
        void main() { vUv = uv; vN = normalize(mat3(modelMatrix) * normal);
          vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: /* glsl */ `
        uniform sampler2D dayMap; uniform float hasMap; uniform vec3 sunDir;
        varying vec3 vN; varying vec2 vUv; varying vec3 vW;
        void main() {
          vec3 n = normalize(vN);
          vec3 base = hasMap > 0.5 ? texture2D(dayMap, vUv).rgb : vec3(0.10, 0.22, 0.42);
          float d = dot(n, normalize(sunDir));
          float lit = smoothstep(-0.08, 0.25, d);
          vec3 V = normalize(cameraPosition - vW);
          float fres = pow(1.0 - max(dot(n, V), 0.0), 3.0);
          vec3 col = base * (0.02 + 1.35 * lit) + vec3(0.30, 0.55, 1.0) * fres * 0.55 * smoothstep(-0.2, 0.3, d);
          gl_FragColor = vec4(col, 1.0);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`,
    }),
  );
  // Thin atmosphere shell: back faces, additive, brightest on the sunlit limb.
  const atmo = new THREE.Mesh(
    new THREE.SphereGeometry(EARTH_RADIUS * 1.035, 96, 48),
    new THREE.ShaderMaterial({
      uniforms: { sunDir: sun },
      vertexShader: /* glsl */ `
        varying vec3 vN; varying vec3 vW;
        void main() { vN = normalize(mat3(modelMatrix) * normal); vec4 w = modelMatrix * vec4(position, 1.0);
          vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: /* glsl */ `
        uniform vec3 sunDir; varying vec3 vN; varying vec3 vW;
        void main() { vec3 n = normalize(vN); vec3 V = normalize(cameraPosition - vW);
          float rim = pow(1.0 - abs(dot(n, V)), 2.5);
          float day = smoothstep(-0.25, 0.35, dot(n, normalize(sunDir)));
          gl_FragColor = vec4(vec3(0.35, 0.65, 1.0) * rim * day * 1.6, 1.0); }`,
      side: THREE.BackSide, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    }),
  );
  group.add(surface, atmo);
  return {
    group,
    setSun: (s) => { sun.value.copy(s).normalize(); },
    place: (dir, distance) => { group.position.copy(dir).normalize().multiplyScalar(distance); },
    setMap: (m) => { m.colorSpace = THREE.SRGBColorSpace; map.value = m; hasMap.value = 1; },
  };
}
