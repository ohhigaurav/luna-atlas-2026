import { describe, expect, it } from 'vitest';
import { outlookOf, outlookText } from '../src/state/outlook';
import type { LandingResult } from '../src/api/plan';

const NOW = Date.parse('2026-11-05T12:00:00Z');
const opp = (from: string, until: string, best: string) => ({
  touchdown_from_utc: from, touchdown_until_utc: until, best_touchdown_utc: best, daylight_after_best_h: 300,
  daylight_is_lower_bound: false, sunset_utc: null, sun_elevation_at_best_deg: 5, earth_in_view_during_mission_pct: 100,
});
const result = (opps: ReturnType<typeof opp>[]) => ({ horizon_mode: 'terrain', opportunities: opps } as unknown as LandingResult);

describe('outlookOf (pin status)', () => {
  it('is green for the first window that opens within 30 days', () => {
    const o = outlookOf(result([opp('2026-12-20T00:00:00Z', '2026-12-21T00:00:00Z', '2026-12-20T06:00:00Z'),
      opp('2026-11-08T04:00:00Z', '2026-11-09T02:00:00Z', '2026-11-08T10:00:00Z')]), NOW);
    expect(o.kind).toBe('window');
    if (o.kind === 'window') { expect(o.fromMs).toBe(Date.parse('2026-11-08T04:00:00Z')); expect(o.openNow).toBe(false); }
    expect(outlookText(o)).toBe('land 8 Nov');
  });
  it('says land now when a window is open, and clips best to now', () => {
    const o = outlookOf(result([opp('2026-11-05T00:00:00Z', '2026-11-06T00:00:00Z', '2026-11-05T06:00:00Z')]), NOW);
    expect(o.kind === 'window' && o.openNow && o.bestMs === NOW).toBe(true);
    expect(outlookText(o)).toBe('land now');
  });
  it('is not green for windows already closed or more than 30 days away', () => {
    const o = outlookOf(result([opp('2026-11-01T00:00:00Z', '2026-11-02T00:00:00Z', '2026-11-01T06:00:00Z'),
      opp('2026-12-06T00:00:00Z', '2026-12-07T00:00:00Z', '2026-12-06T06:00:00Z')]), NOW);
    expect(o.kind).toBe('none');
    expect(outlookText(o)).toBe('no window ≤ 30 d');
  });
});
