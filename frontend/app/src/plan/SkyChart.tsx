// Sky chart (challenge O3, O6, C7, C10): the site's terrain skyline as a 360° panorama with the
// Sun's and Earth's tracks over the whole period, and Earth's track close up at true scale. Data:
// the saved run behind the card's 30-day answer (GET /api/runs/{run_id}, as Compare's MiniSky).
import { useEffect, useMemo, useState } from 'react';
import { fetchRun, type HorizonBin, type SavedRun } from '../api/plan';
import { around, circularMean, dayTicks, earthRadiusDeg, elevRange, exaggeration, extent, segments, track, type Pt, type Segment } from './skyTracks';

type Props = { runId: string; days: number; terrain: string | null };

const dayText = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const deg = (x: number) => `${x < 0 ? '−' : x > 0 ? '+' : ''}${Math.abs(x).toFixed(1)}°`;
const poly = (s: Segment) => s.pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

/** The skyline as a closed shape down to the bottom of the plot; bins without terrain are skipped. */
function ground(hz: HorizonBin[], x: (a: number) => number, y: (e: number) => number, bottom: number, a0 = 0, a1 = 360): string {
  const b = hz.filter((h) => h.elevation_deg != null).map((h) => ({ a: h.azimuth_deg, e: h.elevation_deg as number }));
  if (!b.length) return '';
  const pts = b.map((p) => `L${x(p.a).toFixed(1)},${y(p.e).toFixed(1)}`).join(' ');
  return `M${x(a0).toFixed(1)},${bottom} L${x(a0).toFixed(1)},${y(b[0].e).toFixed(1)} ${pts} L${x(a1).toFixed(1)},${y(b[b.length - 1].e).toFixed(1)} L${x(a1).toFixed(1)},${bottom} Z`;
}

function Tracks({ segs, cls }: { segs: Segment[]; cls: string }) {
  return <>{segs.map((s, i) => <polyline key={i} points={poly(s)} className={`sk-${cls}${s.up ? '' : ' hid'}`} />)}</>;
}

export function Panorama({ run, sun, earth }: { run: SavedRun['sites'][number]; sun: Pt[]; earth: Pt[] }) {
  const W = 720, H = 250, TOP = 16, BOT = 30, PH = H - TOP - BOT;
  const hz = useMemo(() => {
    const b = [...run.horizon_profile].sort((p, q) => p.azimuth_deg - q.azimuth_deg);
    return b.length && b[b.length - 1].azimuth_deg < 360 ? [...b, { ...b[0], azimuth_deg: 360 }] : b;
  }, [run.horizon_profile]);
  const { lo, hi } = elevRange(hz, [sun, earth]);
  const x = (a: number) => (a / 360) * W, y = (e: number) => TOP + ((hi - e) / (hi - lo)) * PH;
  const ex = exaggeration(W / 360, PH / (hi - lo));
  const sunSegs = segments(sun, x, y, lo, hi), earthSegs = segments(earth, x, y, lo, hi);
  const ticks = dayTicks(sun).filter(({ i }) => sun[i].el >= lo && sun[i].el <= hi);
  const ylabels = [...new Set([lo, 0, hi])].filter((v) => v >= lo && v <= hi);
  return (
    <svg className="la-skychart" viewBox={`0 0 ${W} ${H}`} role="img" data-tour="sky"
      aria-label={`Panorama of the terrain horizon with the Sun's and Earth's tracks over ${Math.round((sun[sun.length - 1].t - sun[0].t) / 86400e3)} days. Heights drawn ${ex.toFixed(0)} times taller than true.`}>
      <path d={ground(hz, x, y, TOP + PH)} className="sk-ground" />
      {ylabels.map((v) => (
        <g key={v}>
          <line x1={0} x2={W} y1={y(v)} y2={y(v)} className={v === 0 ? 'sk-level' : 'sk-grid'} />
          <text x={v === 0 ? W - 4 : 4} y={y(v) - 4} textAnchor={v === 0 ? 'end' : 'start'} className="sk-lab">{v === 0 ? 'level 0°' : `${v > 0 ? '+' : '−'}${Math.abs(v)}°`}</text>
        </g>
      ))}
      <Tracks segs={earthSegs} cls="earth" />
      <Tracks segs={sunSegs} cls="sun" />
      {ticks.map(({ i, day }) => (
        <g key={i}>
          <circle cx={x(sun[i].az)} cy={y(sun[i].el)} r={day % 5 === 0 ? 4 : 2.5} className="sk-tick" />
          {day % 5 === 0 && <text x={x(sun[i].az)} y={y(sun[i].el) - 8} textAnchor="middle" className="sk-day">{day === 0 ? 'start' : `day ${day}`}</text>}
        </g>
      ))}
      {[0, 90, 180, 270, 360].map((a, i) => <text key={a} x={Math.min(W - 4, Math.max(4, x(a)))} y={H - 10} textAnchor={a === 0 ? 'start' : a === 360 ? 'end' : 'middle'} className="sk-lab">{'NESWN'[i]} {a}°</text>)}
      <text x={W - 4} y={TOP + 2} textAnchor="end" dominantBaseline="hanging" className="sk-lab">heights ×{ex < 10 ? ex.toFixed(1) : ex.toFixed(0)} (vertical exaggeration)</text>
    </svg>
  );
}

