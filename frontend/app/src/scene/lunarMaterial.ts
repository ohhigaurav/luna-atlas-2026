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
  /** Cast-shadow samples toward the Sun (0 = off, default 24). */
  shadowSteps?: number;
  /** Optional polar caps from lola_to_f16.py --caps (both or neither). */
  caps?: { south: THREE.DataTexture; north: THREE.DataTexture; latDeg: number };
};

const vert = /* glsl */ `
  uniform sampler2D dispMap;
  uniform float heightScale;    // scene units per km of LOLA height: exaggeration / 1737.4 (0 = smooth sphere)
  varying vec3 vObjN;     // object-space unit radial direction (three frame)
  varying vec3 vWorldPos;
  const float PI_V = 3.141592653589793;
  void main() {
    vec3 n = normalize(position);
    vec3 me = vec3(n.x, -n.z, n.y);
    vec2 uv = vec2(atan(me.y, me.x) / (2.0 * PI_V) + 0.5, asin(clamp(me.z, -1.0, 1.0)) / PI_V + 0.5);
    float hKm = heightScale > 0.0 ? textureLod(dispMap, uv, 0.0).r : 0.0;
    vec3 displaced = position + n * hKm * heightScale * length(position);
    vObjN = n;
    vec4 wp = modelMatrix * vec4(displaced, 1.0);
    vWorldPos = wp.xyz;
    gl_Position = projectionMatrix * viewMatrix * wp;
  }
`;

