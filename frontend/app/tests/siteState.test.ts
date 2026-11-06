import { describe, expect, it } from 'vitest';
import type { SkyGeometry } from '../src/api/sky';
import { siteNow, spanText } from '../src/state/siteState';
import { sampleTimesMs } from '../src/api/sky';
import { classifyDays } from '../src/plan/calendarDays';

// Sun on the equator, sub-solar longitude moving west 12.19 deg/day (one synodic month), hourly.
const T0 = Date.parse('2027-01-01T00:00:00Z');
const n = 24 * 40;
const lon = (k: number) => (90 - (360 / 29.530589) * (k / 24)) * Math.PI / 180;
const sky = {
  series: {
    utc: Array.from({ length: n }, (_, k) => new Date(T0 + k * 3600e3).toISOString()),
    sun: { unit: Array.from({ length: n }, (_, k) => [Math.cos(lon(k)), Math.sin(lon(k)), 0]), angular_radius_deg: Array(n).fill(0.2666) },
    // Earth fixed over 0 E, 0 N but nodding 6 deg north and south over 27.3 days (libration-like).
    earth: { unit: Array.from({ length: n }, (_, k) => { const b = 6 * Math.sin((2 * Math.PI * k) / (24 * 27.3)) * Math.PI / 180; return [Math.cos(b), 0, Math.sin(b)]; }) },
  },
} as unknown as SkyGeometry;
const times = sampleTimesMs(sky);

describe('siteNow (flat horizon, from sky geometry only)', () => {
  it('sees the Sun overhead at the sub-solar point and finds sunset a quarter month later', () => {
    const s = siteNow(sky, times, 0, 90, T0);
    expect(s.day).toBe(true);
    expect(s.sunElDeg).toBeCloseTo(90, 3);
    // Sunset when the sub-solar point is 90 deg (+ solar radius) west: 7.38 d + 0.27/12.19 d.
    expect((s.nextChangeMs! - T0) / 86400e3).toBeCloseTo(29.530589 / 4 + 0.2666 / (360 / 29.530589), 2);
  });
  it('a night site reports its next sunrise; none in the window is reported as null', () => {
    const s = siteNow(sky, times, 0, 270, T0);
    expect(s.day).toBe(false);
    expect(s.nextChangeMs! > T0).toBe(true);
    expect(siteNow(sky, times, 89.99, 0, T0).nextChangeMs).toBe(null);
  });
  it('tracks Earth too: always up at the near-side centre, set and rise near the pole', () => {
    expect(siteNow(sky, times, 0, 0, T0)).toMatchObject({ earthUp: true, earthNextMs: null });
    const p = siteNow(sky, times, 89, 0, T0);           // Earth starts on the horizon, climbing
    expect(p.earthUp).toBe(true);
    // Earth sets when its latitude passes -1 deg: 6 sin(x) = -1 -> x = pi + asin(1/6)
    expect((p.earthNextMs! - T0) / 86400e3).toBeCloseTo((27.3 * (Math.PI + Math.asin(1 / 6))) / (2 * Math.PI), 1);
  });
  it('spanText rounds sensibly', () => {
    expect(spanText(30 * 60e3)).toBe('30 min');
    expect(spanText(17.4 * 3600e3)).toBe('17 h');
    expect(spanText((4 * 24 + 3.2) * 3600e3)).toBe('4 d 3 h');
    expect(spanText(5 * 86400e3)).toBe('5 d');
  });
});

describe('classifyDays (calendar heat map)', () => {
  const at = (h: number) => new Date(T0 + h * 3600e3).toISOString();
  const opp = { touchdown_from_utc: at(30), touchdown_until_utc: at(40), best_touchdown_utc: at(34), daylight_after_best_h: 300,
    daylight_is_lower_bound: false, sunset_utc: null, sun_elevation_at_best_deg: 3, earth_in_view_during_mission_pct: 100 };
  it('marks landing days, sunlit days, dark days and days outside the search', () => {
    const days = classifyDays(T0 - 86400e3, T0 + 4 * 86400e3, [opp], [{ start_utc: at(0), end_utc: at(60) }], T0, T0 + 3 * 86400e3);
    expect(days.map((x) => x.kind)).toEqual(['outside', 'sun', 'land', 'sun', 'outside']);
    expect(days[3].sunFraction).toBeCloseTo(0.5, 6);
  });
  it('says unknown, not dark, when the sunlight bands have not arrived', () => {
    const days = classifyDays(T0, T0 + 86400e3, [], null, T0, T0 + 86400e3);
    expect(days[0].kind).toBe('unknown');
  });
});
