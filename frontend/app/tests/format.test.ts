import { describe, expect, it } from 'vitest';
import { formatLat, formatLon, formatUtc } from '../src/state/format';

describe('formatLon (API is 0-360 east)', () => {
  it('east and west hemispheres', () => {
    expect(formatLon(23.47314)).toBe('23.47° E');      // Apollo 11
    expect(formatLon(323.42)).toBe('36.58° W');
    expect(formatLon(357.07)).toBe('2.93° W');         // Malapert
  });
  it('prime and antimeridian carry no hemisphere', () => {
    expect(formatLon(0)).toBe('0.00°');
    expect(formatLon(360)).toBe('0.00°');
    expect(formatLon(180)).toBe('180.00°');
  });
});

describe('formatLat', () => {
  it('north, south, equator', () => {
    expect(formatLat(0.67416)).toBe('0.67° N');
    expect(formatLat(-84.7906)).toBe('84.79° S');
    expect(formatLat(0)).toBe('0.00°');
  });
});

describe('formatUtc', () => {
  it('minute precision, explicit UTC', () => {
    expect(formatUtc(Date.parse('2027-01-14T06:00:59Z'))).toBe('2027-01-14 06:00 UTC');
  });
});
