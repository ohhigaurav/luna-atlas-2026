import { describe, expect, it } from 'vitest';
import type { LandingResult } from '../src/api/plan';
import { fixes, formatDuration, formatIn, nextLanding, type MissAnswer, earthAfter } from '../src/plan/answer';

const T0 = Date.parse('2027-01-01T00:00:00Z');
const at = (d: number) => new Date(T0 + d * 86400e3).toISOString().replace('.000Z', 'Z');
const opp = (from: number, until: number, best: number, sunsetD: number | null, daylightH: number) => ({
  touchdown_from_utc: at(from), touchdown_until_utc: at(until), best_touchdown_utc: at(best),
  daylight_after_best_h: daylightH, daylight_is_lower_bound: sunsetD === null, sunset_utc: sunsetD === null ? null : at(sunsetD),
  sun_elevation_at_best_deg: 5, earth_in_view_during_mission_pct: 100,
});
const result = (opps: ReturnType<typeof opp>[], miss: LandingResult['closest_miss'] = null): LandingResult => ({
  kind: 'landing_opportunities', site: { site_id: 's', name: 'S' }, rules: { mission_days: 10, text: {}, panel_height_m: 2 },
  horizon_mode: 'flat', search: { start_utc: at(0), days: 90 }, opportunities: opps, opportunity_count: opps.length,
  closest_miss: miss, summary: [], caveats: [], compute_seconds: 0,
});

describe('nextLanding', () => {
  const r = result([opp(30, 32, 31, 44, 13 * 24), opp(3, 4, 3.5, 17, 13.5 * 24)]); // unsorted on purpose
  it('picks the earliest window after the knob, with API values untouched', () => {
    const a = nextLanding(r, T0, T0);
    expect(a.kind).toBe('window');
    if (a.kind !== 'window') return;
    expect(a.bestMs).toBe(Date.parse(at(3.5)));
    expect(a.daylightH).toBe(13.5 * 24);
    expect(a.inDays).toBeCloseTo(3.5, 9);
  });
  it('a knob inside a window clips it and recomputes daylight from the API sunset', () => {
    const a = nextLanding(r, Date.parse(at(3.75)), T0);
    if (a.kind !== 'window') throw new Error('expected a window');
    expect(a.fromMs).toBe(Date.parse(at(3.75)));
    expect(a.bestMs).toBe(Date.parse(at(3.75)));
    expect(a.daylightH).toBeCloseTo((17 - 3.75) * 24, 9);
  });
  it('a knob past a window moves to the next one (launch slipped)', () => {
    const a = nextLanding(r, Date.parse(at(5)), T0);
    if (a.kind !== 'window') throw new Error('expected a window');
    expect(a.bestMs).toBe(Date.parse(at(31)));
  });
  it('no window: the closest miss, never a bare no', () => {
    const a = nextLanding(result([], { touchdown_utc: at(12), failed_rules: ['daylight'], daylight_after_h: 9.2 * 24, daylight_needed_h: 240 }), T0, T0);
    expect(a.kind).toBe('miss');
  });
  it('a sunset-less window that is clipped becomes a lower bound', () => {
    const a = nextLanding(result([opp(1, 3, 1, null, 100)]), Date.parse(at(2)), T0);
    if (a.kind !== 'window') throw new Error('expected a window');
    expect(a.daylightH).toBeCloseTo(76, 9);
    expect(a.daylightIsLowerBound).toBe(true);
  });
});

describe('formats', () => {
  it('durations follow the PRD', () => {
    expect(formatDuration(0.75)).toBe('45 min');
    expect(formatDuration(6 + 20 / 60)).toBe('6 h 20 min');
    expect(formatDuration(3 * 24 + 4)).toBe('3 d 4 h');
    expect(formatDuration(30, true)).toBe('≥ 30 h');
  });
  it('countdowns', () => {
    expect(formatIn(70.2)).toBe('in 70 d');
    expect(formatIn(0.4)).toBe('in 10 h');
    expect(formatIn(-3)).toBe('3 d ago');
  });
  it('fixes offer a mission that fits and a higher Sun limit', () => {
    const m: MissAnswer = { kind: 'miss', touchdownMs: T0, daylightH: 9.2 * 24, neededH: 240, failed: ['daylight', 'low_sun'] };
    expect(fixes(m, 10, 20).map((f) => f.label)).toEqual(['10 d → 9 d mission', 'Allow Sun up to 30°']);
  });
});

describe('earthAfter (Earthset countdown after touchdown)', () => {
  const b = [{ start_utc: '2027-01-10T00:00:00Z', end_utc: '2027-01-24T00:00:00Z' }, { start_utc: '2027-02-08T00:00:00Z', end_utc: '2027-02-20T00:00:00Z' }];
  it('gives Earthset when Earth is up at touchdown, Earthrise when it is not', () => {
    expect(earthAfter(b, Date.parse('2027-01-15T00:00:00Z'))).toEqual({ event: 'Earthset', ms: Date.parse('2027-01-24T00:00:00Z') });
    expect(earthAfter(b, Date.parse('2027-01-30T00:00:00Z'))).toEqual({ event: 'Earthrise', ms: Date.parse('2027-02-08T00:00:00Z') });
    expect(earthAfter(b, Date.parse('2027-03-01T00:00:00Z'))).toBeNull();
  });
});
