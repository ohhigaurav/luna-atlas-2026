// POST /api/compare (docs/frontend_api.md): 1-6 places side by side at one moment and over the
// next days. Each place is the cached one-button check, so repeats are instant.
import { parsePointId, post, isoZ, type LimitCheck, type Verify } from './plan';

export type NextEvent = { up: boolean; event: string; utc: string | null; in_h: number; lower_bound: boolean; none_in_period?: boolean };
export type BodyNow = { up: boolean; elevation_deg: number; azimuth_deg: number; horizon_deg: number };
/**
 * First sunrise inside the period and how long until the whole disc is clear (backend 0.7.72,
 * power.py). to_full_disc_h is null when the Sun set again before the disc cleared.
 */
export type FirstSunrise = {
  sunrise_utc: string;
  full_disc_utc: string | null;
  to_full_disc_h: number | null;
  /** The window or the period ended first: "at least". */
  lower_bound: boolean;
  full_disc_reached: boolean;
  set_before_full_disc?: boolean;
  peak_disc_percent?: number;
  resolution_h: number;
};
/**
 * Sunlight reaching a panel 2 m up, BEFORE panel efficiency (W/m²): not power output.
 * Missing or null in older static answers.
 */
export type PeriodPower = {
  mean_vertical_w_m2: number;
  mean_horizontal_w_m2: number;
  peak_vertical_w_m2: number;
  energy_vertical_kwh_m2: number;
  partial_sun_percent: number;
  first_sunrise: FirstSunrise | null;
  step_h: number;
  solar_constant_w_m2?: number;
  definition?: string;
  not_included?: string;
};
export type CompareRow = {
  key: string;
  site: { site_id?: string; name: string; latitude_deg: number; longitude_deg: number; origin?: string };
  horizon_mode: string;
  terrain: { finest_resolution_m: number | null; dem_assets: string[]; ground_elevation_m: number | null } | null;
  now: { utc: string; sun: BodyNow; earth: BodyNow };
  sun_next: NextEvent;
  earth_next: NextEvent;
  period: {
    sunlit_percent: number; earth_percent: number; both_percent: number;
    /** Mean visible fraction of the Sun's disc: the power-relevant sunlight (6 Nov). */
    sun_disc_percent?: number | null;
    longest_darkness_h: number; longest_darkness_lower_bound: boolean;
    longest_earth_gap_h: number; longest_earth_gap_lower_bound: boolean;
    /** Sunlight on a panel, before panel efficiency (0.7.72). */
    power?: PeriodPower | null;
  };
  limits_all_pass: boolean;
  /** Each limit of the default mission profile (backend 6 Nov; older backends omit it). */
  limits?: LimitCheck[];
  caveats: string[];
  verify: Verify | null;
  run_id: string;
  cache_hit: boolean;
};
export type CompareResult = {
  kind: 'site_comparison';
  at_utc: string;
  days: number;
  panel_height_m: number;
  rows: CompareRow[];
  leaders: Record<string, string[]>;
  rules: Record<string, string>;
};

/** Place reference for the API: a catalogue site, or a clicked point (app ID "point:LAT,LON"). */
export function placeRef(siteId: string): Record<string, unknown> {
  const p = parsePointId(siteId);
  return p ? { latitude_deg: p.lat, longitude_deg: p.lon } : { site_id: siteId };
}

export function comparePlaces(siteIds: string[], atMs: number, days: number, signal?: AbortSignal): Promise<CompareResult> {
  return post<CompareResult>('/api/compare', { places: siteIds.map(placeRef), at_utc: isoZ(atMs), days, panel_height_m: 2 }, signal);
}

const pct = (x: number) => `${x < 1 ? x.toFixed(2) : x.toFixed(0)}%`;
const wm2 = (x: number) => `${Math.round(x).toLocaleString('en-GB')} W/m²`;

/** "1,201 W/m²" (vertical panel facing the Sun, period average), or null when the answer has no power. */
export function powerMain(p: PeriodPower | null | undefined): string | null {
  return p ? wm2(p.mean_vertical_w_m2) : null;
}

/** "flat panel 31 W/m² · vertical 865 kWh/m² over 30 d" (energy is the vertical panel's, per m²). */
export function powerSub(p: PeriodPower, days: number): string {
  return `flat panel ${wm2(p.mean_horizontal_w_m2)} · vertical ${p.energy_vertical_kwh_m2.toFixed(0)} kWh/m² over ${days} d`;
}

/**
 * Time from the first sunrise in the period until the whole Sun clears the horizon:
 * "15.8 h", "≥ 37.7 h", "set again first", "no sunrise in the period". Null when there is no power block.
 */
export function sunriseText(p: PeriodPower | null | undefined): { main: string; sub?: string } | null {
  if (!p) return null;
  const f = p.first_sunrise;
  if (!f) return { main: 'No sunrise in the period', sub: 'the Sun was already up, or stayed down' };
  const res = `to ±${+f.resolution_h.toFixed(2)} h`;
  if (f.to_full_disc_h == null) return { main: 'Set again first', sub: `the Sun set again before the whole disc cleared${f.peak_disc_percent != null ? `; at most ${pct(f.peak_disc_percent)} of it was up` : ''}` };
  const h = f.to_full_disc_h.toFixed(1);
  return f.lower_bound
    ? { main: `≥ ${h} h`, sub: `period ended first, ${res}` }
    : { main: `${h} h`, sub: `from ${f.sunrise_utc.slice(0, 16).replace('T', ' ')} UTC, ${res}` };
}

/** The site card's sentence about the first sunrise; null when there is no sunrise in the period. */
export function sunriseSentence(p: PeriodPower | null | undefined): string | null {
  const f = p?.first_sunrise;
  if (!f) return null;
  const on = new Date(f.sunrise_utc).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  if (f.to_full_disc_h == null) return `First sunrise ${on}: the Sun sets again before the whole disc clears.`;
  return `First sunrise ${on}: whole Sun clear after ${f.lower_bound ? 'at least ' : ''}${f.to_full_disc_h.toFixed(1)} h (±${+f.resolution_h.toFixed(2)} h).`;
}

/** "sunset in 3 d 4 h", "≥ 30 d to sunrise", "no sunrise in 30 d". */
export function nextText(n: NextEvent, days: number): string {
  if (n.none_in_period) return `no ${n.event} in ${days} d`;
  const h = n.in_h, d = Math.floor(h / 24), hh = Math.round(h - d * 24);
  const span = d ? `${d} d ${hh} h` : h >= 1 ? `${Math.round(h)} h` : `${Math.max(1, Math.round(h * 60))} min`;
  return n.lower_bound ? `${n.event} in ≥ ${span}` : `${n.event} in ${span}`;
}
