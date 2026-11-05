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
  | { kind: 'none'; horizonMode: string };   // no window in the next OUTLOOK_DAYS (later ones may exist)

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
  return best ?? { kind: 'none', horizonMode: result.horizon_mode };
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
