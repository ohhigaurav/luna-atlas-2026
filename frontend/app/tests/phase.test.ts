import { describe, expect, it } from 'vitest';
import { litFraction, moonPhase } from '../src/state/phase';

describe('litFraction (Moon as seen from Earth)', () => {
  it('Sun behind the Earth (full), beside it (quarter), behind the Moon (new)', () => {
    expect(litFraction([1, 0, 0], [1, 0, 0])).toBeCloseTo(1, 12);
    expect(litFraction([0, 1, 0], [1, 0, 0])).toBeCloseTo(0.5, 12);
    expect(litFraction([-1, 0, 0], [1, 0, 0])).toBeCloseTo(0, 12);
  });
  it('120 deg phase angle is 25% lit', () => {
    const a = (120 * Math.PI) / 180;
    expect(litFraction([Math.cos(a), Math.sin(a), 0], [1, 0, 0])).toBeCloseTo(0.25, 12);
  });
});

describe('moonPhase', () => {
  it('names follow the fraction and its trend', () => {
    expect(moonPhase(0.01, 0.02).name).toBe('New Moon');
    expect(moonPhase(0.2, 0.21).name).toBe('Waxing crescent');
    expect(moonPhase(0.5, 0.51).name).toBe('First quarter');
    expect(moonPhase(0.8, 0.81).name).toBe('Waxing gibbous');
    expect(moonPhase(0.99, 0.98).name).toBe('Full Moon');
    expect(moonPhase(0.8, 0.79).name).toBe('Waning gibbous');
    expect(moonPhase(0.5, 0.49).name).toBe('Last quarter');
    expect(moonPhase(0.2, 0.19).name).toBe('Waning crescent');
  });
});
