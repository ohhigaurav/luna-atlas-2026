// Compare view (challenge O1c, C5, C12; PRD compare tray): 2-6 places side by side at one moment
// and over the next days, from POST /api/compare. One row per metric, the leader's cell marked
// (no combined score), each column's own horizon with the Sun and Earth at that moment.
import { useEffect, useState, type ReactNode } from 'react';
import { nextText, type BodyNow, type CompareRow } from '../api/compare';
import { useCompare } from './useCompare';
import { fetchRun, type LimitCheck, type SavedRun } from '../api/plan';
import type { ReferenceSite } from '../data/source';
import { formatLat, formatLon } from '../state/format';
import { spanText } from '../state/siteState';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS } from '../plan/usePlan';
import type { NextLanding } from './nextLanding';
import { missText } from '../state/rules';
import { terrainText } from '../state/terrain';
import { useNextLanding } from './useNextLanding';
import { CloseIcon } from '../ui/Icons';

type Props = {
  places: ReferenceSite[];
  live: boolean;
  clockMs: number;
  onRemove: (id: string) => void;
  onOpen: (s: ReferenceSite) => void;
  /** Moves the date bar (and so this table) to another moment. */
  onJump: (ms: number) => void;
  onClose: () => void;
};

const dayText = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });

/** Height of a body above the local horizon at that azimuth (terrain where available), signed. */
const signed = (x: number) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(1)}°`;
function aboveHorizon(b: BodyNow): { h: number; main: string; sub: string } {
  const h = b.elevation_deg - b.horizon_deg;
  return { h, main: signed(h), sub: `${signed(b.elevation_deg)} over level ground, az ${b.azimuth_deg.toFixed(0)}°` };
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const hours = (h: number, lower: boolean) => {
  const d = Math.floor(h / 24), hh = Math.round(h - d * 24);
  return `${lower ? '≥ ' : ''}${d ? `${d} d ${hh} h` : `${Math.round(h)} h`}`;
};

type Metric = { label: string; hint?: string; leader?: string; cell: (r: CompareRow, days: number) => { main: string; sub?: ReactNode; tone?: string } };

const LIMIT_NAME: Record<string, string> = { darkness: 'Darkness', earth_gap: 'No Earth', joint_outage: 'No Sun and no Earth', sunlit: 'Sunlight' };
const hShort = (h: number) => (h > 72 && h % 24 === 0 ? `${h / 24}\u00a0d` : `${+h.toFixed(1)}\u00a0h`);

/** Which limits of the default profile fail or cannot be confirmed, with the number and the limit. */
function limitsCell(r: CompareRow): { main: string; sub?: ReactNode; tone?: string } {
  if (!r.limits) return { main: r.limits_all_pass ? 'All pass' : 'Some fail', tone: r.limits_all_pass ? 'good' : 'bad' };
  const bad = r.limits.filter((c) => c.status === 'fail'), unsure = r.limits.filter((c) => c.status === 'unknown');
  const line = (c: LimitCheck) => (
    <span key={c.key} className="c-lim">
      {LIMIT_NAME[c.key] ?? c.label} {c.text}{c.limit_h != null ? `, limit ${hShort(c.limit_h)}` : c.limit_pct != null ? `, needs ${Math.round(c.limit_pct)}%` : ''}
      {c.status === 'unknown' ? ', may be longer' : ''}
    </span>
  );
  if (bad.length) return { main: `${bad.length} of ${r.limits.length} fail`, sub: <>{bad.map(line)}{unsure.map(line)}</>, tone: 'bad' };
  if (unsure.length) return { main: 'Not confirmed', sub: <>{unsure.map(line)}</>, tone: 'dim' };
  return { main: 'All pass', tone: 'good' };
}

const METRICS: Metric[] = [
  { label: 'Sun now', hint: 'centre above (+) or behind (−) the hills at its azimuth, panel 2 m', leader: 'highest_sun_now',
    cell: (r) => { const a = aboveHorizon(r.now.sun); return { main: `${r.now.sun.up ? (a.h < 0 ? 'Partly up' : 'Up') : 'Down'} ${a.main}`, sub: a.sub, tone: r.now.sun.up ? 'sun' : 'dim' }; } },
  { label: 'Sunset or sunrise', leader: 'longest_until_sunset',
    cell: (r, d) => ({ main: cap(nextText(r.sun_next, d)), tone: r.sun_next.up ? 'sun' : 'dim' }) },
  { label: 'Earth now', hint: 'centre above (+) or behind (−) the hills, 2 m antenna: line of sight, not a radio link',
    cell: (r) => { const a = aboveHorizon(r.now.earth); return { main: `${r.now.earth.up ? 'In view' : 'Hidden'} ${a.main}`, sub: a.sub, tone: r.now.earth.up ? 'earth' : 'dim' }; } },
  { label: 'Earthset or Earthrise', leader: 'longest_until_earthset',
    cell: (r, d) => ({ main: cap(nextText(r.earth_next, d)), tone: r.earth_next.up ? 'earth' : 'dim' }) },
  { label: 'Sunlight', hint: 'share of the Sun\'s disc in view, averaged over the period (what a panel gets)', leader: 'most_sunlight',
    cell: (r) => (r.period.sun_disc_percent != null
      ? { main: `${r.period.sun_disc_percent.toFixed(0)}%`, sub: `any part of the Sun: ${r.period.sunlit_percent.toFixed(0)}%` }
      : { main: `${r.period.sunlit_percent.toFixed(0)}%`, sub: 'any part of the Sun' }) },
  { label: 'Earth in view', leader: 'most_earth', cell: (r) => ({ main: `${r.period.earth_percent.toFixed(0)}%` }) },
  { label: 'Sunlit and Earth', hint: 'can work and talk', leader: 'most_both', cell: (r) => ({ main: `${r.period.both_percent.toFixed(0)}%` }) },
  { label: 'Longest darkness', leader: 'shortest_darkness',
    cell: (r) => ({ main: hours(r.period.longest_darkness_h, r.period.longest_darkness_lower_bound) }) },
  { label: 'Longest Earth gap', cell: (r) => ({ main: hours(r.period.longest_earth_gap_h, r.period.longest_earth_gap_lower_bound) }) },
  { label: 'Mission limits', hint: 'default profile: longest darkness, longest time without Earth, longest time with neither', cell: limitsCell },
];

function terrainLabel(r: CompareRow): string {
  return terrainText(r.horizon_mode, r.terrain?.finest_resolution_m);
}

/** The column's 360-degree horizon with the Sun and Earth at the compare moment (from the saved run). */
function MiniSky({ row }: { row: CompareRow }) {
  const [run, setRun] = useState<SavedRun | null>(null);
  useEffect(() => {
    const ac = new AbortController();
    fetchRun(`/api/runs/${row.run_id}`, ac.signal).then(setRun, () => {});
    return () => ac.abort();
  }, [row.run_id]);
  const W = 200, H = 64, lo = -2, hi = 10;
  const x = (az: number) => (az / 360) * W, y = (el: number) => H - 10 - ((Math.max(lo, Math.min(hi, el)) - lo) / (hi - lo)) * (H - 16);
  const hz = run?.sites[0]?.horizon_profile ?? [];
  const ground = hz.length ? `M0,${H} ` + hz.map((b) => `L${x(b.azimuth_deg).toFixed(1)},${y(b.elevation_deg ?? 0).toFixed(1)}`).join(' ') + ` L${W},${H} Z` : `M0,${y(0)} L${W},${y(0)} L${W},${H} L0,${H} Z`;
  const s = row.now.sun, e = row.now.earth;
  return (
    <svg className="la-minisky" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Horizon with the Sun at ${s.elevation_deg.toFixed(1)} degrees and Earth at ${e.elevation_deg.toFixed(1)} degrees`}>
      <path d={ground} className="ms-ground" />
      {[0, 90, 180, 270].map((a, i) => <text key={a} x={x(a) + 2} y={9} className="ms-lab">{'NESW'[i]}</text>)}
      {e.elevation_deg > lo - 1 && <circle cx={x(e.azimuth_deg)} cy={y(e.elevation_deg)} r={4.5} className={`ms-earth${e.up ? '' : ' hid'}`} />}
      {s.elevation_deg > lo - 1 && <circle cx={x(s.azimuth_deg)} cy={y(s.elevation_deg)} r={3.5} className={`ms-sun${s.up ? '' : ' hid'}`} />}
      <text x={W - 2} y={H - 2} textAnchor="end" className="ms-lab">{hz.length ? 'horizon: terrain' : 'horizon: flat'}, ×{(((H - 16) / (hi - lo)) / (W / 360)).toFixed(0)} tall</text>
    </svg>
  );
}

