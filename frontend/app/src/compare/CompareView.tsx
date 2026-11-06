// Compare view (challenge O1c, C5, C12; PRD compare tray): 2-6 places side by side at one moment
// and over the next days, from POST /api/compare. One row per metric, the leader's cell marked
// (no combined score), each column's own horizon with the Sun and Earth at that moment.
import { useEffect, useState } from 'react';
import { nextText, type CompareRow } from '../api/compare';
import { useCompare } from './useCompare';
import { fetchRun, type SavedRun } from '../api/plan';
import type { ReferenceSite } from '../data/source';
import { formatLat, formatLon } from '../state/format';
import { CloseIcon } from '../ui/Icons';

type Props = {
  places: ReferenceSite[];
  live: boolean;
  clockMs: number;
  onRemove: (id: string) => void;
  onOpen: (s: ReferenceSite) => void;
  onClose: () => void;
};

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const hours = (h: number, lower: boolean) => {
  const d = Math.floor(h / 24), hh = Math.round(h - d * 24);
  return `${lower ? '≥ ' : ''}${d ? `${d} d ${hh} h` : `${Math.round(h)} h`}`;
};

type Metric = { label: string; hint?: string; leader?: string; cell: (r: CompareRow, days: number) => { main: string; sub?: string; tone?: string } };

const METRICS: Metric[] = [
  { label: 'Sun now', hint: 'height above the local horizon (terrain), panel 2 m', leader: 'highest_sun_now',
    cell: (r) => ({ main: `${r.now.sun.elevation_deg.toFixed(1)}°`, sub: `${r.now.sun.up ? 'up' : 'below the horizon'}, az ${r.now.sun.azimuth_deg.toFixed(0)}°`, tone: r.now.sun.up ? 'sun' : 'dim' }) },
  { label: 'Sunset or sunrise', leader: 'longest_until_sunset',
    cell: (r, d) => ({ main: cap(nextText(r.sun_next, d)), tone: r.sun_next.up ? 'sun' : 'dim' }) },
  { label: 'Earth now', hint: 'centre above the horizon from a 2 m antenna: line of sight, not a radio link',
    cell: (r) => ({ main: `${r.now.earth.elevation_deg.toFixed(1)}°`, sub: `${r.now.earth.up ? 'in view' : 'hidden'}, az ${r.now.earth.azimuth_deg.toFixed(0)}°`, tone: r.now.earth.up ? 'earth' : 'dim' }) },
  { label: 'Earthset or Earthrise', leader: 'longest_until_earthset',
    cell: (r, d) => ({ main: cap(nextText(r.earth_next, d)), tone: r.earth_next.up ? 'earth' : 'dim' }) },
  { label: 'Sunlit', hint: 'share of the period', leader: 'most_sunlight', cell: (r) => ({ main: `${r.period.sunlit_percent.toFixed(0)}%` }) },
  { label: 'Earth in view', leader: 'most_earth', cell: (r) => ({ main: `${r.period.earth_percent.toFixed(0)}%` }) },
  { label: 'Sunlit and Earth', hint: 'can work and talk', leader: 'most_both', cell: (r) => ({ main: `${r.period.both_percent.toFixed(0)}%` }) },
  { label: 'Longest darkness', leader: 'shortest_darkness',
    cell: (r) => ({ main: hours(r.period.longest_darkness_h, r.period.longest_darkness_lower_bound) }) },
  { label: 'Longest Earth gap', cell: (r) => ({ main: hours(r.period.longest_earth_gap_h, r.period.longest_earth_gap_lower_bound) }) },
  { label: 'Mission limits', hint: 'default profile', cell: (r) => ({ main: r.limits_all_pass ? 'all pass' : 'some fail', tone: r.limits_all_pass ? 'good' : 'bad' }) },
];

function terrainLabel(r: CompareRow): string {
  if (r.horizon_mode !== 'terrain') return 'flat horizon';
  const m = r.terrain?.finest_resolution_m;
  return m ? `${m >= 100 ? Math.round(m) : +m.toFixed(1)} m terrain` : 'terrain';
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

export function CompareView({ places, live, clockMs, onRemove, onOpen, onClose }: Props) {
  const [days, setDays] = useState(30);
  const st = useCompare(places.map((p) => p.site_id), clockMs, days, live, 0);
  const [, tick] = useState(0);
  useEffect(() => {
    if (st.s !== 'loading') return;
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, [st.s]);

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
                <details><summary>{row.caveats.length} {row.caveats.length === 1 ? 'note' : 'notes'}</summary>
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
