// The next landing window at or after one moment, from /api/landing-windows answers (the same
// question as the site card and the green pins: 10-day mission, Sun at most 20 deg up at
// touchdown). Pure: it only compares API timestamps with the moment.
import type { LandingResult } from '../api/plan';
import { utcMidnight } from '../plan/usePlan';

const DAY = 86400e3;

export type NextLanding =
  | { kind: 'pending' }
  | { kind: 'error' }
  /** fromMs is clipped to the moment when the window is already open (openAt). */
  | { kind: 'window'; fromMs: number; bestMs: number; untilMs: number; openAt: boolean; sunDeg?: number }
  /** No window from the moment to throughMs (the end of the searched days). */
  | { kind: 'none'; throughMs: number; longest?: Stretch; earlier?: Earlier; miss?: Miss };

/** The touchdown time after the moment that came closest, and the rules it breaks (landing.py RULE_TEXT keys). */
export type Miss = { atMs: number; rules: string[]; daylightH: number; neededH: number };

/** The longest sunlit stretch the search saw after the moment: what a shorter mission could use. */
export type Stretch = { fromMs: number; hours: number; lowerBound: boolean };
/** The last window before the moment (from today's search), when one exists. */
export type Earlier = { fromMs: number; bestMs: number };

export function nextLandingAt(results: LandingResult[], atMs: number): NextLanding {
  let best: NextLanding | null = null;
  let through = atMs;
  for (const r of results) {
    through = Math.max(through, Date.parse(r.search.start_utc) + r.search.days * DAY);
    for (const o of r.opportunities) {
      const from = Date.parse(o.touchdown_from_utc), until = Date.parse(o.touchdown_until_utc);
      if (until < atMs) continue;
      const start = Math.max(from, atMs);
      if (best === null || (best.kind === 'window' && start < best.fromMs)) {
        best = { kind: 'window', fromMs: start, bestMs: Math.max(Date.parse(o.best_touchdown_utc), start), untilMs: until,
          openAt: from <= atMs, sunDeg: o.sun_above_horizon_at_best_deg };
      }
    }
  }
  if (best) return best;
  const none: NextLanding & { kind: 'none' } = { kind: 'none', throughMs: through };
  for (const r of results) {
    const w = r.longest_sunlit_window;
    if (w && Date.parse(w.end_utc) > atMs && (!none.longest || w.hours > none.longest.hours)) {
      none.longest = { fromMs: Date.parse(w.start_utc), hours: w.hours, lowerBound: w.is_lower_bound };
    }
    const m = r.closest_miss;
    if (m && Date.parse(m.touchdown_utc) >= atMs && (!none.miss || m.failed_rules.length < none.miss.rules.length)) {
      none.miss = { atMs: Date.parse(m.touchdown_utc), rules: m.failed_rules, daylightH: m.daylight_after_h, neededH: m.daylight_needed_h };
    }
    for (const o of r.opportunities) {
      const from = Date.parse(o.touchdown_from_utc);
      if (from < atMs && (!none.earlier || from > none.earlier.fromMs)) none.earlier = { fromMs: from, bestMs: Date.parse(o.best_touchdown_utc) };
    }
  }
  return none;
}

/** Where to start the search for a moment: today's search (warm, usually cached) when it covers the moment. */
export function searchStartFor(atMs: number, todayMs: number, searchDays: number): number {
  return atMs >= todayMs && atMs < todayMs + searchDays * DAY ? todayMs : utcMidnight(atMs);
}
