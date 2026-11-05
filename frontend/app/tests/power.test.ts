import { describe, expect, it } from 'vitest';
import { panelPowerW, simulate, socAt, type SunSample } from '../src/surface/power';

const H = 3600e3;
// 10 h of Sun at 30 deg, then 10 h behind the horizon, hourly samples.
const series: SunSample[] = Array.from({ length: 21 }, (_, i) => ({ tMs: i * H, sunElDeg: i < 10 ? 30 : -2, sunVisible: i < 10 }));

describe('illustrative power model', () => {
  it('flat panel follows sin(el), tracking panel cos(el), nothing when the Sun is hidden', () => {
    expect(panelPowerW({ panelW: 100, panel: 'flat' }, 30, true)).toBeCloseTo(50, 6);
    expect(panelPowerW({ panelW: 100, panel: 'tracking' }, 60, true)).toBeCloseTo(50, 6);
    expect(panelPowerW({ panelW: 100, panel: 'tracking' }, 5, false)).toBe(0);
    expect(panelPowerW({ panelW: 100, panel: 'flat' }, -3, true)).toBe(0);
  });
  it('charges in sunlight (clamped at capacity), drains in the dark, and dies at zero', () => {
    const r = simulate(series, { panelW: 100, panel: 'flat', batteryWh: 200, loadW: 40 }, 0);
    expect(r.socWh[5]).toBe(200);                 // +10 W net while full: stays at capacity
    // Sample 10 is the first hidden one: the step 9->10 averages 50 W and 0 W -> -15 W.
    expect(r.socWh[10]).toBeCloseTo(185, 6);
    expect(r.diedMs).toBeCloseTo(10 * H + (185 / 40) * H, 0);
    expect(r.aliveIsLowerBound).toBe(false);
    expect(socAt(r, 16 * H)).toBe(0);
  });
  it('the same inputs always give the same result, and a big battery survives (lower bound)', () => {
    const p = { panelW: 100, panel: 'tracking' as const, batteryWh: 2000, loadW: 40 };
    const a = simulate(series, p, 0), b = simulate(series, p, 0);
    expect(Array.from(a.socWh)).toEqual(Array.from(b.socWh));
    expect(a.diedMs).toBe(null);
    expect(a.aliveH).toBe(20);
    expect(a.aliveIsLowerBound).toBe(true);
  });
  it('starts at the requested moment', () => {
    const r = simulate(series, { panelW: 100, panel: 'flat', batteryWh: 100, loadW: 10 }, 12 * H);
    expect(r.tMs[0]).toBe(12 * H);
    expect(r.diedMs).toBe(null);              // would empty at 22 h; the series ends at 20 h
    expect(r.socWh[8]).toBeCloseTo(20, 6);
  });
});
