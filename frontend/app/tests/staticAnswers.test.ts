import { describe, expect, it } from 'vitest';
import golden from './static_keys.golden.json';
import { fmt, makeKey, normTime, snapToBaked, type AnswersIndex, type KeySpec } from '../src/data/staticAnswers';

// Same spec as backend/lunar_core/static_answers.py KEY_SPEC (the bundle publishes it as key_spec).
const SPEC: KeySpec = {
  'landing-windows': [['place', null], ['search_start_utc', null], ['search_days', 90], ['mission_days', 10],
    ['panel_height_m', 2], ['require_earth_at_landing', true], ['max_sun_elevation_deg', 20], ['min_sun_elevation_deg', 'auto']],
  check: [['place', null], ['start_utc', null], ['days', 30], ['panel_height_m', 2]],
  compare: [['place', null], ['at_utc', null], ['days', 30], ['panel_height_m', 2]],
  'landing-ellipse': [['site_id', null], ['start_utc', null], ['days', 14], ['semi_major_m', 250], ['semi_minor_m', null],
    ['orientation_deg', 0], ['spacing_m', null], ['panel_height_m', 2]],
};

describe('static answer keys match the backend', () => {
  for (const c of golden.cases) {
    it(c.endpoint, () => expect(makeKey(SPEC, c.endpoint, c.body as Record<string, unknown>)).toBe(c.key));
  }
  it('formats like Python', () => {
    expect(fmt(2.0)).toBe('2');
    expect(fmt(2.5)).toBe('2.5');
    expect(fmt(null)).toBe('null');
    expect(normTime('2027-01-01T05:30:00+05:30')).toBe('2027-01-01T00:00:00Z');
  });
  it('snaps to the baked time at or before', () => {
    const idx = { baked_times: ['2027-01-01T00:00:00Z', '2027-01-08T00:00:00Z'] } as AnswersIndex;
    expect(snapToBaked(idx, Date.parse('2027-01-10T12:00:00Z'))).toBe('2027-01-08T00:00:00Z');
    expect(snapToBaked(idx, Date.parse('2026-12-01T00:00:00Z'))).toBe('2027-01-01T00:00:00Z');
  });
});
