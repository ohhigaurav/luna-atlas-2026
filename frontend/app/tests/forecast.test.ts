// Cross-checked against numpy (np.unpackbits, tools/shadow_match.to_stereo) on the shipped files.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { bitAt, earthFrameAt, pixelOf, sunFrameAt, unpackFrame } from '../src/forecast/forecastData';

const d = new URL('../public/data/shadow_movie/', import.meta.url);
const m = JSON.parse(readFileSync(new URL('movie.json', d), 'utf8'));
const e = JSON.parse(readFileSync(new URL('earth.json', d), 'utf8'));
const n = m.grid.size;
const lit = new Uint8Array(readFileSync(new URL('lit.u8', d)));
const ea = new Uint8Array(readFileSync(new URL('earth.u8', d)));
// numpy reference, 6 Nov: [lat, lon, row, col, lit frames, Earth frames, lit at frame 100, Earth at frame 50]
const REF = [[-89.45, 222.69, 209, 114, 241, 54, 1, 1], [-89.9, 0, 147, 160, 154, 51, 0, 1], [-89.3, 45, 99, 220, 100, 41, 0, 1], [-89.68, -153, 194, 142, 105, 52, 0, 1]];

describe('forecast masks', () => {
  it('index the same pixels and bits as numpy', () => {
    for (const [la, lo, r, c, lh, eh, l100, e50] of REF) {
      const p = pixelOf({ n, halfM: m.grid.half_width_m }, la, lo)!;
      expect([p.r, p.c]).toEqual([r, c]);
      let a = 0, b = 0;
      for (let k = 0; k < m.frames.length; k++) a += +bitAt(lit, k, n, r, c);
      for (let j = 0; j < e.frames.length; j++) b += +bitAt(ea, j, n, r, c);
      expect([a, b]).toEqual([lh, eh]);
      expect(unpackFrame(lit, 100, n)[r * n + c] ? 1 : 0).toBe(l100);
      expect(+bitAt(ea, 50, n, r, c)).toBe(e50);
    }
  });
  it('is outside the square away from the pole', () => {
    expect(pixelOf({ n, halfM: m.grid.half_width_m }, -85, 0)).toBeNull();
  });
  it('blends Sun frames and holds Earth frames', () => {
    const f = { sunMs: m.frames.map(Date.parse), earthMs: e.frames.map(Date.parse) };
    expect(sunFrameAt(f, Date.parse('2027-01-01T03:00:00Z'))).toEqual({ k: 1, k1: 2, mix: 0.5 });
    expect(earthFrameAt(f, Date.parse('2027-01-01T11:59:00Z'))).toBe(1);
    expect(sunFrameAt(f, Date.parse('2026-12-31T00:00:00Z'))).toBeNull();
  });
});
