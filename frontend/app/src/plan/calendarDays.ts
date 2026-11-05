// Calendar heat map (PRD F18): each UTC day coloured by what the API says about it for the
// selected site. Nothing is estimated here: a day is "land" when a landing window from
// /api/landing-windows overlaps it, "sun" when a sunlight band from /api/check covers part of it,
// "dark" when the bands are known and none covers it, and "unknown" when we have no bands.
import type { LandingOpportunity, UtcRange } from '../api/plan';

export type DayKind = 'land' | 'sun' | 'dark' | 'unknown' | 'outside';
export type CalDay = { ms: number; kind: DayKind; sunFraction: number | null; window: LandingOpportunity | null };

const DAY = 86400e3;

function overlap(a0: number, a1: number, b0: number, b1: number): number {
  return Math.max(0, Math.min(a1, b1) - Math.max(a0, b0));
}

export function classifyDays(
  fromMs: number, toMs: number, opportunities: LandingOpportunity[], sun: UtcRange[] | null,
  coveredFrom: number, coveredTo: number,
): CalDay[] {
  const out: CalDay[] = [];
  const opp = opportunities.map((o) => ({ o, a: Date.parse(o.touchdown_from_utc), b: Date.parse(o.touchdown_until_utc) }));
  const bands = sun?.map((r) => [Date.parse(r.start_utc), Date.parse(r.end_utc)] as const) ?? null;
  for (let d = fromMs; d < toMs; d += DAY) {
    if (d + DAY <= coveredFrom || d >= coveredTo) { out.push({ ms: d, kind: 'outside', sunFraction: null, window: null }); continue; }
    // A window can be a single instant (from == until): count it on the day it falls in.
    const w = opp.find(({ a, b }) => (b > a ? overlap(d, d + DAY, a, b) > 0 : a >= d && a < d + DAY));
    const lit = bands ? bands.reduce((acc, [a, b]) => acc + overlap(d, d + DAY, a, b), 0) / DAY : null;
    out.push({ ms: d, kind: w ? 'land' : lit === null ? 'unknown' : lit > 0 ? 'sun' : 'dark', sunFraction: lit, window: w?.o ?? null });
  }
  return out;
}
