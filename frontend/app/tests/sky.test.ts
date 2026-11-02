import { describe, expect, it } from 'vitest';
import { sampleTimesMs, skyAt, type SkyGeometry, type Vec3 } from '../src/api/sky';

// Synthetic track: Sun rotating about +Z at the real rate (360 deg / 29.53 d), 30 min steps.
function fixture(): SkyGeometry {
  const stepMin = 30, n = 49, start = Date.parse('2027-01-01T00:00:00Z');
  const rate = (2 * Math.PI) / (29.530589 * 86400e3);
  const utc: string[] = [], sun: Vec3[] = [], earth: Vec3[] = [], frac: number[] = [];
  for (let k = 0; k < n; k++) {
    const t = start + k * stepMin * 60e3, a = (t - start) * rate;
    utc.push(new Date(t).toISOString().replace('.000', ''));
    sun.push([Math.cos(a), Math.sin(a), 0]);
    earth.push([1, 0, 0]);
    frac.push(k / (n - 1));
  }
  const track = (u: Vec3[]) => ({ unit: u, distance_km: u.map(() => 1), sub_lat_deg: u.map(() => 0),
    sub_lon_east_deg: u.map((v) => ((Math.atan2(v[1], v[0]) * 180) / Math.PI + 360) % 360), angular_radius_deg: u.map(() => 0.27) });
  return {
    schema_version: '1.0', kind: 'sky_geometry', frame: 'MOON_ME', observer_center: 'MOON',
    aberration_correction: 'LT+S', moon_reference_radius_m: 1737400, conventions: {},
    settings: { start_utc: utc[0], end_utc: utc[n - 1], step_min: stepMin, sample_count: n },
    series: { utc, et_s: utc.map((_, k) => k * 1800), sun: track(sun),
      earth: { ...track(earth), phase_angle_deg: frac.map(() => 0), illuminated_fraction: frac } },
  };
}

const angDeg = (a: Vec3, b: Vec3) => (Math.acos(Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])) * 180) / Math.PI;

describe('skyAt', () => {
  const sky = fixture(), times = sampleTimesMs(sky);
  const start = times[0], rate = (2 * Math.PI) / (29.530589 * 86400e3);

  it('returns the sample exactly at sample times', () => {
    expect(angDeg(skyAt(sky, times, times[10]).sunDir, sky.series.sun.unit[10])).toBeLessThan(1e-6);
  });

  it('is within 0.01 deg of the true direction between samples', () => {
    for (let m = 1; m < 1440; m += 7) {
      const t = start + m * 60e3, a = (t - start) * rate;
      expect(angDeg(skyAt(sky, times, t).sunDir, [Math.cos(a), Math.sin(a), 0])).toBeLessThan(0.01);
    }
  });

  it('returns unit vectors and clamps outside the window', () => {
    const before = skyAt(sky, times, start - 3600e3), after = skyAt(sky, times, times[times.length - 1] + 3600e3);
    expect(Math.hypot(...before.sunDir)).toBeCloseTo(1, 12);
    expect(angDeg(before.sunDir, sky.series.sun.unit[0])).toBeLessThan(1e-6);
    expect(angDeg(after.sunDir, sky.series.sun.unit.at(-1)!)).toBeLessThan(1e-6);
  });

  it('interpolates Earth illuminated fraction', () => {
    expect(skyAt(sky, times, (times[0] + times[1]) / 2).earthIllumFrac).toBeCloseTo(0.5 / 48, 9);
  });
});
