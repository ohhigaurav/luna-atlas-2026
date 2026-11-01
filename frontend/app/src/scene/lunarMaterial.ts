// src/scene/lunarMaterial.ts
// Physically motivated Moon shading for MoonGlobe.
//
// Why not MeshStandardMaterial: Lambert/GGX shading darkens a sphere toward the
// limb, so the full Moon looks like a plastic ball. Real regolith is closer to a
// Lommel-Seeliger surface: the lit disc stays nearly flat-bright to the limb and
// the terminator is sharp. McEwen's lunar-Lambert model blends the two with a
// phase-dependent weight L(g).
//
// Frame contract: every direction uniform is in MOON_ME (the frame
// /api/sky-geometry returns), converted once by meToThree(). Texture lookup is
// computed from the fragment's lat/lon in that same frame, so the drawn
// terminator and the backend's subsolar point cannot disagree through a UV
// convention mismatch (the PRD's F1 check: terminator within 1 deg).

import * as THREE from 'three';

/** MOON_ME (X: lon 0 lat 0, Y: lon 90 E, Z: north) -> three.js (Y up). Right-handed both ways. */
export function meToThree(v: readonly [number, number, number]): THREE.Vector3 {
  return new THREE.Vector3(v[0], v[2], -v[1]);
}

/** Inverse of meToThree, for tests and for reading back picked points. */
export function threeToMe(v: THREE.Vector3): [number, number, number] {
  return [v.x, -v.z, v.y];
}

/** Planetocentric lat/lon (deg, lon east-positive 0-360) of a three.js direction. */
export function latLonOf(v: THREE.Vector3): { latDeg: number; lonDeg: number } {
  const [x, y, z] = threeToMe(v.clone().normalize());
  const lat = THREE.MathUtils.radToDeg(Math.asin(THREE.MathUtils.clamp(z, -1, 1)));
  let lon = THREE.MathUtils.radToDeg(Math.atan2(y, x));
  if (lon < 0) lon += 360;
  return { latDeg: lat, lonDeg: lon };
}

/**
 * Lunar-Lambert weight L(g), g = phase angle in degrees.
 * Cubic from McEwen's lunar photometric work (Icarus 1991; LPSC 1996).
 * VERIFY the coefficients against the paper before quoting them in the write-up;
 * the visual result is insensitive to small changes, the citation is not.
 */
export function lunarLambertL(gDeg: number): number {
  const g = THREE.MathUtils.clamp(gDeg, 0, 180);
  return 1 - 0.019 * g + 2.42e-4 * g * g - 1.46e-6 * g * g * g;
}

export type LunarUniforms = {
  colorMap: THREE.Texture;        // SVS CGI Moon Kit colour, equirectangular, lon -180..180 left to right
  dispMap: THREE.DataTexture;     // LOLA heights in km (R, half-float), from loadLolaHeights(); 0 = 1737.4 km sphere
  sunDirMe: [number, number, number];   // unit vector Moon -> Sun, MOON_ME, from /api/sky-geometry at cursorUtc
  earthDirMe: [number, number, number]; // unit vector Moon -> Earth, MOON_ME
  earthIllumFrac: number;         // 0..1, from /api/sky-geometry
};

