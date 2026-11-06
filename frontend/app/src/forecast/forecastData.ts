// Moon weather forecast (PRD F29): the south pole's sunlight every 2 h and Earth's line of sight
// every 6 h for one month, baked by tools/bake_shadow_movie.py and tools/bake_earth_movie.py into
// public/data/shadow_movie/. Lit and Earth masks are 1 bit per 250 m pixel (np.packbits, MSB
// first, row-major, row 0 at +y = toward 0 deg E) on a south polar stereographic grid:
//   rho = 2 R tan(pi/4 + lat/2), x = rho sin(lon), y = rho cos(lon)   (tools/shadow_match.py)
// Nothing here models anything: it indexes the baked masks by time and position.

const R_M = 1737400;

export type ForecastData = {
  n: number;                 // grid is n x n
  pixelM: number;
  halfM: number;
  sunMs: number[];           // time of each Sun (lit) frame
  earthMs: number[];         // time of each Earth frame
  earthSunIdx: number[];     // Sun frame that each Earth frame belongs to
  litBits: Uint8Array;
  earthBits: Uint8Array;
  litHours: Uint16Array;     // per pixel: Sun frames lit (each 2 h)
  earthHours: Uint16Array;   // per pixel: Earth frames in view (each 6 h)
  method: string;
  limits: string;
  earthLimits: string;
  earthNeverShare: number;
};

type MovieJson = { frames: string[]; grid: { size: number; pixel_m: number; half_width_m: number }; method: string; limits: string };
type EarthJson = { frames: string[]; sun_frame_index: number[]; grid: { size: number }; limits: string; month_share?: { never?: number } };

function bitCounts(bits: Uint8Array, frames: number, nn: number): Uint16Array {
  const out = new Uint16Array(nn), bytes = nn >> 3;
  for (let f = 0; f < frames; f++) {
    const o = f * bytes;
    for (let b = 0; b < bytes; b++) {
      const v = bits[o + b];
      if (!v) continue;
      const i = b << 3;
      for (let k = 0; k < 8; k++) if (v & (0x80 >> k)) out[i + k]++;
    }
  }
  return out;
}

export async function loadForecast(base: string): Promise<ForecastData> {
  const get = async (f: string) => {
    const r = await fetch(base + f);
    if (!r.ok) throw new Error(`${f}: HTTP ${r.status}`);
    return r;
  };
  const [movie, earth, lit, eb] = await Promise.all([
    get('movie.json').then((r) => r.json() as Promise<MovieJson>),
    get('earth.json').then((r) => r.json() as Promise<EarthJson>),
    get('lit.u8').then((r) => r.arrayBuffer()),
    get('earth.u8').then((r) => r.arrayBuffer()),
  ]);
  const n = movie.grid.size, nn = n * n;
  if (earth.grid.size !== n) throw new Error('forecast: Sun and Earth grids differ');
  const litBits = new Uint8Array(lit), earthBits = new Uint8Array(eb);
  if (litBits.length !== movie.frames.length * nn / 8) throw new Error('forecast: lit.u8 size does not match movie.json');
  if (earthBits.length !== earth.frames.length * nn / 8) throw new Error('forecast: earth.u8 size does not match earth.json');
  return {
    n, pixelM: movie.grid.pixel_m, halfM: movie.grid.half_width_m,
    sunMs: movie.frames.map(Date.parse), earthMs: earth.frames.map(Date.parse), earthSunIdx: earth.sun_frame_index,
    litBits, earthBits,
    litHours: bitCounts(litBits, movie.frames.length, nn),
    earthHours: bitCounts(earthBits, earth.frames.length, nn),
    method: movie.method, limits: movie.limits, earthLimits: earth.limits,
    earthNeverShare: earth.month_share?.never ?? NaN,
  };
}

/** Grid row and column of a surface point, or null outside the forecast square. */
export function pixelOf(f: Pick<ForecastData, 'n' | 'halfM'>, latDeg: number, lonDeg: number): { r: number; c: number; x: number; y: number } | null {
  const lat = (latDeg * Math.PI) / 180, lon = (lonDeg * Math.PI) / 180;
  const rho = 2 * R_M * Math.tan(Math.PI / 4 + lat / 2);
  const x = rho * Math.sin(lon), y = rho * Math.cos(lon);
  if (Math.abs(x) >= f.halfM || Math.abs(y) >= f.halfM || latDeg > 0) return null;
  const px = (2 * f.halfM) / f.n;
  return { r: Math.floor((f.halfM - y) / px), c: Math.floor((x + f.halfM) / px), x, y };
}

/** The two Sun frames around a time and how far between them, or null outside the month. */
export function sunFrameAt(f: Pick<ForecastData, 'sunMs'>, ms: number): { k: number; k1: number; mix: number } | null {
  const t = f.sunMs, last = t.length - 1;
  if (!t.length || ms < t[0] || ms > t[last]) return null;
  let lo = 0, hi = last;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (t[m] <= ms) lo = m; else hi = m; }
  if (ms >= t[last]) return { k: last, k1: last, mix: 0 };
  return { k: lo, k1: hi, mix: (ms - t[lo]) / (t[hi] - t[lo]) };
}

/** Earth frames are held until the next one (earth.json: "between frames, hold the previous frame"). */
export function earthFrameAt(f: Pick<ForecastData, 'earthMs'>, ms: number): number | null {
  const t = f.earthMs;
  if (!t.length || ms < t[0]) return null;
  let j = 0;
  while (j + 1 < t.length && t[j + 1] <= ms) j++;
  return j;
}

export function bitAt(bits: Uint8Array, frame: number, n: number, r: number, c: number): boolean {
  const i = frame * n * n + r * n + c;
  return (bits[i >> 3] & (0x80 >> (i & 7))) !== 0;
}

/** One frame as bytes (0 or 255), row-major from row 0 = +y, for a texture. */
export function unpackFrame(bits: Uint8Array, frame: number, n: number, out?: Uint8Array): Uint8Array {
  const nn = n * n, o = (frame * nn) >> 3, res = out ?? new Uint8Array(nn);
  for (let b = 0; b < nn >> 3; b++) {
    const v = bits[o + b], i = b << 3;
    for (let k = 0; k < 8; k++) res[i + k] = v & (0x80 >> k) ? 255 : 0;
  }
  return res;
}

/** Lit and Earth-in-view series of one pixel over the month (for the date ribbon). */
export function pixelSeries(f: ForecastData, r: number, c: number): { sun: boolean[]; earth: boolean[] } {
  return {
    sun: f.sunMs.map((_, k) => bitAt(f.litBits, k, f.n, r, c)),
    earth: f.earthMs.map((_, j) => bitAt(f.earthBits, j, f.n, r, c)),
  };
}
