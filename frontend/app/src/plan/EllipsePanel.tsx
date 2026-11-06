// Landing-ellipse risk (PRD F28, challenge C8: why small location changes have large effects).
// Landers come down somewhere inside an ellipse, not on the target. POST /api/landing-ellipse runs
// the full production analysis at ~45 points filling the ellipse; this draws them in local
// east/north metres, coloured by sunlit share, with the best and worst spots marked. A spread over
// evenly spaced points, not a landing probability (the API says so; so does this panel).
import { useEffect, useMemo, useState } from 'react';
import { isoZ, post } from '../api/plan';

export type EllipsePoint = {
  east_m: number; north_m: number; latitude_deg: number; longitude_deg: number; status: string;
  sunlit_percent: number | null; dte_clear_percent: number | null; both_percent: number | null;
  longest_darkness_h: number | null; ground_elevation_m: number | null;
};
type Where = { east_m: number; north_m: number; sunlit_percent: number; dte_clear_percent: number; both_percent: number };
export type EllipseResult = {
  kind: 'landing_ellipse';
  ellipse: { semi_major_m: number; semi_minor_m: number; orientation_deg: number; spacing_m: number; point_count: number };
  risk: {
    points_ok: number;
    sunlit_percent?: { worst: number; p10: number; median: number; p90: number; best: number };
    earth_percent?: { worst: number; best: number };
    dark_trap_share?: number;
    target?: Where | null; best_point?: Where; worst_point?: Where;
    chips?: string[];
  };
  points: EllipsePoint[];
  points_unavailable: number;
  interpretation: string;
  compute_seconds: number;
  cache_hit: boolean;
};

const SIZES = [100, 250, 500, 1000];
const STRETCH: [string, number][] = [['round', 1], ['2 : 1', 0.5], ['3 : 1', 1 / 3]];

