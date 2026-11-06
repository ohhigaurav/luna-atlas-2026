import { describe, expect, it } from 'vitest';
import { parseCoords } from '../src/state/coords';

describe('parseCoords (typed coordinates)', () => {
  it('reads signed and hemisphere forms, longitude east in [0, 360)', () => {
    expect(parseCoords('-89.45, 223.2')).toEqual({ lat: -89.45, lon: 223.2 });
    expect(parseCoords('89.45S 223.2E')).toEqual({ lat: -89.45, lon: 223.2 });
    expect(parseCoords('89.45 S, 136.8 W')).toEqual({ lat: -89.45, lon: 223.2 });
    expect(parseCoords('0.674° N 23.473° E')).toEqual({ lat: 0.674, lon: 23.473 });
  });
  it('refuses dates, words and impossible values', () => {
    expect(parseCoords('2027 3')).toBeNull();
    expect(parseCoords('13 jan 2027')).toBeNull();
    expect(parseCoords('95.0, 10')).toBeNull();
    expect(parseCoords('-89 S, 10 E')).toBeNull();
  });
});
