// Moon weather forecast panel (PRD F29), in the title block: what the square on the Moon shows,
// layer switches, the probe point's month (date ribbon with Sun and Earth bands side by side) and
// the method and its evidence. Every number is counted from the baked masks.
import { useEffect, useMemo, useRef } from 'react';
import { bitAt, pixelOf, pixelSeries, type ForecastData } from './forecastData';
import { formatLat, formatLon } from '../state/format';

export type Probe = { lat: number; lon: number; name: string | null };
export type Layers = { earth: boolean; both: boolean };

type Props = {
  fc: ForecastData;
  cursorMs: number;
  frame: { k: number; j: number | null; litShare: number } | null;
  layers: Layers;
  probe: Probe;
  onLayers: (l: Layers) => void;
  onJump: (ms: number) => void;
  onClose: () => void;
};

const fmt = (ms: number) => {
  const d = new Date(ms);
  return `${d.getUTCDate()} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}, ${String(d.getUTCHours()).padStart(2, '0')}:00`;
};

/** Contiguous runs of true in a series, as [startMs, endMs) using the frame times. */
function runs(on: boolean[], times: number[], stepMs: number): [number, number][] {
  const out: [number, number][] = [];
  let s: number | null = null;
  on.forEach((v, i) => {
    if (v && s === null) s = times[i];
    if (!v && s !== null) { out.push([s, times[i]]); s = null; }
  });
  if (s !== null) out.push([s, times[times.length - 1] + stepMs]);
  return out;
}

function Ribbon({ fc, series, cursorMs, onJump }: { fc: ForecastData; series: { sun: boolean[]; earth: boolean[] }; cursorMs: number; onJump: (ms: number) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const t0 = fc.sunMs[0], t1 = fc.sunMs[fc.sunMs.length - 1] + 2 * 3600e3;
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.clientHeight;
    cv.width = w * dpr; cv.height = h * dpr;
    const g = cv.getContext('2d')!;
    g.scale(dpr, dpr);
    g.clearRect(0, 0, w, h);
    const X = (ms: number) => ((ms - t0) / (t1 - t0)) * w;
    const rows: [string, boolean[], number[], number][] = [
      ['#f2b84b', series.sun, fc.sunMs, 2 * 3600e3],
      ['#59c3d9', series.earth, fc.earthMs, 6 * 3600e3],
    ];
    const both = fc.sunMs.map((ms, k) => series.sun[k] && (() => { let j = 0; while (j + 1 < fc.earthMs.length && fc.earthMs[j + 1] <= ms) j++; return series.earth[j]; })());
    rows.push(['#5ed394', both, fc.sunMs, 2 * 3600e3]);
    rows.forEach(([col, on, times, step], i) => {
      const y = 4 + i * 16;
      g.fillStyle = 'rgba(236,231,220,0.08)'; g.fillRect(0, y, w, 11);
      g.fillStyle = col;
      on.forEach((v, k) => { if (v) g.fillRect(X(times[k]), y, Math.max(1, X(times[k] + step) - X(times[k])), 11); });
    });
    g.fillStyle = 'rgba(236,231,220,0.55)';
    for (let d = 0; d * 86400e3 <= t1 - t0; d++) { const x = X(t0 + d * 86400e3); g.fillRect(x, 50, 1, d % 7 === 0 ? 6 : 3); }
    const cx = X(cursorMs);
    if (cx >= 0 && cx <= w) { g.fillStyle = '#ece7dc'; g.fillRect(cx - 1, 0, 2, 56); }
  }, [fc, series, cursorMs, t0, t1]);
  return (
    <canvas ref={ref} className="la-ribbon" role="slider" aria-label="Forecast time" aria-valuemin={t0} aria-valuemax={t1} aria-valuenow={cursorMs}
      aria-valuetext={fmt(cursorMs)} tabIndex={0}
      onClick={(e) => { const b = e.currentTarget.getBoundingClientRect(); onJump(t0 + ((e.clientX - b.left) / b.width) * (t1 - t0)); }}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 86400e3 : 2 * 3600e3;
        if (e.key === 'ArrowRight') { e.preventDefault(); onJump(Math.min(t1 - 1, cursorMs + step)); }
        if (e.key === 'ArrowLeft') { e.preventDefault(); onJump(Math.max(t0, cursorMs - step)); }
      }} />
  );
}