const frag = /* glsl */ `
  precision highp float;
  uniform sampler2D colorMap;
  uniform sampler2D dispMap;
  uniform vec2  texel;          // 1/width, 1/height of dispMap
  uniform vec2  kmPerUv;        // km of surface per unit uv: (2 pi R at the equator, pi R)
  uniform float reliefGain;     // 1.0 = true slopes; anything else is exaggeration and must be labelled
  uniform vec3  sunDir;         // object space (three frame), unit
  uniform vec3  earthDir;       // object space (three frame), unit
  uniform float earthIllum;     // 0..1
  uniform float earthshineGain; // display boost; real earthshine is ~1e-4 of sunlight
  uniform float L;              // lunarLambertL(phase angle), set per frame on the CPU
  uniform mat3  objToWorldN;    // normal matrix (object -> world)
  uniform sampler2D capS;       // polar stereographic LOLA heights (km), see scripts/lola_to_f16.py --caps
  uniform sampler2D capN;
  uniform float capOn;          // 1 when caps are loaded
  uniform float capLatDeg;      // caps cover |lat| >= capLatDeg; blended in over the 3 deg before it
  uniform float capRho;         // grid half-width in rho = 2 tan(colat/2), Moon radii
  uniform float capTexel;       // 1 / grid size
  uniform float shadowSteps;    // 0 = off; otherwise samples marched toward the Sun (max 32)
  uniform float sunAngRad;      // apparent solar radius, radians (soft edge of cast shadows)
  varying vec3 vObjN;
  varying vec3 vWorldPos;

  const float PI = 3.141592653589793;
  const float R_KM = 1737.4;

  // LOLA height (km vs 1737.4 km) at a direction, from the polar caps where they exist.
  float heightAt(vec3 d, float lod) {
    vec3 me = vec3(d.x, -d.z, d.y);
    float lat = asin(clamp(me.z, -1.0, 1.0));
    if (capOn > 0.5 && abs(lat) * 180.0 / PI > capLatDeg) {
      bool south = lat < 0.0;
      float colat = acos(clamp(south ? -me.z : me.z, -1.0, 1.0));
      float lam = atan(me.y, me.x);
      vec2 cuv = 2.0 * tan(0.5 * colat) * vec2(cos(lam), sin(lam)) / (2.0 * capRho) + 0.5;
      return south ? textureLod(capS, cuv, lod).r : textureLod(capN, cuv, lod).r;
    }
    return textureLod(dispMap, vec2(atan(me.y, me.x) / (2.0 * PI) + 0.5, lat / PI + 0.5), lod).r;
  }

  // Cast shadows from LOLA relief: march from this point toward the Sun over the real heights and
  // keep the smallest clearance angle. Compared with the Sun's apparent radius it gives the
  // visible fraction of the solar disc (0 = fully shadowed, 1 = full Sun). Flat ground never
  // shadows itself: the ray rises d tan(e) + d^2 / 2R above the sphere.
  // pixKm is the ground size of one screen pixel. Every sample, and the start height, is read at
  // a mip level no finer than one pixel, so the ray is compared with heights smoothed to the same
  // scale on both ends. Comparing a full-resolution start height with mip-averaged neighbours
  // made isolated pixels see walls that are not there (speckle near the terminator, 4 Nov).
  float sunVisibility(vec3 n0, vec3 s, float pixKm) {
    float e = dot(n0, s);                          // sin(Sun elevation) over the smooth sphere
    if (shadowSteps < 0.5 || e > 0.75 || e < -0.05) return 1.0;
    vec3 t = s - n0 * e;
    float c = length(t);                           // cos(elevation)
    if (c < 1e-4) return 1.0;
    t /= c;
    float tanE = e / c;
    float texelKm = PI * R_KM / max(1.0 / texel.y, 1.0);
    float clearance = 1e9;
    float d = 0.6;                                 // km; geometric steps (x1.28) out to ~175 km
    for (int i = 0; i < 32; i++) {
      if (float(i) >= shadowSteps) break;
      vec3 p = normalize(n0 + t * (d / R_KM));
      float lod = clamp(log2(max(d / 6.0, pixKm) / texelKm), 0.0, 9.0);
      float ray = heightAt(n0, lod) + d * tanE + d * d / (2.0 * R_KM);
      clearance = min(clearance, (ray - heightAt(p, lod)) / d);
      d *= 1.28;
    }
    return smoothstep(-sunAngRad, sunAngRad, clearance);
  }

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
    // Within ~2.5 deg of a pole an equirectangular map is one stretched row per latitude, which
    // shows as radial streaks. Fade the colour to the cap's mean albedo there; relief shading
    // (from LOLA heights, dense at the poles) carries the detail.
    float polar = smoothstep(87.5, 89.0, abs(uv.y - 0.5) * 180.0);
    albedo = mix(albedo, textureLod(colorMap, vec2(0.5, uv.y < 0.5 ? 0.0 : 1.0), 20.0).rgb, polar);

    // Normal from LOLA heights: central differences across this pixel's footprint (never finer
    // than one texel), sampled from the matching mip level, so slopes are right at any zoom.
    vec2 stepUv = clamp(vec2(max(abs(dx.x), abs(dy.x)), max(abs(dx.y), abs(dy.y))), texel, vec2(0.05)); // cap: polar pixels span huge longitudes
    float hE = textureGrad(dispMap, uv + vec2(stepUv.x, 0.0), dx, dy).r;
    float hW = textureGrad(dispMap, uv - vec2(stepUv.x, 0.0), dx, dy).r;
    float hN = textureGrad(dispMap, uv + vec2(0.0, stepUv.y), dx, dy).r;
    float hS = textureGrad(dispMap, uv - vec2(0.0, stepUv.y), dx, dy).r;
    float cosLat = max(cos((uv.y - 0.5) * PI), 0.02);
    vec3 up = n0;
    vec3 eRaw = cross(vec3(0.0, 1.0, 0.0), up);           // three +Y = lunar north
    vec3 east = dot(eRaw, eRaw) > 1e-10 ? normalize(eRaw) : vec3(1.0, 0.0, 0.0);
    vec3 north = cross(up, east);
    float sE = (hE - hW) / (2.0 * stepUv.x * kmPerUv.x * cosLat);   // dh / (R cos(lat) dlon)
    float sN = (hN - hS) / (2.0 * stepUv.y * kmPerUv.y);            // dh / (R dlat)
    vec3 n = normalize(up - reliefGain * (sE * east + sN * north));

    // Near the poles, take the slope from the polar stereographic caps instead: the same heights
    // on a grid with no longitude stretching, so the shading has no radial wedges.
    float latDeg = (uv.y - 0.5) * 180.0;
    if (capOn > 0.5 && abs(latDeg) > capLatDeg - 3.0) {
      bool south = latDeg < 0.0;
      vec3 me = vec3(n0.x, -n0.z, n0.y);
      float colat = acos(clamp(south ? -me.z : me.z, -1.0, 1.0));
      float rho = 2.0 * tan(0.5 * colat);
      float lam = atan(me.y, me.x);
      vec2 cuv = rho * vec2(cos(lam), sin(lam)) / (2.0 * capRho) + 0.5;
      vec2 cdx = dFdx(cuv), cdy = dFdy(cuv);
      float st = clamp(max(max(abs(cdx.x), abs(cdx.y)), max(abs(cdy.x), abs(cdy.y))), capTexel, 0.05);
      float hxp, hxm, hyp, hym;
      if (south) {
        hxp = textureGrad(capS, cuv + vec2(st, 0.0), cdx, cdy).r; hxm = textureGrad(capS, cuv - vec2(st, 0.0), cdx, cdy).r;
        hyp = textureGrad(capS, cuv + vec2(0.0, st), cdx, cdy).r; hym = textureGrad(capS, cuv - vec2(0.0, st), cdx, cdy).r;
      } else {
        hxp = textureGrad(capN, cuv + vec2(st, 0.0), cdx, cdy).r; hxm = textureGrad(capN, cuv - vec2(st, 0.0), cdx, cdy).r;
        hyp = textureGrad(capN, cuv + vec2(0.0, st), cdx, cdy).r; hym = textureGrad(capN, cuv - vec2(0.0, st), cdx, cdy).r;
      }
      // One cap-uv step is st * 2 capRho in rho; stereographic scale: ds = R drho cos^2(colat/2).
      float c2 = cos(0.5 * colat);
      float dsKm = st * 2.0 * capRho * kmPerUv.y / PI * c2 * c2;
      vec3 tX = normalize(vec3(1.0, 0.0, 0.0) - n0 * n0.x);   // MOON_ME +X (0 deg E) in three
      vec3 tY = normalize(vec3(0.0, 0.0, -1.0) + n0 * n0.z);  // MOON_ME +Y (90 deg E) in three
      vec3 nc = normalize(n0 - reliefGain * ((hxp - hxm) / (2.0 * dsKm) * tX + (hyp - hym) / (2.0 * dsKm) * tY));
      n = normalize(mix(n, nc, smoothstep(capLatDeg - 3.0, capLatDeg, abs(latDeg))));
    }

    vec3 V = normalize(cameraPosition - vWorldPos);
    vec3 Nw = normalize(objToWorldN * n);
    vec3 Sw = normalize(objToWorldN * sunDir);
    vec3 Ew = normalize(objToWorldN * earthDir);

    float mu0 = max(dot(Nw, Sw), 0.0);
    float mu  = max(dot(Nw, V), 1e-3);
    // Lunar-Lambert reflectance (McEwen): Lommel-Seeliger term + Lambert term.
    float sun = 2.0 * L * mu0 / (mu0 + mu) + (1.0 - L) * mu0;
    if (mu0 > 0.0) sun *= sunVisibility(n0, normalize(sunDir), R_KM * length(fwidth(vObjN)));

    // Earthshine: Earth as a dim, phase-weighted light from its true direction.
    float mu0e = max(dot(Nw, Ew), 0.0);
    float shine = earthshineGain * earthIllum * (2.0 * mu0e / (mu0e + mu));

    vec3 col = albedo * (sun + shine * vec3(0.75, 0.85, 1.0));
    gl_FragColor = vec4(col, 1.0);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
  }
`;

