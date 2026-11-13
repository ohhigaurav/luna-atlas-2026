// One data layer for both ways the app runs (docs/static_bundle.md):
//   live   FastAPI is reachable: real sky geometry for "now", any dates and sites.
//   static judge bundle in public/data/: unmodified API responses baked by tools/bake_static.py.
// The rest of the app never needs to know which; static mode only disables what it cannot do.
import type { AnswersIndex } from './staticAnswers';
import { enableStaticAnswers } from './staticMode';
import { API } from '../api/base';
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
  /** "official" (challenge sites; none were published) or "reference"; from GET /api/site-index. */
  origin?: string;
  kind?: string;
  /** Our measured finding about this site, kept apart from the citation (docs/frontend_api.md). */
  analysis_note?: { text: string; evidence?: string; suggested_point?: { latitude_deg: number; longitude_deg: number; label: string } };
};

/** GET /api/site-index without the sites: whether the official challenge list is in yet. */
export type SiteIndexInfo = { official_state: string; official_count: number; reference_count?: number; note?: string };
type SiteIndex = SiteIndexInfo & { sites: ReferenceSite[] };

export type StaticManifest = {
  schema_version: string;
  kind: 'luna_atlas_static_bundle';
  generated_utc: string;
  git_commit: string | null;
  kernel_manifest_sha256: string;
  settings: { start_utc: string; end_utc: string; step_min: number; heights_m: number[]; flat_height_m: number; antenna_height_m: number };
  files: { reference_sites: string; site_index?: string; sky: string };
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
  index: SiteIndexInfo;
  /** Static site with precomputed answers: the times they exist for. */
  answers?: { bakedTimes: string[] };
};

/** Official sites first (the API already orders them; keep it true for any source). */
function fromIndex(ix: SiteIndex): { sites: ReferenceSite[]; index: SiteIndexInfo } {
  const { sites, ...info } = ix;
  const off = sites.filter((x) => x.origin === 'official'), rest = sites.filter((x) => x.origin !== 'official');
  return { sites: [...off, ...rest], index: { ...info, official_count: info.official_count ?? off.length } };
}
const REFERENCE_ONLY: SiteIndexInfo = { official_state: 'awaiting_official_source', official_count: 0 };

const base = import.meta.env.BASE_URL;

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

/**
 * Live if the backend answers. Probe with /api/reference-sites (a small JSON file the app needs
 * anyway), not /api/health: health re-hashes every kernel and DEM (~300 MB) and can take longer
 * than any sensible probe timeout, which silently dropped the app into static mode.
 */
async function detectLive(): Promise<{ sites: ReferenceSite[]; index: SiteIndexInfo } | null> {
  if (import.meta.env.VITE_STATIC === '1') return null;
  try {
    // The site index (official challenge sites first) is the source; an older backend without it
    // falls back to the reference catalogue.
    const r = await fetch(`${API}/api/site-index`, { signal: AbortSignal.timeout(8000) });
    if (r.ok) return fromIndex((await r.json()) as SiteIndex);
    const f = await fetch(`${API}/api/reference-sites`, { signal: AbortSignal.timeout(8000) });
    if (!f.ok) return null;
    return { sites: ((await f.json()) as { sites: ReferenceSite[] }).sites, index: REFERENCE_ONLY };
  } catch {
    return null; // no backend: fall through to the bundle
  }
}

export async function loadDataSource(): Promise<DataSource> {
  const live = await detectLive();
  if (live) {
    const now = Date.now();
    // "The Moon right now": today's lighting, and 30 days ahead so every site can say when its
    // Sun next rises or sets (one lunar day is 29.5 days).
    const start = new Date(now - 2 * 3600e3).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const end = new Date(now + 30 * 86400e3).toISOString().replace(/\.\d{3}Z$/, 'Z');
    const sky = await fetchSkyGeometry(start, end, 30);
    return { mode: 'live', sites: live.sites, index: live.index, sky, initialCursorMs: now };
  }
  const mode: Mode = 'static';
  let manifest: StaticManifest;
  try {
    manifest = await getJson<StaticManifest>(`${base}data/manifest.json`);
  } catch {
    throw new Error('No backend and no baked data. Start ./scripts/run_local.sh, or bake the static bundle (docs/static_bundle.md).');
  }
  const siteIndex = manifest.files.site_index
    ? getJson<SiteIndex>(`${base}data/${manifest.files.site_index}`).then(fromIndex)
    : Promise.reject(new Error('no site index in this bundle'));
  const [sitesRes, sky] = await Promise.all([
    siteIndex.catch(() => getJson<{ sites: ReferenceSite[] }>(`${base}data/${manifest.files.reference_sites}`).then((r) => ({ sites: r.sites, index: REFERENCE_ONLY }))),
    getJson<SkyGeometry>(`${base}data/${manifest.files.sky}`),
  ]);
  // Precomputed API answers (tools/bake_answers.py): with them the static site answers landing,
  // compare, the ellipse and the 3D ground view for the baked dates; without them it shows geometry only.
  const answers = await getJson<AnswersIndex>(`${base}data/answers/index.json`).catch(() => null);
  if (answers) enableStaticAnswers(answers, base);
  return { mode, sites: sitesRes.sites, index: sitesRes.index, sky, initialCursorMs: Date.parse(sky.series.utc[0]), manifest,
    answers: answers ? { bakedTimes: answers.baked_times } : undefined };
}