function earliest(land: Record<string, NextLanding>): number | null {
  const t = Object.values(land).flatMap((n) => (n.kind === 'window' ? [n.fromMs] : []));
  return t.length ? Math.min(...t) : null;
}

/** One sentence above the table: can any of these places land on this date, and if not, when is the soonest chance. */
const daysText = (h: number) => `${(h / 24).toFixed(1)} days`;

function LandingSummary({ places, land, atMs, mission, onJump, onMission }: {
  places: ReferenceSite[]; land: Record<string, NextLanding>; atMs: number; mission: number;
  onJump: (ms: number) => void; onMission: (d: number) => void;
}) {
  const all = places.map((p) => ({ p, n: land[p.site_id] ?? ({ kind: 'pending' } as NextLanding) }));
  const pending = all.filter((x) => x.n.kind === 'pending').length;
  const open = all.filter((x) => x.n.kind === 'window' && x.n.openAt);
  const later = all.flatMap((x) => (x.n.kind === 'window' && !x.n.openAt ? [{ p: x.p, n: x.n }] : [])).sort((a, b) => a.n.fromMs - b.n.fromMs);
  const names = (xs: { p: ReferenceSite }[]) => xs.map((x) => x.p.name).join(', ');
  let body;
  if (open.length) {
    body = <p><b className="good-c">You can land on {dayText(atMs)} at {names(open)}.</b>{pending ? ` Still checking ${pending}.` : ''}</p>;
  } else if (later.length) {
    const s = later[0];
    body = (
      <>
        <p>
          <b>{pending ? 'So far, none of these places can land' : 'None of these places can land'} on {dayText(atMs)}.</b>{' '}
          Soonest chance: <b>{s.p.name}</b> from {dayText(s.n.fromMs)}, in {spanText(s.n.fromMs - atMs)}.
          {pending ? ` Still checking ${pending}.` : ''}
        </p>
        <button type="button" className="la-btn primary" onClick={() => onJump(s.n.bestMs)}>Compare on {dayText(s.n.bestMs)}</button>
      </>
    );
  } else if (pending) {
    body = <p>Looking for the next landing window at each place: {places.length - pending} of {places.length} done.</p>;
  } else {
    // Nothing fits: say how far the search went, the longest sunlight any place gets (what a
    // shorter mission could use) and the last window before this date, each one click away.
    const nones = all.flatMap((x) => (x.n.kind === 'none' ? [{ p: x.p, n: x.n }] : []));
    const through = Math.max(...nones.map((x) => x.n.throughMs));
    const longest = nones.filter((x) => x.n.longest).sort((a, b) => b.n.longest!.hours - a.n.longest!.hours)[0];
    const earlier = nones.filter((x) => x.n.earlier).sort((a, b) => b.n.earlier!.fromMs - a.n.earlier!.fromMs)[0];
    const fits = longest ? Math.floor(longest.n.longest!.hours / 24) : 0;
    const miss = nones.filter((x) => x.n.miss).sort((a, b) => a.n.miss!.rules.length - b.n.miss!.rules.length || a.n.miss!.atMs - b.n.miss!.atMs)[0];
    body = (
      <>
        <p>
          <b>No place here gets a {mission}-day landing window from {dayText(atMs)} to {dayText(through)}.</b>
          {longest && <> The longest sunlight is at <b>{longest.p.name}</b>: {longest.n.longest!.lowerBound ? 'at least ' : ''}{daysText(longest.n.longest!.hours)} from {dayText(longest.n.longest!.fromMs)}.</>}
          {miss && <> Closest try: <b>{miss.p.name}</b> on {dayText(miss.n.miss!.atMs)}, which fails on {missText(miss.n.miss!)}.</>}
          {earlier && <> The last chance before this date was <b>{earlier.p.name}</b> on {dayText(earlier.n.earlier!.fromMs)}.</>}
          {!longest && !earlier && ' The Sun stays below the hills at every place for the whole search.'}
        </p>
        {fits >= 1 && fits < mission && <button type="button" className="la-btn primary" onClick={() => onMission(fits)}>Try a {fits}-day mission</button>}
        {earlier && <button type="button" className="la-btn" onClick={() => onJump(earlier.n.earlier!.bestMs)}>Compare on {dayText(earlier.n.earlier!.bestMs)}</button>}
      </>
    );
  }
  return <div className="la-cmp-land" role="status">{body}</div>;
}