/** Sizes of a full mip chain for a w x h map (each level floor-halved, down to 1 x 1). */
export function mipChain(width: number, height: number): [number, number][] {
  const out: [number, number][] = [[width, height]];
  let w = width, h = height;
  while (w > 1 || h > 1) { w = Math.max(1, w >> 1); h = Math.max(1, h >> 1); out.push([w, h]); }
  return out;
}

/**
 * Loads LOLA heights written by scripts/lola_to_f16.py: raw little-endian float16, km relative to
 * 1737.4 km, row 0 = SOUTH (GL texture origin), lon -180..180. Either one level (width x height)
 * or, with --mips, the full mip chain back to back, which lets distant views sample a filtered
 * level instead of shimmering. Why not PNG: browsers hand WebGL 8-bit pixels even from a 16-bit
 * PNG, and 8 bits over LOLA's ~20 km range is ~80 m per step, which bands the shading.
 */
export async function loadLolaHeights(url: string, width: number, height: number): Promise<THREE.DataTexture> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`LOLA heights: HTTP ${res.status} for ${url}`);
  const all = new Uint16Array(await res.arrayBuffer());
  const chain = mipChain(width, height);
  const chainLen = chain.reduce((n, [w, h]) => n + w * h, 0);
  let tex: THREE.DataTexture;
  if (all.length === width * height) {
    tex = new THREE.DataTexture(all, width, height, THREE.RedFormat, THREE.HalfFloatType);
    tex.minFilter = THREE.LinearFilter; // single level: no mips available
  } else if (all.length === chainLen) {
    let off = 0;
    const levels = chain.map(([w, h]) => { const data = all.subarray(off, off + w * h); off += w * h; return { data, width: w, height: h }; });
    tex = new THREE.DataTexture(levels[0].data, width, height, THREE.RedFormat, THREE.HalfFloatType);
    tex.mipmaps = levels as unknown as THREE.DataTexture['mipmaps'];
    tex.minFilter = THREE.LinearMipmapLinearFilter;
  } else {
    throw new Error(`LOLA heights: ${all.length} samples fit neither ${width}x${height} nor its mip chain (${chainLen})`);
  }
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  tex.flipY = false;                  // the script already wrote south first, so v = 0 is -90 deg as uvOf() expects
  tex.needsUpdate = true;
  return tex;
}

