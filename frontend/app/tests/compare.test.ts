import { describe, expect, it } from 'vitest';
import { nextText, placeRef } from '../src/api/compare';

describe('compare helpers', () => {
  it('words the next sunset / Earthset like the API means it', () => {
    expect(nextText({ up: true, event: 'earthset', utc: 'x', in_h: 146.2, lower_bound: false }, 30)).toBe('earthset in 6 d 2 h');
    expect(nextText({ up: true, event: 'sunset', utc: 'x', in_h: 720, lower_bound: true }, 30)).toBe('sunset in ≥ 30 d 0 h');
    expect(nextText({ up: false, event: 'earthrise', utc: null, in_h: 720, lower_bound: true, none_in_period: true }, 30)).toBe('no earthrise in 30 d');
    expect(nextText({ up: false, event: 'sunrise', utc: 'x', in_h: 0.5, lower_bound: false }, 30)).toBe('sunrise in 30 min');
  });
  it('sends clicked points as coordinates', () => {
    expect(placeRef('point:-89.4500,223.2000')).toEqual({ latitude_deg: -89.45, longitude_deg: 223.2 });
    expect(placeRef('reference-lola-site-001')).toEqual({ site_id: 'reference-lola-site-001' });
  });
});
