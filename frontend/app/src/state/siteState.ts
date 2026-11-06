// "Right now on the Moon" (PRD F24) for every site, from sky-geometry alone: is the Sun up, how
// high, and when does that change. This is geometry over a smooth sphere (no terrain), so the UI
// labels it "no terrain"; hills move polar sunrise and sunset by hours or days, and the site's own
// run (terrain where it exists) is the number to trust.
import type { SkyGeometry, Vec3 } from '../api/sky';

export type SiteNow = {
  day: boolean;            // Sun's upper limb above a flat horizon
  sunElDeg: number;        // Sun centre elevation over the sphere
  /** Next sunrise (if night) or sunset (if day) inside the loaded sky window; null = not in it. */
  nextChangeMs: number | null;
  /** End of the sky window: "no change before this" when nextChangeMs is null. */
  horizonMs: number;
  /** Earth's centre above a flat horizon (challenge O3c: time to Earthset / Earthrise). */
  earthUp: boolean;
  earthElDeg: number;
  /** Next Earthrise (if hidden) or Earthset (if up) in the window; null = not in it. */
  earthNextMs: number | null;
};

const D2R = Math.PI / 180;

export function siteNormal(latDeg: number, lonDeg: number): Vec3 {
  const la = latDeg * D2R, lo = lonDeg * D2R;
  return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
}

const elev = (n: Vec3, s: number[]) => Math.asin(Math.max(-1, Math.min(1, n[0] * s[0] + n[1] * s[1] + n[2] * s[2]))) / D2R;

/** Upper-limb margin over a flat horizon, in degrees, at sample i. */
function margin(sky: SkyGeometry, n: Vec3, i: number): number {
  return elev(n, sky.series.sun.unit[i]) + sky.series.sun.angular_radius_deg[i];
}

/** Value at tMs between samples i and j, and the next sign change of f after tMs (linear root). */
function track(f: (k: number) => number, timesMs: Float64Array, i: number, tMs: number): { v: number; next: number | null } {
  const N = timesMs.length, j = Math.min(i + 1, N - 1), span = timesMs[j] - timesMs[i];
  const w = span > 0 ? Math.min(1, Math.max(0, (tMs - timesMs[i]) / span)) : 0;
  const v = f(i) + (f(j) - f(i)) * w, up = v > 0;
  let prevT = tMs, prevV = v;
  for (let k = i + 1; k < N; k++) {
    const vk = f(k);
    if ((vk > 0) !== up) return { v, next: prevT + (prevV / (prevV - vk)) * (timesMs[k] - prevT) };
    prevT = timesMs[k]; prevV = vk;
  }
  return { v, next: null };
}

export function siteNow(sky: SkyGeometry, timesMs: Float64Array, latDeg: number, lonDeg: number, tMs: number): SiteNow {
  const n = siteNormal(latDeg, lonDeg), N = timesMs.length;
  let i = 0;
  while (i < N - 1 && timesMs[i + 1] <= tMs) i++;
  const sun = track((k) => margin(sky, n, k), timesMs, i, tMs);
  const earth = track((k) => elev(n, sky.series.earth.unit[k]), timesMs, i, tMs);
  const r = sky.series.sun.angular_radius_deg[i];
  return {
    day: sun.v > 0, sunElDeg: sun.v - r, nextChangeMs: sun.next, horizonMs: timesMs[N - 1],
    earthUp: earth.v > 0, earthElDeg: earth.v, earthNextMs: earth.next,
  };
}

/** "4 d 3 h", "17 h", "38 min" for a span of milliseconds. */
export function spanText(ms: number): string {
  const h = ms / 3600e3;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 24) return `${Math.round(h)} h`;
  const d = Math.floor(h / 24), rh = Math.round(h - d * 24);
  return rh === 24 ? `${d + 1} d` : rh ? `${d} d ${rh} h` : `${d} d`;
}
