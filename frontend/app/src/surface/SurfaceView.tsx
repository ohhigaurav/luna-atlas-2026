// Standing at the site (PRD F20, and the target of "Stand there at touchdown"): a 360° panorama of
// the real horizon from the run (LOLA terrain where it exists, flat elsewhere) with the Sun and
// Earth where SPICE puts them at the clock's time, their tracks over the next 30 days, and the
// "Keep the lander alive" battery game on top of the same series.
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import { ApiError, checkSite, fetchRun, type RunRow, type SavedRun } from '../api/plan';
import type { ReferenceSite } from '../data/source';
import { CloseIcon, EarthIcon, PlayIcon, SunIcon } from '../ui/Icons';
import { spanText } from '../state/siteState';
import { simulate, socAt, type PanelKind, type SunSample } from './power';

const RUN_DAYS = 30;
const MASTS = [0, 1, 2, 5, 10];

type Props = {
  site: ReferenceSite;
  touchdownMs: number;
  missionDays: number;
  cursorMs: number;
  playing: boolean;
  onPlay: (fromMs: number | null) => void;   // null = pause
  onJump: (ms: number) => void;
  onClose: () => void;
};

type RunState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; run: SavedRun; times: Float64Array };
const runCache = new Map<string, Promise<SavedRun>>();

