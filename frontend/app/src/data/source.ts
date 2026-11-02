// One data layer for both ways the app runs (docs/static_bundle.md):
//   live   FastAPI is reachable: real sky geometry for "now", any dates and sites.
//   static judge bundle in public/data/: unmodified API responses baked by tools/bake_static.py.
// The rest of the app never needs to know which; static mode only disables what it cannot do.
import { fetchSkyGeometry, type SkyGeometry } from '../api/sky';
import type { PinSite } from '../engine/pins';

export type Mode = 'live' | 'static';

export type ReferenceSite = PinSite & {
  latitude_type?: string;
  longitude_direction?: string;
  source_url?: string;
  source_record?: string;
  terrain_status?: string;
  position_kind?: string;
};

export type StaticManifest = {
  schema_version: string;
  kind: 'luna_atlas_static_bundle';
  generated_utc: string;
  git_commit: string | null;
  kernel_manifest_sha256: string;
  settings: { start_utc: string; end_utc: string; step_min: number; heights_m: number[]; flat_height_m: number; antenna_height_m: number };
  files: { reference_sites: string; sky: string };
  runs: Record<string, { file: string; run_id: string; site_id: string; horizon_mode: string; sun_observer_height_m: number }>;
  notes?: Record<string, string>;
  disclaimer?: string;
};

export type DataSource = {
  mode: Mode;
  sites: ReferenceSite[];
  sky: SkyGeometry;
  /** The instant the opening is lit for: now (live) or the bundle's first sample (static). */
  initialCursorMs: number;
  manifest?: StaticManifest;
};

const base = import.meta.env.BASE_URL;

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

async function detectMode(): Promise<Mode> {
  if (import.meta.env.VITE_STATIC === '1') return 'static';
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(2500) });
    if (r.ok) return 'live';
  } catch { /* no backend: fall through to the bundle */ }
  return 'static';
}

export async function loadDataSource(): Promise<DataSource> {
  const mode = await detectMode();
  if (mode === 'live') {
    const now = Date.now();
    // "The Moon right now": a short window around this moment, so the opening is today's lighting.
    const start = new Date(now - 2 * 3600e3).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const end = new Date(now + 2 * 86400e3).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const [sitesRes, sky] = await Promise.all([
      getJson<{ sites: ReferenceSite[] }>('/api/reference-sites'),
      fetchSkyGeometry(start, end, 30),
    ]);
    return { mode, sites: sitesRes.sites, sky, initialCursorMs: now };
  }
  let manifest: StaticManifest;
  try {
    manifest = await getJson<StaticManifest>(`${base}data/manifest.json`);
  } catch {
    throw new Error('No backend and no baked data. Start ./scripts/run_local.sh, or bake the static bundle (docs/static_bundle.md).');
  }
  const [sitesRes, sky] = await Promise.all([
    getJson<{ sites: ReferenceSite[] }>(`${base}data/${manifest.files.reference_sites}`),
    getJson<SkyGeometry>(`${base}data/${manifest.files.sky}`),
  ]);
  return { mode, sites: sitesRes.sites, sky, initialCursorMs: Date.parse(sky.series.utc[0]), manifest };
}
