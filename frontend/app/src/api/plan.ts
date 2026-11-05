// Client for the two "simple flow" calls (docs/frontend_api.md). Field names follow
// backend/lunar_core/landing.py (run_landing) and check.py (run_check); neither endpoint has a
// response model yet, so these types are hand-written from that code.

export type UtcRange = { start_utc: string; end_utc: string };

export type LandingOpportunity = {
  touchdown_from_utc: string;
  touchdown_until_utc: string;
  best_touchdown_utc: string;
  daylight_after_best_h: number;
  daylight_is_lower_bound: boolean;
  sunset_utc: string | null;
  sun_elevation_at_best_deg: number;
  earth_in_view_during_mission_pct: number;
};

export type LandingResult = {
  kind: 'landing_opportunities';
  site: { site_id: string; name: string };
  rules: { mission_days: number; text: Record<string, string>; panel_height_m: number };
  horizon_mode: 'flat' | 'terrain' | string;
  search: { start_utc: string; days: number };
  opportunities: LandingOpportunity[];
  opportunity_count: number;
  closest_miss: { touchdown_utc: string; failed_rules: string[]; daylight_after_h: number; daylight_needed_h: number } | null;
  summary: string[];
  caveats: string[];
  compute_seconds: number;
};

export type LimitCheck = {
  key: string;
  label: string;
  text: string;
  status: 'pass' | 'fail' | 'unknown' | 'no_limit' | string;
  lower_bound?: boolean;
};

export type CheckResult = {
  kind: 'site_check';
  chosen_settings: { horizon_mode: string; sun_observer_height_m: number; antenna_height_m: number };
  summary: {
    headline: string;
    lines: string[];
    numbers: { sunlit_percent: number; earth_percent: number; both_percent: number };
    limits: { source: string; checks: LimitCheck[]; all_pass: boolean };
    bands: { sun: UtcRange[]; earth: UtcRange[] };
    terrain_status: string;
    caveats: string[];
  };
  run_id: string;
  run_url: string;
  cache_hit: boolean;
  compute_seconds: number | null;
};

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function post<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (!r.ok) {
    const j = (await r.json().catch(() => ({}))) as { detail?: unknown };
    const d = j.detail;
    const msg = typeof d === 'string' ? d
      : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg ?? String(x)).join('; ')
      : `HTTP ${r.status}`;
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}

/** ISO instant with seconds and a Z, as the API requires. */
export function isoZ(ms: number): string {
  return new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function findLandingWindows(siteId: string, startMs: number, days: number, missionDays: number, signal?: AbortSignal,
  maxSunElevationDeg: number | null = 20) {
  return post<LandingResult>('/api/landing-windows',
    { site_id: siteId, search_start_utc: isoZ(startMs), search_days: days, mission_days: missionDays,
      max_sun_elevation_deg: maxSunElevationDeg }, signal);
}

export function checkSite(siteId: string, startMs: number, days: number, signal?: AbortSignal, panelHeightM = 2) {
  return post<CheckResult>('/api/check', { site_id: siteId, start_utc: isoZ(startMs), days, panel_height_m: panelHeightM }, signal);
}

/** One row of a saved run's series (analysis_service.run_analysis timeline). */
export type RunRow = {
  utc: string;
  sun_azimuth_deg: number; sun_elevation_deg: number; sun_horizon_deg: number; sun_visible_upper_limb: boolean;
  earth_azimuth_deg: number; earth_elevation_deg: number; earth_horizon_deg: number; earth_center_clear: boolean;
};
export type HorizonBin = { azimuth_deg: number; elevation_deg: number | null; coverage_status?: string };
export type SavedRun = {
  run_id: string;
  settings: { horizon_mode: string; sun_observer_height_m: number; antenna_height_m: number };
  sites: { site: { site_id: string; name: string }; terrain_status: string; horizon_profile: HorizonBin[]; earth_horizon_profile: HorizonBin[]; series: RunRow[] }[];
};

export async function fetchRun(runUrl: string, signal?: AbortSignal): Promise<SavedRun> {
  const r = await fetch(runUrl, { signal });
  if (!r.ok) throw new ApiError(r.status, `run ${r.status}`);
  return (await r.json()) as SavedRun;
}
