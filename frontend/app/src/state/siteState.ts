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
};

const D2R = Math.PI / 180;

export function siteNormal(latDeg: number, lonDeg: number): Vec3 {
  const la = latDeg * D2R, lo = lonDeg * D2R;
  return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)];
}

/** Upper-limb margin over a flat horizon, in degrees, at sample i. */
function margin(sky: SkyGeometry, n: Vec3, i: number): number {
  const s = sky.series.sun.unit[i];
  const el = Math.asin(Math.max(-1, Math.min(1, n[0] * s[0] + n[1] * s[1] + n[2] * s[2]))) / D2R;
  return el + sky.series.sun.angular_radius_deg[i];
}

export function siteNow(sky: SkyGeometry, timesMs: Float64Array, latDeg: number, lonDeg: number, tMs: number): SiteNow {
  const n = siteNormal(latDeg, lonDeg), N = timesMs.length;
  let i = 0;
  while (i < N - 1 && timesMs[i + 1] <= tMs) i++;
  // Interpolate the margin at tMs between samples i and i+1.
  const j = Math.min(i + 1, N - 1);
  const span = timesMs[j] - timesMs[i];
  const f = span > 0 ? Math.min(1, Math.max(0, (tMs - timesMs[i]) / span)) : 0;
  const m0 = margin(sky, n, i), m1 = margin(sky, n, j);
  const m = m0 + (m1 - m0) * f;
  const r = sky.series.sun.angular_radius_deg[i];
  const day = m > 0;
  let next: number | null = null;
  let prevT = tMs, prevM = m;
  for (let k = i + 1; k < N; k++) {
    const mk = margin(sky, n, k);
    if ((mk > 0) !== day) {
      const a = prevM / (prevM - mk); // linear root between the two samples
      next = prevT + a * (timesMs[k] - prevT);
      break;
    }
    prevT = timesMs[k]; prevM = mk;
  }
  return { day, sunElDeg: m - r, nextChangeMs: next, horizonMs: timesMs[N - 1] };
}

/** "4 d 3 h", "17 h", "38 min" for a span of milliseconds. */
export function spanText(ms: number): string {
  const h = ms / 3600e3;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 24) return `${Math.round(h)} h`;
  const d = Math.floor(h / 24), rh = Math.round(h - d * 24);
  return rh === 24 ? `${d + 1} d` : rh ? `${d} d ${rh} h` : `${d} d`;
}