/** Earth's track over the period at equal scale in both directions, with its real size. */
export function EarthLoop({ run, earth }: { run: SavedRun['sites'][number]; earth: Pt[] }) {
  const W = 320, H = 260, S = 220, OX = (W - S) / 2, OY = 12;
  const c = circularMean(earth.map((p) => p.az));
  const pts = earth.map((p) => ({ ...p, az: around(p.az, c) }));
  const [a0, a1] = extent(pts, (p) => p.az), [e0, e1] = extent(pts, (p) => p.el);
  const span = Math.max(a1 - a0, e1 - e0) + 4, am = (a0 + a1) / 2, em = (e0 + e1) / 2;
  const k = S / span, left = am - span / 2, top = em + span / 2;
  const x = (a: number) => OX + (a - left) * k, y = (e: number) => OY + (top - e) * k;
  const hz = run.earth_horizon_profile
    .filter((b) => b.elevation_deg != null)
    .map((b) => ({ ...b, azimuth_deg: around(b.azimuth_deg, c) }))
    .filter((b) => b.azimuth_deg >= left - 5 && b.azimuth_deg <= left + span + 5)
    .sort((p, q) => p.azimuth_deg - q.azimuth_deg);
  const segs = segments(pts, x, y, -90, 90, false);
  const ticks = dayTicks(pts);
  const r0 = run.series[0]?.earth_range_m;
  const rDisc = r0 ? earthRadiusDeg(r0) * k : null;
  const level = 0 >= top - span && 0 <= top;
  return (
    <svg className="la-skychart loop" viewBox={`0 0 ${W} ${H}`} role="img" data-tour="sky-earth"
      aria-label={`Earth's track over the period, true scale: azimuth ${a0.toFixed(1)} to ${a1.toFixed(1)} degrees, elevation ${e0.toFixed(1)} to ${e1.toFixed(1)} degrees`}>
      <defs><clipPath id="sk-loop-clip"><rect x={OX} y={OY} width={S} height={S} /></clipPath></defs>
      <rect x={OX} y={OY} width={S} height={S} className="sk-frame" />
      <g clipPath="url(#sk-loop-clip)">
        {hz.length > 1 && <path d={ground(hz, x, y, OY + S, hz[0].azimuth_deg, hz[hz.length - 1].azimuth_deg)} className="sk-ground" />}
        {level && <line x1={OX} x2={OX + S} y1={y(0)} y2={y(0)} className="sk-level" />}
        <Tracks segs={segs} cls="earth" />
        {rDisc && <circle cx={x(pts[0].az)} cy={y(pts[0].el)} r={rDisc} className={`sk-disc${pts[0].up ? '' : ' hid'}`} />}
        {ticks.map(({ i, day }) => day % 5 === 0 && (
          <g key={i}>
            <circle cx={x(pts[i].az)} cy={y(pts[i].el)} r={2.5} className="sk-tick" />
            <text x={x(pts[i].az) + 5} y={y(pts[i].el) - 4} className="sk-day">{day === 0 ? 'start' : `d${day}`}</text>
          </g>
        ))}
      </g>
      {level && <text x={OX + 3} y={y(0) - 3} className="sk-lab">level 0°</text>}
      <text x={OX} y={OY + S + 16} className="sk-lab">az {((a0 % 360) + 360) % 360 | 0}°–{((a1 % 360) + 360) % 360 | 0}°</text>
      <text x={OX + S} y={OY + S + 16} textAnchor="end" className="sk-lab">true scale, box {span.toFixed(0)}° wide</text>
    </svg>
  );
}

export function SkyChart({ runId, days, terrain }: Props) {
  const [st, setSt] = useState<{ id: string; run?: SavedRun; err?: string }>({ id: '' });
  useEffect(() => {
    const ac = new AbortController();
    fetchRun(`/api/runs/${runId}`, ac.signal).then(
      (run) => setSt({ id: runId, run }),
      (e: Error) => { if (!ac.signal.aborted) setSt({ id: runId, err: e.message }); },
    );
    return () => ac.abort();
  }, [runId]);
  const site = st.id === runId ? st.run?.sites[0] : undefined;
  const sun = useMemo(() => (site ? track(site.series, 'sun') : []), [site]);
  const earth = useMemo(() => (site ? track(site.series, 'earth') : []), [site]);

  if (st.id === runId && st.err) return <section className="la-sec"><p className="la-err">Sky chart: could not load the saved run ({st.err}).</p></section>;
  if (!site || sun.length < 2) return <section className="la-sec"><span className="la-cap">Sky over the next {days} days</span><p className="la-note">Loading the saved run…</p></section>;
  const [sMin, sMax] = extent(sun, (p) => p.el), [eMin, eMax] = extent(earth, (p) => p.el);
  const upShare = (pts: Pt[]) => Math.round((100 * pts.filter((p) => p.up).length) / pts.length);
  return (
    <section className="la-sec la-sky" aria-label="Sky chart">
      <span className="la-cap">Sky from {dayText(sun[0].t)}, {days} days{terrain ? `, ${terrain}` : ''}</span>
      <Panorama run={site} sun={sun} earth={earth} />
      <p className="sk-cap">
        <b className="sun-c">Sun</b> centre between {deg(sMin)} and {deg(sMax)} from level; above the skyline {upShare(sun)}% of the time.{' '}
        <b className="earth-c">Earth</b> between {deg(eMin)} and {deg(eMax)}; centre above the skyline {upShare(earth)}% (line of sight, not a radio link).{' '}
        Solid: in view. Faint: behind the terrain. Dots mark each day from the start.
      </p>
      <EarthLoop run={site} earth={earth} />
      <p className="sk-cap">
        Earth close up, same scale both ways{site.series[0]?.earth_range_m ? ', with its real size at the start' : ''}. It barely moves across the sky; the loop is mostly libration, the Moon's slow rocking as seen from Earth.
        Positions every {Math.round((sun[1].t - sun[0].t) / 60e3)} min from the saved run (NAIF SPICE). Skyline seen from a panel {st.run!.settings.sun_observer_height_m} m up; the Earth close-up uses the antenna's, {st.run!.settings.antenna_height_m} m.
      </p>
    </section>
  );
}
