// Pre-computed API answers for the static judge site (no backend). Mirror of
// backend/lunar_core/static_answers.py: same key, same defaults, checked against the shared
// vectors in tests/static_keys.golden.json. The bundle's data/answers/index.json maps each key to
// a file holding the unmodified API response (tools/bake_answers.py).

export type KeySpec = Record<string, Array<[string, unknown]>>;

export type AnswersIndex = {
  schema_version: string;
  kind: 'luna_atlas_static_answers';
  key_spec: KeySpec;
  baked_times: string[];        // the start / at times answers exist for (UTC, "YYYY-MM-DDTHH:MM:SSZ")
  answers: Record<string, string>; // key -> file, relative to data/
  runs: Record<string, string>;    // run_id -> file, for GET /api/runs/{id}
};

const TIME_FIELDS = new Set(['search_start_utc', 'start_utc', 'at_utc']);

export function normTime(v: unknown): string {
  const s = String(v);
  if (!/(Z|[+-]\d\d:?\d\d)$/.test(s)) throw new Error(`time without timezone: ${s}`);
  return new Date(s).toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function fmt(v: unknown): string {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') {
    if (!Number.isFinite(v)) throw new Error('non-finite number in a key');
    return Number.isInteger(v) ? String(Math.trunc(v)) : String(v);
  }
  return String(v);
}

export function placeOf(body: Record<string, unknown>): string {
  if (body.site_id !== undefined && body.site_id !== null) return String(body.site_id);
  const lat = Number(body.latitude_deg), lon = ((Number(body.longitude_deg) % 360) + 360) % 360;
  return `point:${lat.toFixed(4)},${lon.toFixed(4)}`;
}

export function makeKey(spec: KeySpec, endpoint: string, body: Record<string, unknown>): string {
  const fields = spec[endpoint];
  if (!fields) throw new Error(`no static answers for ${endpoint}`);
  const parts = fields.map(([name, dflt]) => {
    let v = name === 'place' ? placeOf(body) : (name in body ? body[name] : dflt);
    if (TIME_FIELDS.has(name)) v = normTime(v);
    return `${name}=${fmt(v)}`;
  });
  return `${endpoint}?${parts.join('&')}`;
}

/** "/api/landing-windows" -> "landing-windows"; null if the path is not an answerable endpoint. */
export function endpointOf(url: string, spec: KeySpec): string | null {
  const m = /\/api\/([a-z-]+)$/.exec(url);
  return m && spec[m[1]] ? m[1] : null;
}

/** The baked time at or before ``ms`` (static mode snaps the clock to these); the first if none. */
export function snapToBaked(index: AnswersIndex, ms: number): string {
  const times = index.baked_times.map((t) => Date.parse(t)).sort((a, b) => a - b);
  let best = times[0];
  for (const t of times) if (t <= ms) best = t;
  return new Date(best).toISOString().replace(/\.\d{3}Z$/, 'Z');
}