/** Sunlit share to colour: red (dark trap) through amber to green. The number is always printed too. */
export function sunColour(pct: number): string {
  const stops: [number, number[]][] = [[0, [239, 107, 91]], [50, [242, 184, 75]], [100, [94, 211, 148]]];
  const p = Math.max(0, Math.min(100, pct));
  const [a, b] = p <= 50 ? [stops[0], stops[1]] : [stops[1], stops[2]];
  const f = (p - a[0]) / (b[0] - a[0]);
  const c = a[1].map((v, i) => Math.round(v + (b[1][i] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

function Plot({ r }: { r: EllipseResult }) {
  const S = 320, pad = 26;
  const a = r.ellipse.semi_major_m, b = r.ellipse.semi_minor_m, th = r.ellipse.orientation_deg;
  const half = a * 1.12, k = (S / 2 - pad) / half;
  const X = (e: number) => S / 2 + e * k, Y = (n: number) => S / 2 - n * k;
  const cell = Math.max(3, r.ellipse.spacing_m * k * 0.94);
  const nice = [10, 20, 25, 50, 100, 200, 250, 500, 1000].filter((v) => v * k <= S / 3).pop() ?? 10;
  const best = r.risk.best_point, worst = r.risk.worst_point;
  const lab = (p: Where | undefined, text: string, cls: string) => p && (
    <g className={`el-mark ${cls}`}>
      <circle cx={X(p.east_m)} cy={Y(p.north_m)} r={cell / 2 + 3} />
      <text x={X(p.east_m) + cell / 2 + 6} y={Y(p.north_m) + 4} className="el-txt">{text} {p.sunlit_percent.toFixed(0)}%</text>
    </g>
  );
  return (
    <svg className="la-elplot" viewBox={`0 0 ${S} ${S}`} role="img"
      aria-label={`Ellipse ${a} by ${b} metres: sunlight ranges from ${r.risk.sunlit_percent?.worst.toFixed(0)}% to ${r.risk.sunlit_percent?.best.toFixed(0)}% over ${r.risk.points_ok} points`}>
      <ellipse cx={S / 2} cy={S / 2} rx={b * k} ry={a * k} transform={`rotate(${th} ${S / 2} ${S / 2})`} className="el-outline" />
      {r.points.map((p, i) => (
        <rect key={i} x={X(p.east_m) - cell / 2} y={Y(p.north_m) - cell / 2} width={cell} height={cell}
          className={p.status === 'ok' ? 'el-cell' : 'el-cell na'} style={p.status === 'ok' && p.sunlit_percent !== null ? { fill: sunColour(p.sunlit_percent) } : undefined}>
          <title>{p.status === 'ok' ? `${p.east_m.toFixed(0)} m E, ${p.north_m.toFixed(0)} m N: sunlit ${p.sunlit_percent?.toFixed(0)}%, Earth ${p.dte_clear_percent?.toFixed(0)}%, both ${p.both_percent?.toFixed(0)}%` : 'no answer here (terrain unavailable)'}</title>
        </rect>
      ))}
      <path d={`M${S / 2 - 7},${S / 2} H${S / 2 + 7} M${S / 2},${S / 2 - 7} V${S / 2 + 7}`} className="el-target" />
      {lab(worst, 'worst', 'worst')}
      {lab(best, 'best', 'best')}
      <g className="el-scale" transform={`translate(${pad}, ${S - 12})`}>
        <path d={`M0,-5 V0 H${nice * k} V-5`} />
        <text x={nice * k + 5} y={0}>{nice} m</text>
      </g>
      <text x={S - 12} y={20} textAnchor="middle" className="el-n">N</text>
      <path d={`M${S - 12},26 V40 M${S - 16},30 L${S - 12},26 L${S - 8},30`} className="el-scale" />
    </svg>
  );
}

export function EllipsePanel({ siteId, startMs }: { siteId: string; startMs: number }) {
  const [open, setOpen] = useState(false);
  const [size, setSize] = useState(250);
  const [ratio, setRatio] = useState(1);
  const [rot, setRot] = useState(0);
  const [st, setSt] = useState<{ s: 'idle' } | { s: 'loading'; since: number } | { s: 'ready'; r: EllipseResult } | { s: 'error'; m: string }>({ s: 'idle' });
  const [, tick] = useState(0);
  const body = useMemo(() => ({
    site_id: siteId, start_utc: isoZ(startMs), days: 14, semi_major_m: size,
    semi_minor_m: Math.max(25, Math.round(size * ratio)), orientation_deg: ratio === 1 ? 0 : rot, panel_height_m: 2,
  }), [siteId, startMs, size, ratio, rot]);
  const key = JSON.stringify(body);
  const [asked, setAsked] = useState<string | null>(null);
  useEffect(() => { if (asked !== key) setSt({ s: 'idle' }); }, [key, asked]);
  useEffect(() => {
    if (st.s !== 'loading') return;
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, [st.s]);

  const run = () => {
    setAsked(key);
    setSt({ s: 'loading', since: performance.now() });
    post<EllipseResult>('/api/landing-ellipse', body).then((r) => setSt({ s: 'ready', r }), (e: Error) => setSt({ s: 'error', m: e.message }));
  };

  if (!open) {
    return (
      <section className="la-sec">
        <button type="button" className="la-btn" onClick={() => setOpen(true)}>Where could you actually come down? Landing ellipse</button>
      </section>
    );
  }
  const r = st.s === 'ready' ? st.r : null;
  return (
    <section className="la-sec la-ellipse" aria-label="Landing ellipse">
      <span className="la-cap">Landing ellipse, 14 days from {isoZ(startMs).slice(0, 16).replace('T', ' ')} UTC</span>
      <p className="la-fine" style={{ margin: 0 }}>
        Landers come down somewhere inside an ellipse, not on the target. IM-2 stopped about 250 m from its target in a crater and could not recharge.
      </p>
      <div className="la-seg" role="group" aria-label="Ellipse size (semi-major axis)">
        {SIZES.map((v) => <button key={v} type="button" aria-pressed={size === v} className={size === v ? 'on' : undefined} onClick={() => setSize(v)}>{v >= 1000 ? `${v / 1000} km` : `${v} m`}</button>)}
      </div>
      <div className="la-seg" role="group" aria-label="Stretch">
        {STRETCH.map(([l, v]) => <button key={l} type="button" aria-pressed={ratio === v} className={ratio === v ? 'on' : undefined} onClick={() => setRatio(v)}>{l}</button>)}
      </div>
      {ratio !== 1 && (
        <label className="la-elrot">
          <span className="la-cap">Long axis bearing {rot}°</span>
          <input type="range" min={0} max={165} step={15} value={rot} onChange={(e) => setRot(Number(e.target.value))} />
        </label>
      )}
      {st.s !== 'ready' && st.s !== 'loading' && (
        <button type="button" className="la-btn primary" onClick={run}>Check this ellipse</button>
      )}
      {st.s === 'loading' && (
        <div role="status" className="la-fine">
          Running the full analysis at about 45 points inside the ellipse: {Math.round((performance.now() - st.since) / 1000)} s.
          The first time takes about 2–4 minutes; the same ellipse again is instant.
          <div className="la-bar" />
        </div>
      )}
      {st.s === 'error' && <p className="la-err" role="alert">{st.m}</p>}
      {r && (
        <>
          {r.risk.points_ok > 0 ? (
            <>
              <div className="la-chips">{(r.risk.chips ?? []).map((c) => <span key={c} className="la-tag">{c}</span>)}</div>
              <Plot r={r} />
              <div className="la-elkey" aria-hidden="true"><span>0%</span><i /><span>100% sunlit</span><span className="la-dim">+ target</span></div>
              <p className="la-fine" style={{ margin: 0 }}>
                {r.risk.target && <>On the target itself: sunlit {r.risk.target.sunlit_percent.toFixed(0)}%. </>}
                Earth in view {r.risk.earth_percent?.worst.toFixed(0)}–{r.risk.earth_percent?.best.toFixed(0)}% across the ellipse.
                {' '}{r.risk.points_ok} of {r.points.length} points answered{r.points_unavailable ? `, ${r.points_unavailable} without terrain` : ''}; {r.ellipse.spacing_m.toFixed(0)} m apart.
                {' '}{r.interpretation}
              </p>
            </>
          ) : <p className="la-err">No point in this ellipse could be analysed (terrain unavailable).</p>}
        </>
      )}
    </section>
  );
}
