// Landing-ellipse risk (PRD F28, challenge C8: why small location changes have large effects).
// Landers come down somewhere inside an ellipse, not on the target. POST /api/landing-ellipse runs
// the full production analysis at ~45 points filling the ellipse; this draws them in local
// east/north metres, coloured by sunlit share, with the best and worst spots marked. A spread over
// evenly spaced points, not a landing probability (the API says so; so does this panel).
import { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, getApi, isoZ, post } from '../api/plan';
import { staticIndex } from '../data/staticMode';

/** POST /api/landing-ellipse/jobs (backend 0.7.46): an ellipse takes 4-5 min, so it runs as a polled job. */
type Job = { job_id: string; status: 'queued' | 'running' | 'done' | 'error'; done: number; total: number;
  queued_s: number; elapsed_s: number; error?: string | null; result?: EllipseResult };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export type EllipsePoint = {
  east_m: number; north_m: number; latitude_deg: number; longitude_deg: number; status: string;
  sunlit_percent: number | null; dte_clear_percent: number | null; both_percent: number | null;
  longest_darkness_h: number | null; ground_elevation_m: number | null;
  /** Slope of the 5 m terrain (schema 1.1, 7 Nov); null where no 5 m tile covers the point. */
  slope_deg?: number | null; slope_err_deg?: number | null; slope_verdict?: 'within' | 'over' | 'uncertain' | null;
};
export type SlopeBlock = {
  status: 'ok' | 'not_available' | string;
  reason?: string;
  label?: string;
  limit_deg?: number;
  limit_note?: string;
  area?: { slope_deg?: { median: number; p90: number; p99: number; max: number }; share_within_limit?: number;
    cdf?: { step_deg: number; max_deg: number; share_at_or_below: number[] } };
  overlay?: { max_slope_deg: (number | null)[][]; cell_m: number; first_cell_centre_east_m: number; first_cell_centre_north_m: number };
  chips?: string[];
  best_sunlit_within_limit?: { east_m: number; north_m: number; sunlit_percent: number; dte_clear_percent: number; slope_deg: number } | null;
  validation?: { status: string; summary?: string; evidence?: string };
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
  slope?: SlopeBlock;
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

type SlopeView = { limit: number; colour: boolean; best: Where | null };
const REPO_BLOB = 'https://github.com/ohhigaurav/luna-atlas-2026/blob/main/';

/** Within / uncertain / over a slope limit, using the error layer when there is one. */
export function slopeVerdict(slope: number, err: number | null | undefined, limit: number): 'within' | 'uncertain' | 'over' {
  const e = err ?? 0;
  if (slope + e <= limit) return 'within';
  if (slope - e > limit) return 'over';
  return 'uncertain';
}
/** Share of the ellipse at or below the limit, from the API's CDF (steps of step_deg). */
export function shareAtOrBelow(cdf: { step_deg: number; share_at_or_below: number[] }, limit: number): number {
  const i = Math.min(cdf.share_at_or_below.length - 1, Math.max(0, Math.floor(limit / cdf.step_deg + 1e-9)));
  return cdf.share_at_or_below[i];
}
/** The sunniest answered point no steeper than the limit (client-side, for any limit). */
export function bestWithin(points: EllipsePoint[], limit: number): Where | null {
  let best: EllipsePoint | null = null;
  for (const p of points) {
    if (p.status !== 'ok' || p.sunlit_percent === null || p.slope_deg == null || p.slope_deg > limit) continue;
    if (!best || p.sunlit_percent > (best.sunlit_percent ?? -1)) best = p;
  }
  return best && { east_m: best.east_m, north_m: best.north_m, sunlit_percent: best.sunlit_percent!, dte_clear_percent: best.dte_clear_percent ?? 0, both_percent: best.both_percent ?? 0 };
}
const SLOPE_FILL = { within: 'rgb(94,211,148)', uncertain: 'rgb(242,184,75)', over: 'rgb(239,107,91)' };

function Plot({ r, sv }: { r: EllipseResult; sv: SlopeView | null }) {
  const S = 320, pad = 26;
  const a = r.ellipse.semi_major_m, b = r.ellipse.semi_minor_m, th = r.ellipse.orientation_deg;
  const half = a * 1.12, k = (S / 2 - pad) / half;
  const X = (e: number) => S / 2 + e * k, Y = (n: number) => S / 2 - n * k;
  const cell = Math.max(3, r.ellipse.spacing_m * k * 0.94);
  const nice = [10, 20, 25, 50, 100, 200, 250, 500, 1000].filter((v) => v * k <= S / 3).pop() ?? 10;
  const best = r.risk.best_point, worst = r.risk.worst_point;
  const ov = sv && r.slope?.overlay;
  const flat = sv?.best && best && (sv.best.east_m !== best.east_m || sv.best.north_m !== best.north_m) ? sv.best : null;
  const lab = (p: Where | undefined, text: string, cls: string) => p && (
    <g className={`el-mark ${cls}`}>
      <circle cx={X(p.east_m)} cy={Y(p.north_m)} r={cell / 2 + 3} />
      <text x={X(p.east_m) + cell / 2 + 6} y={Y(p.north_m) + 4} className="el-txt">{text} {p.sunlit_percent.toFixed(0)}%</text>
    </g>
  );
  return (
    <svg className="la-elplot" viewBox={`0 0 ${S} ${S}`} role="img"
      aria-label={`Ellipse ${a} by ${b} metres: sunlight ranges from ${r.risk.sunlit_percent?.worst.toFixed(0)}% to ${r.risk.sunlit_percent?.best.toFixed(0)}% over ${r.risk.points_ok} points`}>
      {ov && sv?.colour && ov.max_slope_deg.map((row, ri) => row.map((v, ci) => v === null ? null : (
        <rect key={`o${ri}-${ci}`} className="el-ov" x={X(ov.first_cell_centre_east_m + ci * ov.cell_m) - (ov.cell_m * k) / 2}
          y={Y(ov.first_cell_centre_north_m - ri * ov.cell_m) - (ov.cell_m * k) / 2} width={ov.cell_m * k + 0.5} height={ov.cell_m * k + 0.5}
          style={{ opacity: Math.min(0.55, (v / Math.max(sv.limit * 2, 1)) * 0.55) }} />
      )))}
      <ellipse cx={S / 2} cy={S / 2} rx={b * k} ry={a * k} transform={`rotate(${th} ${S / 2} ${S / 2})`} className="el-outline" />
      {r.points.map((p, i) => {
        const v = sv && p.slope_deg != null ? slopeVerdict(p.slope_deg, p.slope_err_deg, sv.limit) : null;
        const fill = sv?.colour ? (v ? SLOPE_FILL[v] : undefined) : p.status === 'ok' && p.sunlit_percent !== null ? sunColour(p.sunlit_percent) : undefined;
        return (
          <rect key={i} x={X(p.east_m) - cell / 2} y={Y(p.north_m) - cell / 2} width={cell} height={cell}
            className={`${p.status === 'ok' ? 'el-cell' : 'el-cell na'}${sv?.colour && v === 'over' ? ' over' : ''}`} style={fill ? { fill } : undefined}>
            <title>{p.status === 'ok' ? `${p.east_m.toFixed(0)} m E, ${p.north_m.toFixed(0)} m N: sunlit ${p.sunlit_percent?.toFixed(0)}%, Earth ${p.dte_clear_percent?.toFixed(0)}%, both ${p.both_percent?.toFixed(0)}%${p.slope_deg != null ? `, slope ${p.slope_deg.toFixed(1)}°${p.slope_err_deg != null ? ` ± ${p.slope_err_deg.toFixed(1)}°` : ''}${v ? ` (${v} ${sv!.limit}°)` : ''}` : ''}` : 'no answer here (terrain unavailable)'}</title>
          </rect>
        );
      })}
      <path d={`M${S / 2 - 7},${S / 2} H${S / 2 + 7} M${S / 2},${S / 2 - 7} V${S / 2 + 7}`} className="el-target" />
      {lab(worst, 'worst', 'worst')}
      {lab(best, 'best', 'best')}
      {flat && lab(flat, `best ≤ ${sv!.limit}°`, 'flat')}
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
  const [colourBy, setColourBy] = useState<'sun' | 'slope'>('sun');
  const [limit, setLimit] = useState(8);
  const [st, setSt] = useState<{ s: 'idle' } | { s: 'loading'; since: number; job?: Job } | { s: 'ready'; r: EllipseResult; liveS?: number } | { s: 'error'; m: string }>({ s: 'idle' });
  const poll = useRef<{ stop: boolean } | null>(null);
  useEffect(() => () => { if (poll.current) poll.current.stop = true; }, []);
  const [, tick] = useState(0);
  const body = useMemo(() => ({
    site_id: siteId, start_utc: isoZ(startMs), days: 14, semi_major_m: size,
    semi_minor_m: Math.max(25, Math.round(size * ratio)), orientation_deg: ratio === 1 ? 0 : rot, panel_height_m: 2,
  }), [siteId, startMs, size, ratio, rot]);
  const key = JSON.stringify(body);
  const [asked, setAsked] = useState<string | null>(null);
  useEffect(() => {
    if (asked !== key) { if (poll.current) poll.current.stop = true; setSt({ s: 'idle' }); }
  }, [key, asked]);
  useEffect(() => {
    if (st.s !== 'loading') return;
    const t = setInterval(() => tick((k) => k + 1), 1000);
    return () => clearInterval(t);
  }, [st.s]);

  const run = () => {
    setAsked(key);
    const since = performance.now();
    setSt({ s: 'loading', since });
    if (staticIndex()) {
      // The static site reads the baked /api/landing-ellipse answers.
      post<EllipseResult>('/api/landing-ellipse', body).then((r) => setSt({ s: 'ready', r }), (e: Error) => setSt({ s: 'error', m: e.message }));
      return;
    }
    if (poll.current) poll.current.stop = true;
    const token = { stop: false };
    poll.current = token;
    const go = async (retried: boolean): Promise<void> => {
      let j = await post<Job>('/api/landing-ellipse/jobs', body);
      while (!token.stop) {
        if (j.status === 'done' && j.result) { setSt({ s: 'ready', r: j.result, liveS: j.elapsed_s }); return; }
        if (j.status === 'error') { setSt({ s: 'error', m: j.error ?? 'The ellipse job failed.' }); return; }
        setSt({ s: 'loading', since, job: j });
        await sleep(2500);
        if (token.stop) return;
        try {
          j = await getApi<Job>(`/api/landing-ellipse/jobs/${j.job_id}`);
        } catch (e) {
          // 404: the server restarted and forgot the job; start it again once.
          if (e instanceof ApiError && e.status === 404 && !retried) return go(true);
          throw e;
        }
      }
    };
    go(false).catch((e: Error) => { if (!token.stop) setSt({ s: 'error', m: e.message }); });
  };

  if (!open) {
    return (
      <section className="la-sec">
        <button type="button" className="la-btn" onClick={() => setOpen(true)}>Where could you actually come down? Landing ellipse</button>
      </section>
    );
  }
  const r = st.s === 'ready' ? st.r : null;
  const slope = r?.slope;
  const sOk = slope?.status === 'ok';
  const sv: SlopeView | null = r && sOk ? { limit, colour: colourBy === 'slope', best: bestWithin(r.points, limit) } : null;
  const share = sOk && slope!.area?.cdf ? shareAtOrBelow(slope!.area.cdf, limit) : null;
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
          {st.job?.status === 'queued'
            ? <>Waiting for another ellipse to finish · {Math.round(st.job.queued_s)} s</>
            : st.job
              ? <>Computing live on the server: point {st.job.done} of {st.job.total} · {Math.round(st.job.elapsed_s)} s</>
              : <>Running the full analysis at about 45 points inside the ellipse: {Math.round((performance.now() - st.since) / 1000)} s.</>}
          {' '}The first time takes about 4–5 minutes; the same ellipse again is instant.
          {st.job && st.job.total > 0
            ? <div className="el-prog"><i style={{ width: `${Math.round((st.job.done / st.job.total) * 100)}%` }} /></div>
            : <div className="la-bar" />}
        </div>
      )}
      {st.s === 'error' && <p className="la-err" role="alert">{st.m}</p>}
      {r && (
        <>
          {r.risk.points_ok > 0 ? (
            <>
              <div className="la-chips">{(r.risk.chips ?? []).map((c) => <span key={c} className="la-tag">{c}</span>)}</div>
              {sOk && (
                <div className="el-slope">
                  <div className="la-seg" role="group" aria-label="Colour the points by">
                    <button type="button" aria-pressed={colourBy === 'sun'} className={colourBy === 'sun' ? 'on' : undefined} onClick={() => setColourBy('sun')}>Sunlight</button>
                    <button type="button" aria-pressed={colourBy === 'slope'} className={colourBy === 'slope' ? 'on' : undefined} onClick={() => setColourBy('slope')}>Slope</button>
                  </div>
                  <label className="el-limit">
                    <span className="la-cap">Lander slope limit</span>
                    <input type="number" min={0.5} max={45} step={0.5} value={limit} onChange={(e) => { const v = Number(e.target.value); if (v >= 0.5 && v <= 45) setLimit(v); }} />°
                  </label>
                  {slope!.limit_note && <p className="la-fine" style={{ margin: 0 }}>{slope!.limit_note}</p>}
                  <div className="la-chips">
                    {share !== null && <span className="la-tag">{Math.round(share * 100)}% of ellipse ≤ {limit}°</span>}
                    {slope!.area?.slope_deg && <span className="la-tag">typical {slope!.area.slope_deg.median.toFixed(1)}°, steepest {slope!.area.slope_deg.max.toFixed(0)}°</span>}
                    {sv?.best && <span className="la-tag">sunniest point ≤ {limit}°: {sv.best.sunlit_percent.toFixed(0)}% sunlit</span>}
                    {sv && !sv.best && <span className="la-tag warn">no answered point is ≤ {limit}°</span>}
                  </div>
                </div>
              )}
              <Plot r={r} sv={sv} />
              {sv?.colour ? (
                <div className="la-elkey slope" aria-hidden="true">
                  <span><i style={{ background: SLOPE_FILL.within }} />within {limit}°</span>
                  <span><i style={{ background: SLOPE_FILL.uncertain }} />uncertain</span>
                  <span><i className="over" style={{ background: SLOPE_FILL.over }} />over (hatched)</span>
                  <span className="la-dim">grey haze: steepest 5 m pixel in each cell</span>
                </div>
              ) : <div className="la-elkey" aria-hidden="true"><span>0%</span><i /><span>100% sunlit</span><span className="la-dim">+ target</span></div>}
              {sOk && (
                <p className="la-fine" style={{ margin: 0 }}>
                  {slope!.label} 5 m terrain.{' '}
                  {slope!.validation?.status === 'pass' && slope!.validation.evidence && (
                    <a href={REPO_BLOB + slope!.validation.evidence} target="_blank" rel="noreferrer">Checked against NASA's slope map ↗</a>
                  )}
                </p>
              )}
              {slope && !sOk && <p className="la-fine dim" style={{ margin: 0 }}>Slope: {slope.reason ?? 'not available here (no 5 m terrain tile covers this ellipse)'}.</p>}
              <p className="la-fine" style={{ margin: 0 }}>
                {r.risk.target && <>On the target itself: sunlit {r.risk.target.sunlit_percent.toFixed(0)}%. </>}
                Earth in view {r.risk.earth_percent?.worst.toFixed(0)}–{r.risk.earth_percent?.best.toFixed(0)}% across the ellipse.
                {' '}{r.risk.points_ok} of {r.points.length} points answered{r.points_unavailable ? `, ${r.points_unavailable} without terrain` : ''}; {r.ellipse.spacing_m.toFixed(0)} m apart.
                {' '}{r.interpretation}
                {' '}{r.cache_hit ? 'From this server\'s cache.' : st.s === 'ready' && st.liveS !== undefined ? `Computed live in ${Math.round(st.liveS)} s.` : staticIndex() ? 'Precomputed.' : ''}
              </p>
            </>
          ) : <p className="la-err">No point in this ellipse could be analysed (terrain unavailable).</p>}
        </>
      )}
    </section>
  );
}