export function ForecastPanel({ fc, cursorMs, frame, layers, probe, onLayers, onJump, onClose }: Props) {
  const px = useMemo(() => pixelOf(fc, probe.lat, probe.lon), [fc, probe]);
  const series = useMemo(() => (px ? pixelSeries(fc, px.r, px.c) : null), [fc, px]);
  const i = px ? px.r * fc.n + px.c : -1;
  const sunPct = px ? (fc.litHours[i] / fc.sunMs.length) * 100 : 0;
  const earthPct = px ? (fc.earthHours[i] / fc.earthMs.length) * 100 : 0;
  const litNow = px && frame ? bitAt(fc.litBits, frame.k, fc.n, px.r, px.c) : null;
  const earthNow = px && frame && frame.j !== null ? bitAt(fc.earthBits, frame.j, fc.n, px.r, px.c) : null;
  const earthRuns = series ? runs(series.earth, fc.earthMs, 6 * 3600e3) : [];
  const t0 = fc.sunMs[0];
  const month = new Date(t0).toLocaleString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' });

  return (
    <section className="la-carto-body site" aria-label="Moon weather forecast">
      <div className="la-side-scroll">
        <section className="la-sec">
          <button type="button" className="la-back" onClick={onClose}>‹ All sites</button>
          <div className="la-site-head">
            <h2>Moon weather forecast</h2>
            <span className="co">South pole, {Math.round(fc.halfM / 1000)} km around it, {month}</span>
          </div>
          <p className="la-fine" style={{ margin: 0 }}>
            The square on the Moon is the forecast: sunlight on the ground every 2 hours, Earth's line of sight every 6. Press play to watch shadows sweep the craters.
          </p>
          {frame ? (
            <div className="la-fc-now">
              <span className="la-cap">Showing</span>
              <b>{fmt(cursorMs)} UTC</b>
              <span>{Math.round(frame.litShare * 100)}% of the square in sunlight</span>
            </div>
          ) : (
            <button type="button" className="la-btn primary" onClick={() => onJump(t0)}>Go to {month}</button>
          )}
        </section>

        <section className="la-sec" aria-label="Layers">
          <div className="la-key flat">
            <div className="row"><i className="la-swatch lit" aria-hidden="true" /><span>Sunlit ground (black: in shadow)</span></div>
            <label className="row toggle">
              <input type="checkbox" checked={layers.earth} onChange={(e) => onLayers({ ...layers, earth: e.target.checked })} />
              <i className="la-swatch earth" aria-hidden="true" /><span>Earth in view (radio line of sight)</span>
            </label>
            <label className="row toggle">
              <input type="checkbox" checked={layers.both} onChange={(e) => onLayers({ ...layers, both: e.target.checked })} />
              <i className="la-swatch both" aria-hidden="true" /><span>Both: a solar lander can work and talk</span>
            </label>
          </div>
        </section>

        <section className="la-sec" aria-label="Point">
          <span className="la-cap">{probe.name ?? 'Point'} at {formatLat(probe.lat)} {formatLon(probe.lon)}, 250 m pixel of the 240 m regional map (click the square to move it)</span>
          {px && series ? (
            <>
              <p className="la-fc-probe">
                Now: <b className={litNow ? 'sun-c' : undefined}>{litNow ? 'in sunlight' : 'in shadow'}</b>,{' '}
                <b className={earthNow ? 'earth-c' : undefined}>{earthNow ? 'Earth in view' : 'Earth hidden'}</b>.
                This month: Sun <b>{sunPct.toFixed(0)}%</b> of the time, Earth <b>{earthPct.toFixed(0)}%</b>.
              </p>
              <Ribbon fc={fc} series={series} cursorMs={cursorMs} onJump={onJump} />
              <div className="la-ribbon-key"><span className="sun-c">Sun</span><span className="earth-c">Earth</span><span className="good-c">Both</span><span className="la-dim">1, 8, 15, 22, 29 {new Date(t0).toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}</span></div>
              <p className="la-fine">
                {earthRuns.length
                  ? <>Earth in view here: {earthRuns.map(([a, b]) => `${fmt(a)} to ${fmt(b)}`).join('; ')} UTC. A lander that must talk to Earth has only these days.</>
                  : <>Earth never rises over the horizon here this month: no direct radio link.</>}
              </p>
            </>
          ) : (
            <p className="la-fine">This point is outside the forecast square.</p>
          )}
        </section>

        <section className="la-sec">
          <p className="la-fine" style={{ margin: 0 }}>
            240 m regional view; site panels use 5 m terrain where available, so a site's own numbers can differ from its forecast pixel.
            {' '}Forecast, 240 m LOLA terrain, observer on the ground. Same shadow method that matched 5 of 6 LRO photos. Earth view agrees with the site panel's own analysis on 99.86% of 1,440 checked pixel-frames (all clear cases).
            {' '}Limits: {fc.limits} Earth: geometric line of sight from a 2 m antenna, not a radio link budget.
          </p>
        </section>
      </div>
    </section>
  );
}
