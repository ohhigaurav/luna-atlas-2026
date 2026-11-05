// The chart frame (neatline): a graduated border whose coordinate ticks are read from the globe
// on screen, a scale bar and a north arrow, like the margin of a printed lunar chart. Every tick is
// a real crossing of a meridian or parallel with the frame edge (ray-cast through the camera); when
// the Moon does not reach an edge, that edge has no ticks.
import { useEffect, useRef, useState, type RefObject } from 'react';
import type { GlobeHandle } from '../GlobeView';

const R_KM = 1737.4;
const D2R = Math.PI / 180;
export const FRAME_OUT = 8;   // outer rule, px from the window edge
export const FRAME_IN = 30;   // inner rule

type Tick = { edge: 't' | 'b' | 'l' | 'r'; at: number; label: string };
type Scale = { px: number; km: number; northDeg: number | null } | null;

const STEPS = [0.5, 1, 2, 5, 10, 15, 30];
const fmtLat = (v: number) => (Math.abs(v) < 1e-6 ? '0°' : `${+Math.abs(v).toFixed(1)}°${v < 0 ? 'S' : 'N'}`);
const fmtLon = (v: number) => { const e = ((v + 540) % 360) - 180; return Math.abs(e) < 1e-6 || Math.abs(Math.abs(e) - 180) < 1e-6 ? `${Math.abs(e)}°` : `${+Math.abs(e).toFixed(1)}°${e < 0 ? 'W' : 'E'}`; };

function angDeg(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  const s = Math.sin(((b.lat - a.lat) * D2R) / 2) ** 2 + Math.cos(a.lat * D2R) * Math.cos(b.lat * D2R) * Math.sin(((b.lon - a.lon) * D2R) / 2) ** 2;
  return (2 * Math.asin(Math.min(1, Math.sqrt(s)))) / D2R;
}

function niceKm(maxKm: number): number {
  const p = 10 ** Math.floor(Math.log10(maxKm));
  for (const m of [5, 2, 1]) if (m * p <= maxKm) return m * p;
  return p;
}

