import { describe, expect, it } from 'vitest';
import type { LandingResult } from '../src/api/plan';
import { nextLandingAt, searchStartFor } from '../src/compare/nextLanding';

const T = (s: string) => Date.parse(s);
const opp = (from: string, best: string, until: string) => ({
  touchdown_from_utc: from, best_touchdown_utc: best, touchdown_until_utc: until, sun_above_horizon_at_best_deg: 1.5,
});
const result = (start: string, days: number, opps: ReturnType<typeof opp>[], longest?: [string, string, number]): LandingResult => ({
  kind: 'landing_opportunities', site: { site_id: 's', name: 'S' }, rules: { mission_days: 10, text: {}, panel_height_m: 2 },
  horizon_mode: 'terrain', search: { start_utc: start, days }, opportunities: opps as never, opportunity_count: opps.length,
  closest_miss: null, summary: [], caveats: [], compute_seconds: 0,
  longest_sunlit_window: longest ? { start_utc: longest[0], end_utc: longest[1], hours: longest[2], is_lower_bound: false } : null,
});

describe('next landing window at a moment', () => {
  const r = result('2026-11-07T00:00:00Z', 90, [
    opp('2026-11-20T00:00:00Z', '2026-11-21T00:00:00Z', '2026-11-22T00:00:00Z'),
    opp('2026-12-18T00:00:00Z', '2026-12-19T00:00:00Z', '2026-12-20T00:00:00Z'),
  ]);
  it('picks the first window that has not closed', () => {
    const n = nextLandingAt([r], T('2026-11-25T00:00:00Z'));
    expect(n).toMatchObject({ kind: 'window', openAt: false, fromMs: T('2026-12-18T00:00:00Z'), bestMs: T('2026-12-19T00:00:00Z') });
  });
  it('says "open now" inside a window and never points best before the moment', () => {
    const n = nextLandingAt([r], T('2026-11-21T12:00:00Z'));
    expect(n).toMatchObject({ kind: 'window', openAt: true, fromMs: T('2026-11-21T12:00:00Z'), bestMs: T('2026-11-21T12:00:00Z') });
  });
  it('when nothing is left, reports the searched end, the last earlier window and the longest later sunlight', () => {
    const later = result('2027-01-19T00:00:00Z', 90, [], ['2027-03-03T00:00:00Z', '2027-03-10T05:00:00Z', 173]);
    later.closest_miss = { touchdown_utc: '2027-02-08T00:00:00Z', failed_rules: ['daylight'], daylight_after_h: 190, daylight_needed_h: 240 };
    r.closest_miss = { touchdown_utc: '2026-11-08T00:00:00Z', failed_rules: [], daylight_after_h: 0, daylight_needed_h: 240 }; // before the moment: ignored
    const n = nextLandingAt([r, later], T('2027-01-19T03:00:00Z'));
    r.closest_miss = null;
    expect(n).toEqual({
      kind: 'none', throughMs: T('2027-04-19T00:00:00Z'),
      miss: { atMs: T('2027-02-08T00:00:00Z'), rules: ['daylight'], daylightH: 190, neededH: 240 },
      longest: { fromMs: T('2027-03-03T00:00:00Z'), hours: 173, lowerBound: false },
      earlier: { fromMs: T('2026-12-18T00:00:00Z'), bestMs: T('2026-12-19T00:00:00Z') },
    });
  });
  it('ignores a longest stretch that ended before the moment', () => {
    const old = result('2026-11-07T00:00:00Z', 90, [], ['2026-11-10T00:00:00Z', '2026-11-15T00:00:00Z', 120]);
    expect(nextLandingAt([old], T('2027-01-01T00:00:00Z'))).toEqual({ kind: 'none', throughMs: T('2027-02-05T00:00:00Z') });
  });
  it("reuses today's search when it covers the moment, else searches from the moment's day", () => {
    const today = T('2026-11-07T00:00:00Z');
    expect(searchStartFor(T('2027-01-19T03:00:00Z'), today, 90)).toBe(today);
    expect(searchStartFor(T('2027-03-01T15:00:00Z'), today, 90)).toBe(T('2027-03-01T00:00:00Z'));
    expect(searchStartFor(T('2026-10-01T15:00:00Z'), today, 90)).toBe(T('2026-10-01T00:00:00Z'));
  });
});
