// Geometry for the sky chart (SkyChart.tsx): the saved run's terrain skyline with the Sun's and
// Earth's tracks over the whole period. Pure functions, so tests/skyTracks.test.ts can check them.
import type { HorizonBin, RunRow } from '../api/plan';

export type Body = 'sun' | 'earth';
export type Pt = { az: number; el: number; up: boolean; t: number };
export type Segment = { up: boolean; pts: { x: number; y: number }[] };

const az = (r: RunRow, b: Body) => (b === 'sun' ? r.sun_azimuth_deg : r.earth_azimuth_deg);
const el = (r: RunRow, b: Body) => (b === 'sun' ? r.sun_elevation_deg : r.earth_elevation_deg);
/** Visible as the backend decides it: the Sun's upper limb, Earth's centre, above the terrain horizon. */
const up = (r: RunRow, b: Body) => (b === 'sun' ? r.sun_visible_upper_limb : r.earth_center_clear);

export function track(series: RunRow[], b: Body): Pt[] {
  return series.map((r) => ({ az: az(r, b), el: el(r, b), up: up(r, b), t: Date.parse(r.utc) }));
}

/**
 * Polyline pieces in chart space. A piece ends where the body's visibility changes, where it wraps
 * across the chart's azimuth edge (a jump of more than 180°), or where it leaves [lo, hi] in elevation.
 */
export function segments(pts: Pt[], x: (az: number) => number, y: (el: number) => number, lo: number, hi: number, wrap = true): Segment[] {
  const out: Segment[] = [];
  let cur: Segment | null = null;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], prev = pts[i - 1];
    const inside = p.el >= lo && p.el <= hi;
    const brk = !cur || !inside || cur.up !== p.up || (wrap && prev && Math.abs(p.az - prev.az) > 180);
    if (!inside) { cur = null; continue; }
    if (brk) {
      // A visibility change keeps the line continuous: the new piece starts at the previous point.
      const seed: { x: number; y: number }[] = cur && prev && cur.up !== p.up && !(wrap && Math.abs(p.az - prev.az) > 180) ? [cur.pts[cur.pts.length - 1]] : [];
      cur = { up: p.up, pts: seed };
      out.push(cur);
    }
    cur!.pts.push({ x: x(p.az), y: y(p.el) });
  }
  return out.filter((s) => s.pts.length > 1);
}

/** Indices of the points at whole days from the first one (the steps need not divide a day exactly). */
export function dayTicks(pts: Pt[]): { i: number; day: number }[] {
  if (!pts.length) return [];
  const t0 = pts[0].t, out: { i: number; day: number }[] = [];
  let next = 0;
  for (let i = 0; i < pts.length; i++) {
    const d = (pts[i].t - t0) / 86400e3;
    if (d >= next - 1e-6) { out.push({ i, day: Math.round(d) }); next = Math.floor(d + 1e-6) + 1; }
  }
  return out;
}

/** Elevation range to draw: the whole skyline and both tracks while they are near or above it. */
export function elevRange(hz: HorizonBin[], tracks: Pt[][]): { lo: number; hi: number } {
  const h = hz.flatMap((b) => (b.elevation_deg == null ? [] : [b.elevation_deg]));
  const hMin = h.length ? Math.min(...h) : 0, hMax = h.length ? Math.max(...h) : 0;
  const lo = Math.max(-15, Math.floor(Math.min(-2, hMin - 1)));
  const near = tracks.flat().filter((p) => p.el > lo).map((p) => p.el);
  const hi = Math.min(90, Math.ceil(Math.max(hMax + 1, lo + 6, ...near) + 0.5));
  return { lo, hi };
}

/** How many times taller than true the chart draws heights (degrees per pixel across / down). */
export function exaggeration(pxPerDegX: number, pxPerDegY: number): number {
  return pxPerDegY / pxPerDegX;
}

/** Mean direction of a set of azimuths (handles the 0/360 wrap). */
export function circularMean(azs: number[]): number {
  let sx = 0, sy = 0;
  for (const a of azs) { sx += Math.cos((a * Math.PI) / 180); sy += Math.sin((a * Math.PI) / 180); }
  return ((Math.atan2(sy, sx) * 180) / Math.PI + 360) % 360;
}

/** a expressed within ±180° of centre, so a track around north does not split. */
export function around(a: number, centre: number): number {
  return centre + ((((a - centre) % 360) + 540) % 360) - 180;
}

export function extent(pts: Pt[], f: (p: Pt) => number): [number, number] {
  let a = Infinity, b = -Infinity;
  for (const p of pts) { const v = f(p); if (v < a) a = v; if (v > b) b = v; }
  return [a, b];
}

/** Earth's angular radius seen from the Moon, from its distance (mean radius 6371 km). */
export function earthRadiusDeg(rangeM: number): number {
  return (Math.asin(6_371_000 / rangeM) * 180) / Math.PI;
}