export function createLunarMaterial(u: LunarUniforms): THREE.ShaderMaterial {
  const img = u.dispMap.image as { width: number; height: number };
  const R_KM = 1737.4;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert,
    fragmentShader: frag,
    uniforms: {
      colorMap: { value: u.colorMap },
      dispMap: { value: u.dispMap },
      texel: { value: new THREE.Vector2(1 / img.width, 1 / img.height) },
      kmPerUv: { value: new THREE.Vector2(2 * Math.PI * R_KM, Math.PI * R_KM) },
      reliefGain: { value: 1.0 },
      heightScale: { value: 1 / 1737.4 },  // true relief; the UI must label any exaggeration
      sunDir: { value: meToThree(u.sunDirMe).normalize() },
      earthDir: { value: meToThree(u.earthDirMe).normalize() },
      earthIllum: { value: u.earthIllumFrac },
      earthshineGain: { value: 0.012 },
      L: { value: 1.0 },
      objToWorldN: { value: new THREE.Matrix3() },
      capS: { value: u.caps?.south ?? u.dispMap },
      capN: { value: u.caps?.north ?? u.dispMap },
      capOn: { value: u.caps ? 1 : 0 },
      capLatDeg: { value: u.caps?.latDeg ?? 75 },
      capRho: { value: 2 * Math.tan(THREE.MathUtils.degToRad(90 - (u.caps?.latDeg ?? 75)) / 2) },
      capTexel: { value: u.caps ? 1 / (u.caps.south.image as { width: number }).width : 1 },
      shadowSteps: { value: u.shadowSteps ?? 24 },
      sunAngRad: { value: THREE.MathUtils.degToRad(0.2666) }, // mean solar radius seen from the Moon
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
