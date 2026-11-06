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
  | { kind: 'none'; throughMs: number };

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
  return best ?? { kind: 'none', throughMs: through };
}

/** Where to start the search for a moment: today's search (warm, usually cached) when it covers the moment. */
export function searchStartFor(atMs: number, todayMs: number, searchDays: number): number {
  return atMs >= todayMs && atMs < todayMs + searchDays * DAY ? todayMs : utcMidnight(atMs);
}
