// Pin status for "Right now on the Moon" (PRD F24): green when a landing window opens within the
// next 30 days, from the same /api/landing-windows answer the planner shows (same request, so a
// click on a green pin is served from cache). Pure: it only compares API timestamps with "now".
import type { LandingResult } from '../api/plan';

export const OUTLOOK_DAYS = 30;
const DAY = 86400e3;

export type Outlook =
  | { kind: 'pending' }
  | { kind: 'error' }
  | { kind: 'window'; fromMs: number; bestMs: number; openNow: boolean; horizonMode: string }
  /** No window in the next OUTLOOK_DAYS. laterMs: the first one after that, inside the search;
   *  miss: the closest try's failed rules (landing.py RULE_TEXT keys) when there is no later one. */
  | { kind: 'none'; horizonMode: string; laterMs?: number; miss?: { atMs: number; rules: string[]; daylightH: number; neededH: number } };

export function outlookOf(result: LandingResult, nowMs: number): Outlook {
  const limit = nowMs + OUTLOOK_DAYS * DAY;
  let best: Outlook | null = null;
  for (const o of result.opportunities) {
    const from = Date.parse(o.touchdown_from_utc), until = Date.parse(o.touchdown_until_utc);
    if (until < nowMs || from > limit) continue;
    const start = Math.max(from, nowMs);
    if (best === null || (best.kind === 'window' && start < best.fromMs)) {
      best = { kind: 'window', fromMs: start, bestMs: Math.max(Date.parse(o.best_touchdown_utc), start), openNow: from <= nowMs, horizonMode: result.horizon_mode };
    }
  }
  if (best) return best;
  const none: Outlook & { kind: 'none' } = { kind: 'none', horizonMode: result.horizon_mode };
  for (const o of result.opportunities) {
    const from = Date.parse(o.touchdown_from_utc);
    if (from > limit && (none.laterMs === undefined || from < none.laterMs)) none.laterMs = from;
  }
  const m = result.closest_miss;
  if (none.laterMs === undefined && m) {
    none.miss = { atMs: Date.parse(m.touchdown_utc), rules: m.failed_rules, daylightH: m.daylight_after_h, neededH: m.daylight_needed_h };
  }
  return none;
}

/** Short pin/list text: "land now", "land 8 Nov", "no window ≤ 30 d". */
export function outlookText(o: Outlook): string {
  switch (o.kind) {
    case 'pending': return 'checking…';
    case 'error': return 'not checked';
    case 'none': return `no window ≤ ${OUTLOOK_DAYS} d`;
    case 'window': return o.openNow ? 'land now' : `land ${new Date(o.fromMs).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })}`;
  }
}

export type Timing = { polar: boolean; ms: number };

/**
 * Time left for the sites still to check, from how long the checked ones took (mean per kind:
 * polar sites use real terrain and are slower). A kind not measured yet borrows the slower known
 * mean. Null until one site has been timed. An estimate: the UI says "about".
 */
export function etaMs(timings: Timing[], left: { polar: number; flat: number }): number | null {
  if (!timings.length) return null;
  const mean = (p: boolean) => { const t = timings.filter((x) => x.polar === p); return t.length ? t.reduce((a, x) => a + x.ms, 0) / t.length : null; };
  const mp = mean(true), mf = mean(false), slow = Math.max(mp ?? 0, mf ?? 0);
  return left.polar * (mp ?? slow) + left.flat * (mf ?? slow);
}

/** "about 3 min left", "about 40 s left", "almost done". */
export function etaText(ms: number): string {
  if (ms < 5000) return 'almost done';
  if (ms < 60e3) return `about ${Math.round(ms / 10e3) * 10 || 10} s left`;
  return `about ${Math.round(ms / 60e3)} min left`;
}
