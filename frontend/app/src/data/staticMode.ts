// Static judge site: every API question goes to the precomputed answers baked by
// tools/bake_answers.py (docs/static_bundle.md → "Frontend: one change in post()"). Times snap to
// the baked times, compare is merged from one stored answer per place, and anything not baked says
// it needs the live server. Never extrapolates or interpolates an answer.
import type { CompareResult, CompareRow } from '../api/compare';
import { endpointOf, makeKey, snapToBaked, type AnswersIndex } from './staticAnswers';

let idx: AnswersIndex | null = null;
let base = '/';
let nowMs: number | null = null;

export class StaticMiss extends Error {
  status = 404;
}

/** Switch the API layer to the baked answers. The app's "now" becomes the first baked time. */
export function enableStaticAnswers(index: AnswersIndex, baseUrl: string) {
  idx = index; base = baseUrl;
  nowMs = Date.parse(snapToBaked(index, -Infinity));
}
export const staticIndex = () => idx;

/** "Now" for questions: the wall clock live; the first baked time on the static site. */
export function appNow(): number {
  return nowMs ?? Date.now();
}

const TIME_FIELDS = ['search_start_utc', 'start_utc', 'at_utc'];
const needsServer = (i: AnswersIndex) =>
  `Precomputed for ${i.baked_times.map((t) => t.slice(0, 10)).join(', ')}; this question needs the live server.`;

async function file<T>(rel: string): Promise<T> {
  const r = await fetch(`${base}data/${rel}`);
  if (!r.ok) throw new StaticMiss(`precomputed answer missing (${r.status})`);
  return (await r.json()) as T;
}

/** Same rules as lunar_core.compare.leaders: best per metric, ties listed, up-now metrics among places that are up. */
export function compareLeaders(rows: CompareRow[]): Record<string, string[]> {
  const best = (vals: Array<[string, number]>, higher = true) => {
    if (!vals.length) return [];
    const t = higher ? Math.max(...vals.map((v) => v[1])) : Math.min(...vals.map((v) => v[1]));
    return vals.filter((v) => Math.abs(v[1] - t) < 1e-9).map((v) => v[0]);
  };
  const all = (f: (r: CompareRow) => number) => rows.map((r): [string, number] => [r.key, f(r)]);
  return {
    most_sunlight: best(all((r) => r.period.sun_disc_percent ?? r.period.sunlit_percent)),
    most_earth: best(all((r) => r.period.earth_percent)),
    most_both: best(all((r) => r.period.both_percent)),
    shortest_darkness: best(all((r) => r.period.longest_darkness_h), false),
    longest_until_sunset: best(rows.filter((r) => r.sun_next.up).map((r): [string, number] => [r.key, r.sun_next.in_h])),
    longest_until_earthset: best(rows.filter((r) => r.earth_next.up).map((r): [string, number] => [r.key, r.earth_next.in_h])),
    highest_sun_now: best(rows.filter((r) => r.now.sun.up).map((r): [string, number] => [r.key, r.now.sun.elevation_deg - (r.now.sun.horizon_deg ?? 0)])),
  };
}

export async function staticPost<T>(url: string, body: Record<string, unknown>): Promise<T> {
  const i = idx!;
  const ep = endpointOf(url, i.key_spec);
  if (!ep) throw new StaticMiss('This needs the live server (not precomputed on the static site).');
  const b: Record<string, unknown> = { ...body };
  for (const f of TIME_FIELDS) if (typeof b[f] === 'string') b[f] = snapToBaked(i, Date.parse(b[f] as string));
  const one = async <R>(bb: Record<string, unknown>): Promise<R> => {
    const f = i.answers[makeKey(i.key_spec, ep, bb)];
    if (!f) throw new StaticMiss(needsServer(i));
    return file<R>(f);
  };
  if (ep !== 'compare') return one<T>(b);
  // Compare is stored one place at a time: ask each and merge.
  const { places, ...rest } = b as { places: Record<string, unknown>[] };
  const parts = await Promise.all(places.map((p) => one<CompareResult>({ ...rest, ...p })));
  const rows = parts.map((x) => x.rows[0]);
  return { ...parts[0], rows, leaders: compareLeaders(rows) } as unknown as T;
}

export async function staticRun<T>(runUrl: string): Promise<T> {
  const id = /\/api\/runs\/([^/?]+)/.exec(runUrl)?.[1];
  const f = id ? idx!.runs[id] : undefined;
  if (!f) throw new StaticMiss('This saved run is not in the precomputed bundle.');
  return file<T>(f);
}
