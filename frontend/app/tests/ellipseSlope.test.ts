import { describe, expect, it } from 'vitest';
import { bestWithin, shareAtOrBelow, slopeVerdict, type EllipsePoint } from '../src/plan/EllipsePanel';

const pt = (e: number, sun: number, slope: number | null, status = 'ok') => ({
  east_m: e, north_m: 0, latitude_deg: 0, longitude_deg: 0, status, sunlit_percent: sun, dte_clear_percent: 50, both_percent: 40,
  longest_darkness_h: 0, ground_elevation_m: 0, slope_deg: slope, slope_err_deg: null,
}) as EllipsePoint;

describe('ellipse slope against a lander limit', () => {
  it('uses the error band: within, uncertain, over', () => {
    expect(slopeVerdict(6, 1, 8)).toBe('within');
    expect(slopeVerdict(7.5, 1, 8)).toBe('uncertain');
    expect(slopeVerdict(9.5, 1, 8)).toBe('over');
    expect(slopeVerdict(8, null, 8)).toBe('within');
  });
  it('reads the share from the CDF at the limit (0.5° steps)', () => {
    const cdf = { step_deg: 0.5, share_at_or_below: [0, 0.1, 0.2, 0.3, 0.4, 0.5] };
    expect(shareAtOrBelow(cdf, 1.0)).toBe(0.2);
    expect(shareAtOrBelow(cdf, 1.2)).toBe(0.2);
    expect(shareAtOrBelow(cdf, 99)).toBe(0.5);
  });
  it('picks the sunniest point no steeper than the limit, skipping unanswered ones', () => {
    const pts = [pt(1, 90, 12), pt(2, 70, 5), pt(3, 80, 7.9), pt(4, 99, null), pt(5, 95, 1, 'unavailable')];
    expect(bestWithin(pts, 8)?.east_m).toBe(3);
    expect(bestWithin(pts, 15)?.east_m).toBe(1);
    expect(bestWithin(pts, 1)).toBeNull();
  });
});
