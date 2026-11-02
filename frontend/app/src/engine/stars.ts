// Background star field. ILLUSTRATIVE: random positions with a realistic brightness and colour
// distribution, not a catalogue (real bright-star positions are F14). Say so in the expert drawer.
import * as THREE from 'three';

export function createStars(count = 7000, radius = 2500, seed = 20261101): THREE.Points {
  let s = seed >>> 0;
  const rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
  const pos = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  const size = new Float32Array(count);
  // Colour by temperature class, weighted toward white/yellow like the naked-eye sky.
  const palette: [number, number, number, number][] = [
    [0.62, 0.72, 1.0, 0.08], [0.80, 0.86, 1.0, 0.22], [1.0, 1.0, 1.0, 0.30],
    [1.0, 0.94, 0.82, 0.24], [1.0, 0.82, 0.62, 0.12], [1.0, 0.70, 0.52, 0.04],
  ];
  for (let i = 0; i < count; i++) {
    const u = rnd() * 2 - 1, phi = rnd() * Math.PI * 2, r = Math.sqrt(1 - u * u);
    pos.set([radius * r * Math.cos(phi), radius * u, radius * r * Math.sin(phi)], i * 3);
    // Magnitude-like: many faint, few bright (N(<m) grows ~ x3 per magnitude).
    const m = 6.5 - Math.log(1 + rnd() * 700) / Math.log(3);
    size[i] = Math.max(0.6, 3.4 - 0.42 * m);
    let pick = rnd(), c = palette[2];
    for (const p of palette) { if ((pick -= p[3]) <= 0) { c = p; break; } }
    const b = Math.min(1, Math.max(0.18, 1.15 - 0.13 * m));
    col.set([c[0] * b, c[1] * b, c[2] * b], i * 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  g.setAttribute('size', new THREE.BufferAttribute(size, 1));
  const mat = new THREE.ShaderMaterial({
    uniforms: { opacity: { value: 1 }, pixelRatio: { value: 1 } },
    vertexShader: /* glsl */ `
      attribute float size; attribute vec3 color; varying vec3 vC; uniform float pixelRatio;
      void main() { vC = color; vec4 mv = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = size * pixelRatio; gl_Position = projectionMatrix * mv; }`,
    fragmentShader: /* glsl */ `
      varying vec3 vC; uniform float opacity;
      void main() { vec2 d = gl_PointCoord - 0.5; float r = length(d);
        float a = smoothstep(0.5, 0.0, r); a *= a; gl_FragColor = vec4(vC * a * opacity, 1.0); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
  });
  const pts = new THREE.Points(g, mat);
  pts.frustumCulled = false;
  pts.renderOrder = -10;
  return pts;
}