const vert = /* glsl */ `
  varying vec3 vObjN;     // object-space unit normal of the sphere (three frame)
  varying vec3 vWorldPos;
  void main() {
    vObjN = normalize(position);
    vec4 wp = modelMatrix * vec4(position, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const frag = /* glsl */ `
  precision highp float;
  uniform sampler2D colorMap;
  uniform sampler2D dispMap;
  uniform vec2  texel;          // 1/width, 1/height of dispMap
  uniform vec2  kSlope;         // km of height difference -> slope, east (at equator) and north
  uniform float reliefGain;     // 1.0 = true slopes; anything else is exaggeration and must be labelled
  uniform vec3  sunDir;         // object space (three frame), unit
  uniform vec3  earthDir;       // object space (three frame), unit
  uniform float earthIllum;     // 0..1
  uniform float earthshineGain; // display boost; real earthshine is ~1e-4 of sunlight
  uniform float L;              // lunarLambertL(phase angle), set per frame on the CPU
  uniform mat3  objToWorldN;    // normal matrix (object -> world)
  varying vec3 vObjN;
  varying vec3 vWorldPos;

  const float PI = 3.141592653589793;

  // three frame -> MOON_ME: (x, -z, y)
  vec2 uvOf(vec3 n) {
    vec3 me = vec3(n.x, -n.z, n.y);
    float lon = atan(me.y, me.x);           // -pi..pi, east positive
    float lat = asin(clamp(me.z, -1.0, 1.0));
    return vec2(lon / (2.0 * PI) + 0.5, lat / PI + 0.5);
  }

  void main() {
    vec3 n0 = normalize(vObjN);
    vec2 uv = uvOf(n0);

    // Explicit gradients: the atan seam would otherwise pick the smallest mip and draw a line.
    vec2 dx = dFdx(uv), dy = dFdy(uv);
    dx.x -= floor(dx.x + 0.5); dy.x -= floor(dy.x + 0.5);
    vec3 albedo = textureGrad(colorMap, uv, dx, dy).rgb;

    // Normal from LOLA heights: central differences in lon/lat.
    float hE = textureGrad(dispMap, uv + vec2(texel.x, 0.0), dx, dy).r;
    float hW = textureGrad(dispMap, uv - vec2(texel.x, 0.0), dx, dy).r;
    float hN = textureGrad(dispMap, uv + vec2(0.0, texel.y), dx, dy).r;
    float hS = textureGrad(dispMap, uv - vec2(0.0, texel.y), dx, dy).r;
    float cosLat = max(cos((uv.y - 0.5) * PI), 0.02);
    vec3 up = n0;
    vec3 eRaw = cross(vec3(0.0, 1.0, 0.0), up);           // three +Y = lunar north
    vec3 east = dot(eRaw, eRaw) > 1e-10 ? normalize(eRaw) : vec3(1.0, 0.0, 0.0);
    vec3 north = cross(up, east);
    float sE = (hE - hW) * kSlope.x / cosLat;              // dh / (R cos(lat) dlon)
    float sN = (hN - hS) * kSlope.y;                       // dh / (R dlat)
    vec3 n = normalize(up - reliefGain * (sE * east + sN * north));

    vec3 V = normalize(cameraPosition - vWorldPos);
    vec3 Nw = normalize(objToWorldN * n);
    vec3 Sw = normalize(objToWorldN * sunDir);
    vec3 Ew = normalize(objToWorldN * earthDir);

    float mu0 = max(dot(Nw, Sw), 0.0);
    float mu  = max(dot(Nw, V), 1e-3);
    // Lunar-Lambert reflectance (McEwen): Lommel-Seeliger term + Lambert term.
    float sun = 2.0 * L * mu0 / (mu0 + mu) + (1.0 - L) * mu0;

    // Earthshine: Earth as a dim, phase-weighted light from its true direction.
    float mu0e = max(dot(Nw, Ew), 0.0);
    float shine = earthshineGain * earthIllum * (2.0 * mu0e / (mu0e + mu));

    vec3 col = albedo * (sun + shine * vec3(0.75, 0.85, 1.0));
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

/**
 * Loads LOLA heights written by scripts/lola_to_f16.py: raw little-endian float16,
 * width x height, km relative to 1737.4 km, row 0 = SOUTH (GL texture origin), lon -180..180.
 * Why not PNG: browsers hand WebGL 8-bit pixels even from a 16-bit PNG, and 8 bits
 * over LOLA's ~20 km range is ~80 m per step, which bands the shading.
 */
export async function loadLolaHeights(url: string, width: number, height: number): Promise<THREE.DataTexture> {
  const buf = await (await fetch(url)).arrayBuffer();
  const data = new Uint16Array(buf);
  if (data.length !== width * height) throw new Error(`LOLA heights: expected ${width * height} samples, got ${data.length}`);
  const tex = new THREE.DataTexture(data, width, height, THREE.RedFormat, THREE.HalfFloatType);
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.magFilter = THREE.LinearFilter;
  tex.minFilter = THREE.LinearFilter; // no mips: R16F mip generation is not guaranteed in WebGL2
  tex.generateMipmaps = false;
  tex.flipY = false;                  // the script already wrote south first, so v = 0 is -90 deg as uvOf() expects
  tex.needsUpdate = true;
  return tex;
}

export function createLunarMaterial(u: LunarUniforms): THREE.ShaderMaterial {
  const img = u.dispMap.image as { width: number; height: number };
  const R_KM = 1737.4;
  // Central difference spans 2 texels: 2 * (360 deg / width) of longitude, 2 * (180 deg / height) of latitude.
  const kE = 1 / (R_KM * 2 * (2 * Math.PI / img.width));
  const kN = 1 / (R_KM * 2 * (Math.PI / img.height));
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert,
    fragmentShader: frag,
    uniforms: {
      colorMap: { value: u.colorMap },
      dispMap: { value: u.dispMap },
      texel: { value: new THREE.Vector2(1 / img.width, 1 / img.height) },
      kSlope: { value: new THREE.Vector2(kE, kN) },
      reliefGain: { value: 1.0 },
      sunDir: { value: meToThree(u.sunDirMe).normalize() },
      earthDir: { value: meToThree(u.earthDirMe).normalize() },
      earthIllum: { value: u.earthIllumFrac },
      earthshineGain: { value: 0.012 },
      L: { value: 1.0 },
      objToWorldN: { value: new THREE.Matrix3() },
    },
  });
  mat.toneMapped = true;
  return mat;
}

/**
 * Call inside useFrame. Reads cursor-time geometry, never triggers a React render.
 * phase angle g = angle Sun-Moon-camera, measured at the Moon's centre.
 */
export function updateLunarMaterial(
  mat: THREE.ShaderMaterial,
  mesh: THREE.Object3D,
  camera: THREE.Camera,
  sunDirMe: [number, number, number],
  earthDirMe: [number, number, number],
  earthIllumFrac: number,
): void {
  const s = meToThree(sunDirMe).normalize();
  mat.uniforms.sunDir.value.copy(s);
  mat.uniforms.earthDir.value.copy(meToThree(earthDirMe).normalize());
  mat.uniforms.earthIllum.value = earthIllumFrac;
  mat.uniforms.objToWorldN.value.getNormalMatrix(mesh.matrixWorld);

  const centre = new THREE.Vector3().setFromMatrixPosition(mesh.matrixWorld);
  const toCam = camera.getWorldPosition(new THREE.Vector3()).sub(centre).normalize();
  const sWorld = s.clone().applyMatrix3(mat.uniforms.objToWorldN.value).normalize();
  const g = THREE.MathUtils.radToDeg(Math.acos(THREE.MathUtils.clamp(sWorld.dot(toCam), -1, 1)));
  mat.uniforms.L.value = lunarLambertL(g);
}

/**
 * Surface-view exposure: stars fade as the Sun rises, the way a camera would
 * have to stop down. Driven by the Sun's elevation at cursorUtc (series[] el).
 * Returns star opacity 0..1. Disclose as "exposure" in the expert drawer.
 */
export function starOpacityForSunElevation(sunElDeg: number): number {
  const t = THREE.MathUtils.clamp((sunElDeg + 2) / 4, 0, 1); // fully dim by +2 deg
  return 1 - 0.85 * t * t * (3 - 2 * t);
}
