import { describe, expect, it } from 'vitest';
import { around, circularMean, dayTicks, earthRadiusDeg, elevRange, exaggeration, segments, type Pt } from '../src/plan/skyTracks';

const H = 3600e3;
const pt = (az: number, el: number, up: boolean, h: number): Pt => ({ az, el, up, t: h * H });

describe('sky chart geometry', () => {
  it('splits a track where visibility changes (sharing the point) and where it wraps past north', () => {
    const pts = [pt(350, 1, true, 0), pt(355, 1, true, 1), pt(359, 0.5, false, 2), pt(3, 0.4, false, 3), pt(8, 1, true, 4)];
    const s = segments(pts, (a) => a, (e) => -e, -5, 10);
    expect(s.map((x) => [x.up, x.pts.length])).toEqual([[true, 2], [false, 2], [true, 2]]);
    expect(s[1].pts[0]).toEqual({ x: 355, y: -1 });   // the hidden piece starts where the visible one ended
    expect(s[2].pts[0]).toEqual({ x: 3, y: -0.4 });
  });
  it('drops points outside the elevation range and does not wrap the close-up', () => {
    const pts = [pt(10, 1, true, 0), pt(20, 50, true, 1), pt(30, 2, true, 2), pt(40, 3, true, 3)];
    expect(segments(pts, (a) => a, (e) => e, 0, 10).map((x) => x.pts.length)).toEqual([2]);
    const loop = [pt(-3, 1, true, 0), pt(359, 1, true, 1)];
    expect(segments(loop, (a) => a, (e) => e, -90, 90, false)).toHaveLength(1);
  });
  it('ticks whole days from the start, with 30 min steps', () => {
    const pts = Array.from({ length: 145 }, (_, i) => pt(0, 0, true, i * 0.5));
    expect(dayTicks(pts)).toEqual([{ i: 0, day: 0 }, { i: 48, day: 1 }, { i: 96, day: 2 }, { i: 144, day: 3 }]);
  });
  it('fits the skyline and the tracks near it; exaggeration is vertical over horizontal scale', () => {
    const r = elevRange([{ azimuth_deg: 0, elevation_deg: -1.2 }, { azimuth_deg: 180, elevation_deg: 2.4 }, { azimuth_deg: 90, elevation_deg: null }],
      [[pt(0, 1.5, true, 0), pt(0, -40, false, 1)], [pt(0, 6.15, true, 0)]]);
    expect(r).toEqual({ lo: -3, hi: 7 });
    expect(exaggeration(2, 20.4)).toBeCloseTo(10.2, 6);
  });
  it('averages and unwraps azimuths around north', () => {
    expect(circularMean([350, 10])).toBeCloseTo(0, 6);
    expect(around(355, 2)).toBe(-5);
    expect(around(10, 358)).toBe(370);
  });
  it('gives Earth about a 1° radius seen from the Moon', () => {
    expect(earthRadiusDeg(384_400_000)).toBeCloseTo(0.9496, 3);
  });
});
