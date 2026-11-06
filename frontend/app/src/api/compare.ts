// POST /api/compare (docs/frontend_api.md): 1-6 places side by side at one moment and over the
// next days. Each place is the cached one-button check, so repeats are instant.
import { parsePointId, post, isoZ, type Verify } from './plan';

export type NextEvent = { up: boolean; event: string; utc: string | null; in_h: number; lower_bound: boolean; none_in_period?: boolean };
export type BodyNow = { up: boolean; elevation_deg: number; azimuth_deg: number; horizon_deg: number };
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
    longest_darkness_h: number; longest_darkness_lower_bound: boolean;
    longest_earth_gap_h: number; longest_earth_gap_lower_bound: boolean;
  };
  limits_all_pass: boolean;
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

/** "sunset in 3 d 4 h", "≥ 30 d to sunrise", "no sunrise in 30 d". */
export function nextText(n: NextEvent, days: number): string {
  if (n.none_in_period) return `no ${n.event} in ${days} d`;
  const h = n.in_h, d = Math.floor(h / 24), hh = Math.round(h - d * 24);
  const span = d ? `${d} d ${hh} h` : h >= 1 ? `${Math.round(h)} h` : `${Math.max(1, Math.round(h * 60))} min`;
  return n.lower_bound ? `${n.event} in ≥ ${span}` : `${n.event} in ${span}`;
}
