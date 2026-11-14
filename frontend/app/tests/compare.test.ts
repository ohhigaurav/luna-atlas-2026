import { describe, expect, it } from 'vitest';
import { nextText, placeRef, powerMain, powerSub, sunriseSentence, sunriseText, type PeriodPower } from '../src/api/compare';

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

// Gate P numbers (validation/evidence/power_check_2026-11-13.md), Site 001, 30 d.
const oct: PeriodPower = { mean_vertical_w_m2: 1108.4, mean_horizontal_w_m2: 31.4, peak_vertical_w_m2: 1360, energy_vertical_kwh_m2: 797.2,
  partial_sun_percent: 3, step_h: 0.5,
  first_sunrise: { sunrise_utc: '2027-10-16T19:12:00Z', full_disc_utc: '2027-10-17T11:00:00Z', to_full_disc_h: 15.8, lower_bound: false, full_disc_reached: true, resolution_h: 0.5 } };
describe('sunlight on a panel', () => {
  it('shows the vertical panel average, the flat panel and the energy; nothing without the block', () => {
    expect(powerMain(oct)).toBe('1,108 W/m²');
    expect(powerSub(oct, 30)).toBe('flat panel 31 W/m² · vertical 797 kWh/m² over 30 d');
    expect(powerMain(null)).toBe(null);
    expect(powerMain(undefined)).toBe(null);
    expect(sunriseText(undefined)).toBe(null);
  });
  it('words the first sunrise: measured, at least, set again first, none', () => {
    expect(sunriseText(oct)!.main).toBe('15.8 h');
    expect(sunriseText(oct)!.sub).toContain('±0.5 h');
    const fs = oct.first_sunrise!;
    expect(sunriseText({ ...oct, first_sunrise: { ...fs, to_full_disc_h: 37.7, lower_bound: true, full_disc_reached: false } })!.main).toBe('≥ 37.7 h');
    expect(sunriseText({ ...oct, first_sunrise: { ...fs, to_full_disc_h: null, full_disc_reached: false, set_before_full_disc: true, peak_disc_percent: 0.11 } })!.main).toBe('Set again first');
    expect(sunriseText({ ...oct, first_sunrise: { ...fs, to_full_disc_h: null, full_disc_reached: false, set_before_full_disc: true, peak_disc_percent: 0.11 } })!.sub).toContain('0.11%');
    expect(sunriseText({ ...oct, first_sunrise: null })!.main).toBe('No sunrise in the period');
  });
  it('gives the site card one sentence about the first sunrise', () => {
    expect(sunriseSentence(oct)).toBe('First sunrise 16 Oct: whole Sun clear after 15.8 h (±0.5 h).');
    const fs = oct.first_sunrise!;
    expect(sunriseSentence({ ...oct, first_sunrise: { ...fs, to_full_disc_h: 37.7, lower_bound: true } })).toContain('at least 37.7 h');
    expect(sunriseSentence({ ...oct, first_sunrise: { ...fs, to_full_disc_h: null, set_before_full_disc: true } })).toContain('sets again before the whole disc clears');
    expect(sunriseSentence({ ...oct, first_sunrise: null })).toBe(null);
    expect(sunriseSentence(null)).toBe(null);
  });
});

import { sunColour } from '../src/plan/EllipsePanel';
describe('ellipse colour scale', () => {
  it('runs red (dark trap) to amber to green, clamped', () => {
    expect(sunColour(0)).toBe('rgb(239,107,91)');
    expect(sunColour(50)).toBe('rgb(242,184,75)');
    expect(sunColour(100)).toBe('rgb(94,211,148)');
    expect(sunColour(140)).toBe('rgb(94,211,148)');
  });
});
