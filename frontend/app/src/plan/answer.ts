// The Answer card's content, from /api/landing-windows output and the launch knob. Pure and
// unit-tested: it only selects and clips API windows and subtracts API timestamps; it never
// decides whether a time is landable (the API did that for every 30 min touchdown candidate).
import type { LandingOpportunity, LandingResult } from '../api/plan';

const H = 3600e3, D = 86400e3;

export type WindowAnswer = {
  kind: 'window';
  fromMs: number;        // first allowed touchdown at or after the knob
  untilMs: number;
  bestMs: number;        // API best touchdown, moved to the knob if the knob is past it
  daylightH: number;     // daylight left after bestMs
  daylightIsLowerBound: boolean;
  earthPct: number;      // API value for its own best touchdown
  inDays: number;        // from "now" (the clock) to bestMs
  opportunity: LandingOpportunity;
};
export type MissAnswer = {
  kind: 'miss';
  touchdownMs: number;
  daylightH: number;
  neededH: number;
  failed: string[];
};
export type Answer = WindowAnswer | MissAnswer | { kind: 'none' };

/** The first landing window that is still open at or after notBeforeMs. */
export function nextLanding(result: LandingResult, notBeforeMs: number, nowMs: number): Answer {
  const opps = [...result.opportunities].sort((a, b) => Date.parse(a.touchdown_from_utc) - Date.parse(b.touchdown_from_utc));
  for (const o of opps) {
    const until = Date.parse(o.touchdown_until_utc);
    if (until < notBeforeMs) continue;
    const from = Math.max(Date.parse(o.touchdown_from_utc), notBeforeMs);
    const apiBest = Date.parse(o.best_touchdown_utc);
    const best = Math.max(apiBest, from);
    let daylightH = o.daylight_after_best_h, lower = o.daylight_is_lower_bound;
    if (best > apiBest) {
      // Landing later than the API's best leaves less daylight before the same sunset.
      if (o.sunset_utc) daylightH = (Date.parse(o.sunset_utc) - best) / H;
      else { daylightH = o.daylight_after_best_h - (best - apiBest) / H; lower = true; }
    }
    return { kind: 'window', fromMs: from, untilMs: until, bestMs: best, daylightH, daylightIsLowerBound: lower,
      earthPct: o.earth_in_view_during_mission_pct, inDays: (best - nowMs) / D, opportunity: o };
  }
  const m = result.closest_miss;
  if (m) return { kind: 'miss', touchdownMs: Date.parse(m.touchdown_utc), daylightH: m.daylight_after_h, neededH: m.daylight_needed_h, failed: m.failed_rules };
  return { kind: 'none' };
}

/** PRD durations: under 1 h "45 min"; under 48 h "6 h 20 min"; above "3 d 4 h". */
export function formatDuration(hours: number, lowerBound = false): string {
  const pre = lowerBound ? '≥ ' : '';
  if (hours < 1) return `${pre}${Math.round(hours * 60)} min`;
  if (hours < 48) {
    const h = Math.floor(hours), m = Math.round((hours - h) * 60);
    return m === 60 ? `${pre}${h + 1} h` : m ? `${pre}${h} h ${m} min` : `${pre}${h} h`;
  }
  const d = Math.floor(hours / 24), h = Math.round(hours - d * 24);
  return h === 24 ? `${pre}${d + 1} d` : h ? `${pre}${d} d ${h} h` : `${pre}${d} d`;
}

/** "in 70 d", "in 9 h", "now", "3 d ago" for the countdown chip. */
export function formatIn(days: number): string {
  if (Math.abs(days) < 1 / 24) return 'now';
  const txt = Math.abs(days) >= 2 ? `${Math.round(Math.abs(days))} d` : `${Math.round(Math.abs(days) * 24)} h`;
  return days > 0 ? `in ${txt}` : `${txt} ago`;
}

/** One-tap fixes when nothing qualifies (PRD Phase 2 rule 2: never a bare "no"). */
export function fixes(miss: MissAnswer, missionDays: number, maxSunDeg: number | null): { label: string; missionDays?: number; maxSunDeg?: number | null }[] {
  const out: { label: string; missionDays?: number; maxSunDeg?: number | null }[] = [];
  const fit = Math.floor(miss.daylightH / 24);
  if (fit >= 1 && fit < missionDays) out.push({ label: `${missionDays} d → ${fit} d mission`, missionDays: fit });
  if (miss.failed.includes('low_sun') && (maxSunDeg ?? 90) < 30) out.push({ label: 'Allow Sun up to 30°', maxSunDeg: 30 });
  return out;
}

/** Next Earthset (if Earth is up at t) or Earthrise (if not) from Earth-in-view bands. */
export function earthAfter(bands: { start_utc: string; end_utc: string }[], t: number): { event: 'Earthset' | 'Earthrise'; ms: number } | null {
  for (const b of bands) {
    const a = Date.parse(b.start_utc), e = Date.parse(b.end_utc);
    if (a <= t && t < e) return { event: 'Earthset', ms: e };
    if (a > t) return { event: 'Earthrise', ms: a };
  }
  return null;
}
