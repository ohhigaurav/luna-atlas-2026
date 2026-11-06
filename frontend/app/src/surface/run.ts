// The site's saved run (POST /api/check -> GET /api/runs/{id}): 30 days of Sun and Earth
// azimuth/elevation and terrain visibility every 30 min, plus the horizon profile. Shared by the
// 3D ground view and the battery model.
import { useEffect, useState } from 'react';
import { ApiError, checkSite, fetchRun, type RunRow, type SavedRun } from '../api/plan';

export const RUN_DAYS = 30;

export type RunState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; run: SavedRun; times: Float64Array };
const runCache = new Map<string, Promise<SavedRun>>();

export function useRun(siteId: string, startMs: number, mastM: number): RunState {
  const [st, setSt] = useState<RunState>({ status: 'loading' });
  useEffect(() => {
    let off = false;
    setSt({ status: 'loading' });
    const key = `${siteId}|${startMs}|${mastM}`;
    let p = runCache.get(key);
    if (!p) {
      p = checkSite(siteId, startMs, RUN_DAYS, undefined, mastM).then((c) => fetchRun(c.run_url));
      runCache.set(key, p);
      p.catch(() => runCache.delete(key));
    }
    p.then((run) => {
      if (off) return;
      const times = Float64Array.from(run.sites[0].series, (r) => Date.parse(r.utc));
      setSt({ status: 'ready', run, times });
    }, (e: unknown) => { if (!off) setSt({ status: 'error', message: e instanceof ApiError ? `${e.message} (HTTP ${e.status})` : String(e) }); });
    return () => { off = true; };
  }, [siteId, startMs, mastM]);
  return st;
}

/** Interpolated row at t (azimuths unwrapped across 0/360). */
export function rowAt(series: RunRow[], times: Float64Array, t: number): RunRow | null {
  const n = times.length;
  if (!n || t < times[0] || t > times[n - 1]) return null;
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (times[m] <= t) lo = m; else hi = m; }
  const a = series[lo], b = series[hi], f = hi > lo ? (t - times[lo]) / (times[hi] - times[lo]) : 0;
  const az = (x: number, y: number) => { let d = y - x; if (d > 180) d -= 360; if (d < -180) d += 360; return (x + d * f + 360) % 360; };
  return {
    ...a,
    sun_azimuth_deg: az(a.sun_azimuth_deg, b.sun_azimuth_deg), sun_elevation_deg: a.sun_elevation_deg + (b.sun_elevation_deg - a.sun_elevation_deg) * f,
    earth_azimuth_deg: az(a.earth_azimuth_deg, b.earth_azimuth_deg), earth_elevation_deg: a.earth_elevation_deg + (b.earth_elevation_deg - a.earth_elevation_deg) * f,
    sun_visible_upper_limb: f < 0.5 ? a.sun_visible_upper_limb : b.sun_visible_upper_limb,
    earth_center_clear: f < 0.5 ? a.earth_center_clear : b.earth_center_clear,
  };
}