export function CompareView({ places, live, clockMs, onRemove, onOpen, onJump, onClose }: Props) {
  const [days, setDays] = useState(30);
  const st = useCompare(places.map((p) => p.site_id), clockMs, days, live, 0);
  const [mission, setMission] = useState(DEFAULT_MISSION_DAYS);
  const land = useNextLanding(places.map((p) => p.site_id), clockMs, mission, live);
  const landPending = Object.values(land).some((x) => x.kind === 'pending');
  const [, tick] = useState(0);
  useEffect(() => {
    if (st.s !== 'loading' && !landPending) return;
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, [st.s, landPending]);

  const r = st.s === 'ready' ? st.r : null;
  const shown = r ?? (st.s === 'loading' ? st.last : null);
  const byKey = (row: CompareRow) => places.find((p) => p.site_id === row.site.site_id || (p.latitude_deg.toFixed(3) === row.site.latitude_deg.toFixed(3) && p.longitude_deg.toFixed(3) === row.site.longitude_deg.toFixed(3)));

  return (
    <section className="la-sheet compare" aria-label="Compare places">
      <div className="la-sheet-head">
        <h2>Compare {places.length} {places.length === 1 ? 'place' : 'places'}</h2>
        <span className="la-cap">For the date in the bar at the top</span>
        <label className="la-cmpdate">
          <span className="la-cap">Next</span>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[14, 30, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
        </label>
        <label className="la-cmpdate">
          <span className="la-cap">Mission</span>
          <select value={mission} onChange={(e) => setMission(Number(e.target.value))}>
            {[...new Set([1, 2, 3, 5, 7, 10, 14, mission])].sort((a, b) => a - b).map((d) => <option key={d} value={d}>{d} {d === 1 ? 'day' : 'days'}{d === DEFAULT_MISSION_DAYS ? ' (default)' : ''}</option>)}
          </select>
        </label>
        <span className="la-spacer" />
        <button type="button" className="la-x" aria-label="Close compare (Esc)" onClick={onClose}><CloseIcon /></button>
      </div>

      {!live && <div className="la-sheet-main"><p className="la-err">Comparing needs the live backend (each place is a full terrain analysis).</p></div>}
      {live && st.s === 'loading' && (
        <div className="la-cmp-status" role="status">
          Checking {places.length} {places.length === 1 ? 'place' : 'places'}, one at a time: {Math.round((performance.now() - st.since) / 1000)} s.
          New places or dates take about 10–20 s each the first time; repeats are instant.
          <div className="la-bar" />
        </div>
      )}
      {live && st.s === 'error' && <div className="la-cmp-status"><p className="la-err" role="alert">{st.m}</p></div>}

      {live && places.length > 0 && <LandingSummary places={places} land={land} atMs={clockMs} mission={mission} onJump={onJump} onMission={setMission} />}

      {live && shown && (
        <div className={`la-cmp${st.s === 'loading' ? ' stale' : ''}`} style={{ gridTemplateColumns: `150px repeat(${shown.rows.length}, minmax(132px, 1fr))` }}>
          <div className="c-corner"><span className="la-cap">{new Date(shown.at_utc).toISOString().slice(0, 16).replace('T', ' ')} UTC, then {shown.days} days</span></div>
          {shown.rows.map((row) => {
            const p = byKey(row);
            return (
              <div key={row.key} className="c-head">
                <button type="button" className="c-name" onClick={() => p && onOpen(p)} title="Open this place">{row.site.name}</button>
                <span className="c-co">{formatLat(row.site.latitude_deg)} {formatLon(row.site.longitude_deg)}</span>
                <span className={`la-tag${row.horizon_mode === 'terrain' ? '' : ' warn'}`}>{terrainLabel(row)}</span>
                {p && <button type="button" className="c-rm" aria-label={`Remove ${row.site.name}`} onClick={() => onRemove(p.site_id)}>×</button>}
              </div>
            );
          })}
          <div className="c-label">Horizon now<small>terrain, Sun ● Earth ●</small></div>
          {shown.rows.map((row) => <div key={row.key} className="c-cell sky"><MiniSky row={row} /></div>)}
          <div className="c-label">Next landing window<small>{mission}-day mission in sunlight, Earth in view, Sun ≤ {DEFAULT_MAX_SUN_DEG}° at touchdown</small></div>
          {shown.rows.map((row) => {
            const p = byKey(row);
            const n: NextLanding = p ? land[p.site_id] ?? { kind: 'pending' } : { kind: 'error' };
            const lead = shown.rows.length > 1 && n.kind === 'window' && earliest(land) === n.fromMs;
            return (
              <div key={row.key} role="cell" className={`c-cell${lead ? ' lead' : ''}`}>
                {n.kind === 'pending' && <><b className="dim-c">Checking…</b><small>about 10–60 s the first time</small></>}
                {n.kind === 'error' && <b className="dim-c">Not checked</b>}
                {n.kind === 'none' && (
                  <>
                    <b className="dim-c">None</b>
                    <small>through {dayText(n.throughMs)}</small>
                    {n.miss && <small>closest {dayText(n.miss.atMs)}: {missText(n.miss)}</small>}
                    {n.longest
                      ? <small>longest sunlight {n.longest.lowerBound ? '≥ ' : ''}{daysText(n.longest.hours)}, from {dayText(n.longest.fromMs)}</small>
                      : <small>no sunlit stretch after this date</small>}
                    {n.earlier && <button type="button" className="c-go" onClick={() => onJump(n.earlier!.bestMs)}>Earlier: {dayText(n.earlier.bestMs)}</button>}
                  </>
                )}
                {n.kind === 'window' && n.openAt && <><b className="good-c">Open now</b><small>until {dayText(n.untilMs)}</small></>}
                {n.kind === 'window' && !n.openAt && (
                  <>
                    <b>{dayText(n.fromMs)}</b>
                    <small>in {spanText(n.fromMs - clockMs)}{n.sunDeg !== undefined ? `, Sun ${n.sunDeg.toFixed(1)}° at best` : ''}</small>
                    <button type="button" className="c-go" onClick={() => onJump(n.bestMs)}>Go to {dayText(n.bestMs)}</button>
                  </>
                )}
                {lead && <span className="c-best">soonest</span>}
              </div>
            );
          })}
          {METRICS.map((m) => (
            <div key={m.label} className="c-row" role="row">
              <div className="c-label" role="rowheader">{m.label}{m.hint && <small>{m.hint}</small>}</div>
              {shown.rows.map((row) => {
                const c = m.cell(row, shown.days);
                const lead = m.leader && shown.rows.length > 1 && (shown.leaders[m.leader] ?? []).includes(row.key);
                return (
                  <div key={row.key} role="cell" className={`c-cell${lead ? ' lead' : ''}`}>
                    <b className={c.tone ? `${c.tone}-c` : undefined}>{c.main}</b>
                    {c.sub && <small>{c.sub}</small>}
                    {lead && <span className="c-best">best</span>}
                  </div>
                );
              })}
            </div>
          ))}
          <div className="c-label">Check it</div>
          {shown.rows.map((row) => (
            <div key={row.key} className="c-cell small">
              {row.verify?.sun?.horizons_url && <a href={row.verify.sun.horizons_url} target="_blank" rel="noopener noreferrer">Verify with NASA JPL ↗</a>}
              {row.caveats.length > 0 && (
                <details><summary>Read {row.caveats.length} {row.caveats.length === 1 ? 'note' : 'notes'}</summary>
                  <ul>{row.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </details>
              )}
            </div>
          ))}
          <p className="c-rules">
            "Best" marks the leader in each row; there is no combined score. {shown.rules.sun_up}. {shown.rules.earth_up}. "≥" means {shown.rules.lower_bound}.
          </p>
        </div>
      )}
    </section>
  );
}