export function Neatline({ globe, centerX, centerY, quiet = false }: { globe: RefObject<GlobeHandle | null>; centerX: number; centerY: number; quiet?: boolean }) {
  const [ticks, setTicks] = useState<Tick[]>([]);
  const [scale, setScale] = useState<Scale>(null);
  const [size, setSize] = useState({ w: window.innerWidth, h: window.innerHeight });
  const last = useRef('');
  const c = useRef({ x: centerX, y: centerY });
  c.current = { x: centerX, y: centerY };

  useEffect(() => {
    const r = () => setSize({ w: window.innerWidth, h: window.innerHeight });
    window.addEventListener('resize', r);
    return () => window.removeEventListener('resize', r);
  }, []);

  useEffect(() => {
    let raf = 0, t = 0;
    const run = () => {
      const g = globe.current;
      if (g) compute(g);
      t = window.setTimeout(() => { raf = requestAnimationFrame(run); }, 200);
    };
    const compute = (g: GlobeHandle) => {
      const { w, h } = size, cx = c.current.x, cy = c.current.y;
      const p0 = g.pick(cx, cy), p1 = g.pick(cx + 100, cy);
      let step = 30, sc: Scale = null;
      if (p0 && p1) {
        const degPerPx = angDeg(p0, p1) / 100;
        step = STEPS.find((s) => s / Math.max(1e-6, degPerPx) >= 110) ?? 30;
        const kmPerPx = (degPerPx * D2R) * R_KM;
        const km = niceKm(150 * kmPerPx);
        let northDeg: number | null = null;
        if (p0.lat < 89.5) {
          const a = g.project(p0.lat, p0.lon), b = g.project(Math.min(89.9, p0.lat + 0.3), p0.lon);
          if (a && b && a.facing) northDeg = Math.atan2(b.x - a.x, -(b.y - a.y)) / D2R;
        }
        sc = { px: km / kmPerPx, km, northDeg };
      }
      // Walk the inner rule; record where a meridian or parallel of the chosen step crosses it.
      const out: Tick[] = [];
      const lo = FRAME_IN, edges: { edge: Tick['edge']; x0: number; y0: number; x1: number; y1: number }[] = [
        { edge: 't', x0: lo, y0: lo, x1: w - lo, y1: lo }, { edge: 'b', x0: lo, y0: h - lo, x1: w - lo, y1: h - lo },
        { edge: 'l', x0: lo, y0: lo, x1: lo, y1: h - lo }, { edge: 'r', x0: w - lo, y0: lo, x1: w - lo, y1: h - lo },
      ];
      for (const e of edges) {
        const len = Math.hypot(e.x1 - e.x0, e.y1 - e.y0), n = Math.ceil(len / 3);
        let prev: { lat: number; lon: number } | null = null, lastAt = -1e9;
        for (let i = 0; i <= n; i++) {
          const f = i / n, x = e.x0 + (e.x1 - e.x0) * f, y = e.y0 + (e.y1 - e.y0) * f;
          const p = g.pick(x, y);
          const at = f * len + (e.edge === 't' || e.edge === 'b' ? e.x0 : e.y0);
          if (p && prev) {
            const push = (label: string) => { if (at - lastAt > 46) { out.push({ edge: e.edge, at, label }); lastAt = at; } };
            const a = Math.floor(prev.lat / step), b = Math.floor(p.lat / step);
            if (a !== b) push(fmtLat(Math.max(a, b) * step));
            let d = p.lon - prev.lon; if (d > 180) d -= 360; if (d < -180) d += 360;
            if (Math.abs(d) < 20) {
              const u = prev.lon + d;
              const k0 = Math.floor(prev.lon / step), k1 = Math.floor(u / step);
              if (k0 !== k1) push(fmtLon(Math.max(k0, k1) * step));
            }
          }
          prev = p;
        }
      }
      const key = JSON.stringify([out, sc && [Math.round(sc.px), sc.km, sc.northDeg && Math.round(sc.northDeg)]]);
      if (key !== last.current) { last.current = key; setTicks(out); setScale(sc); }
    };
    raf = requestAnimationFrame(run);
    return () => { cancelAnimationFrame(raf); clearTimeout(t); };
  }, [globe, size]);

  const { w, h } = size, o = FRAME_OUT, i = FRAME_IN;
  return (
    <svg className="la-neat" width={w} height={h} aria-hidden="true">
      <path className="neat-band" fillRule="evenodd" d={`M0 0H${w}V${h}H0Z M${i} ${i}V${h - i}H${w - i}V${i}Z`} />
      <rect className="neat-out" x={o + 0.5} y={o + 0.5} width={w - 2 * o - 1} height={h - 2 * o - 1} />
      <rect className="neat-in" x={i + 0.5} y={i + 0.5} width={w - 2 * i - 1} height={h - 2 * i - 1} />
      {!quiet && ticks.map((t, k) => {
        const hor = t.edge === 't' || t.edge === 'b';
        const x = hor ? t.at : t.edge === 'l' ? i : w - i, y = hor ? (t.edge === 't' ? i : h - i) : t.at;
        const dx = t.edge === 'l' ? 1 : t.edge === 'r' ? -1 : 0, dy = t.edge === 't' ? 1 : t.edge === 'b' ? -1 : 0;
        const lx = hor ? x : t.edge === 'l' ? (o + i) / 2 : w - (o + i) / 2, ly = hor ? (t.edge === 't' ? (o + i) / 2 : h - (o + i) / 2) : y;
        return (
          <g key={k}>
            <line className="neat-tick" x1={x - dx * (i - o)} y1={y - dy * (i - o)} x2={x + dx * 9} y2={y + dy * 9} />
            <text className="neat-lab" x={lx} y={ly} transform={hor ? undefined : `rotate(${t.edge === 'l' ? -90 : 90} ${lx} ${ly})`}>{t.label}</text>
          </g>
        );
      })}
      {!quiet && scale && (
        <g className="neat-scale" transform={`translate(${w - i - 52 - scale.px}, ${h - i - 92})`}>
          <rect x={0} y={0} width={scale.px / 2} height={5} className="fill" />
          <rect x={scale.px / 2} y={0} width={scale.px / 2} height={5} className="hollow" />
          <text x={0} y={-6}>0</text>
          <text x={scale.px} y={-6} textAnchor="end">{scale.km >= 1 ? scale.km : scale.km.toFixed(1)} km</text>
          {scale.northDeg !== null && (
            <g transform={`translate(${scale.px + 18}, -2) rotate(${scale.northDeg})`}>
              <path d="M0,-11 L4,5 L0,2 L-4,5 Z" className="north" />
              <text x={0} y={-15} textAnchor="middle" transform={`rotate(${-scale.northDeg} 0 -15)`}>N</text>
            </g>
          )}
        </g>
      )}
    </svg>
  );
}
