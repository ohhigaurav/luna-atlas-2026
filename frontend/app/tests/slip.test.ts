import { describe, expect, it } from 'vitest';
import { SLIPS, distanceKm, nearbySites, rankBySoonest } from '../src/plan/SlipPanel';
import type { NextLanding } from '../src/compare/nextLanding';

const at = (lat: number, lon: number, id = `s${lat},${lon}`) => ({ site_id: id, name: id, latitude_deg: lat, longitude_deg: lon });

describe('launch slipped', () => {
  it('slips by 7 days and by calendar months (UTC)', () => {
    const t = Date.parse('2027-01-31T00:00:00Z');
    expect(new Date(SLIPS[0].add(t)).toISOString().slice(0, 10)).toBe('2027-02-07');
    expect(new Date(SLIPS[1].add(t)).toISOString().slice(0, 10)).toBe('2027-03-03');
    expect(new Date(SLIPS[2].add(Date.parse('2027-08-01T12:00:00Z'))).toISOString()).toBe('2027-11-01T12:00:00.000Z');
  });
  it('measures great-circle distance on the Moon', () => {
    expect(distanceKm(at(-90, 0), at(-89, 0))).toBeCloseTo(30.32, 1);           // 1° of latitude = 30.3 km
    expect(distanceKm(at(-89.5, 0), at(-89.5, 180))).toBeCloseTo(30.32, 1);     // across the pole
  });
  it('picks the nearest catalogue sites within the limit, never itself or a clicked point', () => {
    const me = at(-89.45, 222.69, 'me');
    const list = [me, at(-89.0, 200, 'a'), at(-88, 0, 'b'), at(0, 0, 'far'), at(-89.4, 222, 'point:-89.4,222'), at(-87, 90, 'c'), at(-86, 10, 'd')];
    const n = nearbySites(me as never, list as never);
    expect(n.map((x) => x.s.site_id)).toEqual(['a', 'b', 'c']);
  });
  it('ranks windows by their start, then no window, with pending in between', () => {
    const w = (fromMs: number): NextLanding => ({ kind: 'window', fromMs, bestMs: fromMs, untilMs: fromMs + 1, openAt: false });
    const xs = [{ id: 'none', n: { kind: 'none', throughMs: 0 } as NextLanding }, { id: 'late', n: w(20) }, { id: 'wait', n: { kind: 'pending' } as NextLanding }, { id: 'soon', n: w(10) }];
    expect(rankBySoonest(xs).map((x) => x.id)).toEqual(['soon', 'late', 'wait', 'none']);
  });
});