function useRun(siteId: string, startMs: number, mastM: number): RunState {
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
function rowAt(series: RunRow[], times: Float64Array, t: number): RunRow | null {
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

function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ w: 800, h: 300 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  return [ref, size] as const;
}

function Panorama({ run, times, cursorMs }: { run: SavedRun; times: Float64Array; cursorMs: number }) {
  const [ref, { w, h }] = useSize<HTMLDivElement>();
  const site = run.sites[0];
  const series = site.series;
  const now = rowAt(series, times, cursorMs);
  const hz = site.horizon_profile.map((b) => ({ az: b.azimuth_deg, el: b.elevation_deg ?? 0 }));
  const hzMax = Math.max(0, ...hz.map((p) => p.el));
  const trackMax = Math.max(...series.map((r) => r.sun_elevation_deg), ...series.map((r) => r.earth_elevation_deg));
  // Vertical scale: linear from -3 deg up to a ceiling that fits the horizon and the low part of
  // the tracks; if the Sun or Earth climbs higher, the upper 38% compresses everything above 15 deg.
  const lo = -3, linTop = Math.max(8, Math.ceil(hzMax + 3));
  const split = trackMax > linTop + 2 ? Math.max(linTop, 15) : null;
  const top = 26, bottom = h - 24, span = bottom - top;
  const y = (el: number) => {
    if (split === null) return bottom - ((Math.min(el, linTop) - lo) / (linTop - lo)) * span;
    if (el <= split) return bottom - ((el - lo) / (split - lo)) * span * 0.62;
    return bottom - span * 0.62 - ((Math.min(el, 90) - split) / (90 - split)) * span * 0.38;
  };
  const x = (az: number) => (az / 360) * w;
  const pxPerDegV = split === null ? span / (linTop - lo) : (span * 0.62) / (split - lo);
  const exag = pxPerDegV / (w / 360);
  const ground = `M0,${h} ` + hz.map((p) => `L${x(p.az).toFixed(1)},${y(p.el).toFixed(1)}`).join(' ') + ` L${w},${y(hz[hz.length - 1]?.el ?? 0).toFixed(1)} L${w},${h} Z`;
  const ridge = hz.map((p, i) => `${i ? 'L' : 'M'}${x(p.az).toFixed(1)},${y(p.el).toFixed(1)}`).join(' ');
  const track = (az: (r: RunRow) => number, el: (r: RunRow) => number) => {
    let d = '', prev: number | null = null;
    for (let i = 0; i < series.length; i += 2) {
      const a = az(series[i]), e = el(series[i]);
      if (e < lo - 1 || (split === null && e > linTop + 1)) { prev = null; continue; }
      d += `${prev === null || Math.abs(a - prev) > 180 ? 'M' : 'L'}${x(a).toFixed(1)},${y(e).toFixed(1)} `;
      prev = a;
    }
    return d;
  };
  const sunR = Math.max(5, 0.27 * pxPerDegV), earthR = Math.max(6, 0.95 * pxPerDegV);
  const ticks = split === null ? [0, Math.round(linTop / 2), linTop] : [0, 5, 10, split, 45, 90].filter((v, i, a) => v <= 90 && a.indexOf(v) === i);
  return (
    <div className="la-pano" ref={ref}>
      <svg role="img" aria-label={`Horizon at ${site.site.name}${now ? `: Sun ${now.sun_elevation_deg.toFixed(1)} degrees up at azimuth ${now.sun_azimuth_deg.toFixed(0)}` : ''}`}>
        {[0, 45, 90, 135, 180, 225, 270, 315, 360].map((a) => <line key={a} className="pano-grid" x1={x(a)} x2={x(a)} y1={top - 8} y2={bottom} />)}
        {ticks.map((e) => <g key={e}><line className="pano-grid" x1={0} x2={w} y1={y(e)} y2={y(e)} /><text className="pano-lab" x={30} y={y(e) - 4}>{e}°</text></g>)}
        {split !== null && <text className="pano-lab" x={w - 6} y={y(split) - 4} textAnchor="end">scale changes above {split}°</text>}
        <path className="pano-track-earth" d={track((r) => r.earth_azimuth_deg, (r) => r.earth_elevation_deg)} />
        <path className="pano-track-sun" d={track((r) => r.sun_azimuth_deg, (r) => r.sun_elevation_deg)} />
        {now && (
          <>
            <circle cx={x(now.earth_azimuth_deg)} cy={y(now.earth_elevation_deg)} r={earthR} fill="#1d6f80" stroke="var(--earth)" strokeWidth={1.5} />
            <g>
              <circle cx={x(now.sun_azimuth_deg)} cy={y(now.sun_elevation_deg)} r={sunR * 3.2} fill="rgba(242,184,75,.12)" />
              <circle cx={x(now.sun_azimuth_deg)} cy={y(now.sun_elevation_deg)} r={sunR} fill={now.sun_visible_upper_limb ? '#ffe2a3' : 'rgba(242,184,75,.35)'} />
            </g>
          </>
        )}
        <path className="pano-ground" d={ground} />
        <path className="pano-ridge" d={ridge} />
        {['N', 'E', 'S', 'W', 'N'].map((c, i) => <text key={i} className="pano-card" x={x(i * 90) + (i === 4 ? -14 : 4)} y={16}>{c}</text>)}
        <text className="pano-lab" x={w - 6} y={h - 7} textAnchor="end">
          {run.settings.horizon_mode === 'terrain' ? 'Horizon: LOLA terrain' : 'Horizon: flat (no terrain model here)'} · vertical ×{exag.toFixed(0)} · tracks: next {RUN_DAYS} d
        </text>
      </svg>
    </div>
  );
}

function SocChart({ samples, res, batteryWh, startMs, missionDays, cursorMs, onJump }: {
  samples: SunSample[]; res: ReturnType<typeof simulate>; batteryWh: number; startMs: number; missionDays: number; cursorMs: number; onJump: (ms: number) => void;
}) {
  const [ref, { w }] = useSize<HTMLDivElement>();
  const h = 150, pad = 4;
  const end = res.endMs, span = Math.max(1, end - startMs);
  const X = (t: number) => ((t - startMs) / span) * w;
  const Y = (wh: number) => pad + (1 - wh / batteryWh) * (h - 2 * pad - 14);
  const sunRects: [number, number][] = [];
  let open: number | null = null;
  for (const s of samples) {
    if (s.tMs < startMs) continue;
    if (s.sunVisible && open === null) open = s.tMs;
    if (!s.sunVisible && open !== null) { sunRects.push([open, s.tMs]); open = null; }
  }
  if (open !== null) sunRects.push([open, end]);
  let d = '';
  for (let i = 0; i < res.tMs.length; i++) d += `${i ? 'L' : 'M'}${X(res.tMs[i]).toFixed(1)},${Y(res.socWh[i]).toFixed(1)} `;
  const goal = startMs + missionDays * 86400e3;
  const days = Math.floor(span / 86400e3);
  const pick = (e: RPointerEvent<SVGSVGElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    onJump(startMs + ((e.clientX - b.left) / b.width) * span);
  };
  return (
    <div className="la-soc" ref={ref}>
      <svg onPointerDown={pick} style={{ cursor: 'pointer' }} role="img" aria-label="Battery charge over time; amber background is sunlight">
        {sunRects.map(([a, b]) => <rect key={a} className="soc-sun" x={X(a)} y={0} width={Math.max(1, X(b) - X(a))} height={h - 14} />)}
        {goal < end && <line className="soc-goal" x1={X(goal)} x2={X(goal)} y1={0} y2={h - 14} />}
        <path className="soc-line" d={d} />
        {res.diedMs !== null && <line className="soc-death" x1={X(res.diedMs)} x2={X(res.diedMs)} y1={0} y2={h - 14} />}
        {cursorMs >= startMs && cursorMs <= end && <line className="soc-cursor" x1={X(cursorMs)} x2={X(cursorMs)} y1={0} y2={h - 14} />}
        {Array.from({ length: days + 1 }, (_, k) => k).filter((k) => k % 5 === 0).map((k) => (
          <text key={k} className="pano-lab" x={Math.min(w - 24, X(startMs + k * 86400e3) + 2)} y={h - 2}>{k === 0 ? 'touchdown' : `+${k} d`}</text>
        ))}
        {goal < end && <text className="pano-lab" x={X(goal) + 4} y={12}>mission {missionDays} d</text>}
      </svg>
    </div>
  );
}

export function SurfaceView({ site, touchdownMs, missionDays, cursorMs, playing, onPlay, onJump, onClose }: Props) {
  const [mast, setMast] = useState(2);
  const [panel, setPanel] = useState<PanelKind>('tracking');
  const [panelW, setPanelW] = useState(400);
  const [batteryWh, setBatteryWh] = useState(2000);
  const [loadW, setLoadW] = useState(60);
  // Start a whole half hour before touchdown so the first sample is not after it.
  const startMs = Math.floor(touchdownMs / 1800e3) * 1800e3;
  const st = useRun(site.site_id, startMs, mast);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);

  const samples = useMemo<SunSample[]>(() => (st.status === 'ready'
    ? st.run.sites[0].series.map((r, i) => ({ tMs: st.times[i], sunElDeg: r.sun_elevation_deg, sunVisible: r.sun_visible_upper_limb })) : []), [st]);
  const res = useMemo(() => simulate(samples, { panelW, panel, batteryWh, loadW }, touchdownMs), [samples, panelW, panel, batteryWh, loadW, touchdownMs]);
  const soc = socAt(res, cursorMs);
  const now = st.status === 'ready' ? rowAt(st.run.sites[0].series, st.times, cursorMs) : null;
  // Next sunset / sunrise after the cursor, from the run's visibility flags.
  const nextChange = useMemo(() => {
    if (st.status !== 'ready' || !now) return null;
    const s = st.run.sites[0].series;
    for (let i = 0; i < s.length; i++) if (st.times[i] > cursorMs && s[i].sun_visible_upper_limb !== now.sun_visible_upper_limb) return st.times[i];
    return null;
  }, [st, now, cursorMs]);
  const goalMs = touchdownMs + missionDays * 86400e3;
  const madeIt = res.diedMs === null ? res.endMs >= goalMs : res.diedMs >= goalMs;

  return (
    <section className="la-sheet surface" aria-label={`Surface at ${site.name}`}>
      <div className="la-sheet-head">
        <h2>{site.name}</h2>
        <span className="la-cap">Touchdown {new Date(touchdownMs).toISOString().slice(0, 16).replace('T', ' ')} UTC · mast {mast} m</span>
        <span className="la-spacer" />
        <button type="button" className="la-btn" onClick={onClose}>Back to orbit</button>
        <button type="button" className="la-x" style={{ position: 'static' }} aria-label="Close (Esc)" onClick={onClose}><CloseIcon /></button>
      </div>
      {st.status === 'loading' && <div className="la-sheet-main"><span className="la-cap">Computing {RUN_DAYS} days at this site…</span><div className="la-bar" /></div>}
      {st.status === 'error' && <div className="la-sheet-main"><p className="la-err" role="alert">{st.message}</p></div>}
      {st.status === 'ready' && (
        <>
          <Panorama run={st.run} times={st.times} cursorMs={cursorMs} />
          <p className="la-airless">No air on the Moon: the horizon is the terrain itself, so a hill a kilometre away can hide the Sun, and the sky stays black in daylight.</p>
          <div className="la-surf-body">
            <div className="la-surf-ctl">
              <span className="la-cap">Keep the lander alive</span>
              <div className="la-field">
                <span className="la-cap">Solar panel</span>
                <div className="la-seg">
                  <button type="button" className={panel === 'flat' ? 'on' : ''} onClick={() => setPanel('flat')}>Flat on deck</button>
                  <button type="button" className={panel === 'tracking' ? 'on' : ''} onClick={() => setPanel('tracking')}>Upright, tracking</button>
                </div>
              </div>
              <label className="la-field"><span className="row"><span className="la-cap">Panel rating</span><b>{panelW} W</b></span>
                <input type="range" min={50} max={1500} step={50} value={panelW} onChange={(e) => setPanelW(+e.target.value)} /></label>
              <label className="la-field"><span className="row"><span className="la-cap">Battery</span><b>{(batteryWh / 1000).toFixed(1)} kWh</b></span>
                <input type="range" min={200} max={20000} step={200} value={batteryWh} onChange={(e) => setBatteryWh(+e.target.value)} /></label>
              <label className="la-field"><span className="row"><span className="la-cap">Load (heaters, radio)</span><b>{loadW} W</b></span>
                <input type="range" min={10} max={400} step={5} value={loadW} onChange={(e) => setLoadW(+e.target.value)} /></label>
              <div className="la-field">
                <span className="row"><span className="la-cap">Raise the mast</span><b>{mast} m</b></span>
                <div className="la-seg">{MASTS.map((m) => <button key={m} type="button" className={mast === m ? 'on' : ''} onClick={() => setMast(m)}>{m} m</button>)}</div>
                <span className="la-note" style={{ fontSize: 12 }}>A taller mast sees over nearby hills: the backend recomputes sunlight for that height.</span>
              </div>
              <p className="la-note" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                Illustrative power model, not a real lander: flat panel P = rating × sin(Sun elevation), upright tracking panel P = rating × cos(elevation), zero while the Sun’s upper limb is behind the horizon.
                Battery starts full, never exceeds capacity, and the lander dies at zero. Sunlight is from the run ({st.run.settings.horizon_mode === 'terrain' ? 'LOLA terrain' : 'flat horizon'}, {mast} m).
              </p>
            </div>
            <div className="la-surf-main">
              <div className="la-kv">
                <div><span className="la-cap sun-c"><SunIcon size={12} /> Sun</span>
                  <b>{now ? `${now.sun_elevation_deg.toFixed(1)}° · ${now.sun_azimuth_deg.toFixed(0)}°` : '—'}</b>
                  <span className="la-note" style={{ fontSize: 12 }}>{now ? (now.sun_visible_upper_limb ? 'visible' : 'behind the horizon') : 'outside the run'}{nextChange ? ` · ${now?.sun_visible_upper_limb ? 'sets' : 'rises'} in ${spanText(nextChange - cursorMs)}` : ''}</span></div>
                <div><span className="la-cap earth-c"><EarthIcon size={12} /> Earth</span>
                  <b>{now ? `${now.earth_elevation_deg.toFixed(1)}° · ${now.earth_azimuth_deg.toFixed(0)}°` : '—'}</b>
                  <span className="la-note" style={{ fontSize: 12 }}>{now ? (now.earth_center_clear ? 'in view' : 'hidden') : ''}</span></div>
                <div><span className="la-cap">Battery</span><b>{soc === null ? '—' : `${Math.round((soc / batteryWh) * 100)}%`}</b>
                  <div className="la-gauge" style={{ width: 160 }}><i className={soc === 0 ? 'empty' : soc !== null && soc / batteryWh < 0.25 ? 'low' : ''} style={{ width: `${soc === null ? 0 : (soc / batteryWh) * 100}%` }} /></div></div>
              </div>
              <div className="la-result">
                <b className={res.diedMs === null || madeIt ? 'good-c' : 'bad-c'}>
                  {res.diedMs === null ? `Survived ${spanText(res.aliveH * 3600e3)}+` : madeIt ? `${missionDays}-day mission done` : `Died after ${spanText(res.aliveH * 3600e3)}`}
                </b>
                <span className="la-note">
                  {res.diedMs === null
                    ? `still alive when the ${RUN_DAYS}-day run ends${madeIt ? `, ${missionDays}-day mission done` : ''}`
                    : `battery empty ${new Date(res.diedMs).toISOString().slice(0, 16).replace('T', ' ')} UTC, ${madeIt ? `${spanText(res.aliveH * 3600e3)} after touchdown` : `${missionDays}-day mission not done`}`}
                </span>
                <span className="la-spacer" />
                <button type="button" className="la-btn primary" onClick={() => onPlay(playing ? null : (cursorMs >= touchdownMs && cursorMs < res.endMs ? cursorMs : touchdownMs))}>
                  <PlayIcon playing={playing} /> {playing ? 'Pause' : 'Play the mission'}
                </button>
              </div>
              <SocChart samples={samples} res={res} batteryWh={batteryWh} startMs={touchdownMs} missionDays={missionDays} cursorMs={cursorMs} onJump={onJump} />
              {res.diedMs !== null && <p className="la-note">Moves that win: raise the mast, pick a later window, a bigger battery or a lighter load.</p>}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
