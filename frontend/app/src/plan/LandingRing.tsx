// F17 landing ring: 90 days drawn around the selected pin, clockwise from the top. Every arc edge is
// an API timestamp (landing windows from /api/landing-windows, bands from /api/check); the knob and
// the mission handle only change what is asked. Positioned on the pin every frame without React.
import { useEffect, useRef, type PointerEvent as RPointerEvent, type WheelEvent as RWheelEvent } from 'react';
import type { PinSite } from '../engine/pins';
import type { UtcRange } from '../api/plan';
import type { Answer } from './answer';
import { SEARCH_DAYS, type PlanData, type PlanSettings } from './usePlan';

const DAY = 86400e3, SYNODIC = 29.530589;
const S = 440, C = S / 2;
const R_SUN = 160, R_EARTH = 149, R_LAND = 132, R_LABEL = 178;

type Props = {
  site: PinSite;
  screenOf: (s: PinSite) => { x: number; y: number; facing: boolean } | null;
  settings: PlanSettings;
  data: PlanData;
  answer: Answer | null;
  onSettings: (p: Partial<PlanSettings>) => void;
  onJump: (ms: number) => void;
};

function angleOf(ms: number, start: number): number {
  return Math.min(359.99, Math.max(0, ((ms - start) / (SEARCH_DAYS * DAY)) * 360));
}
function pt(r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [C + r * Math.sin(a), C - r * Math.cos(a)];
}
function arc(r: number, a0: number, a1: number): string {
  if (a1 - a0 < 0.05) a1 = a0 + 0.05;
  const [x0, y0] = pt(r, a0), [x1, y1] = pt(r, a1);
  return `M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`;
}
function msAt(e: { clientX: number; clientY: number }, svg: SVGSVGElement, start: number): number {
  const b = svg.getBoundingClientRect();
  const dx = e.clientX - (b.left + b.width / 2), dy = e.clientY - (b.top + b.height / 2);
  let deg = (Math.atan2(dx, -dy) * 180) / Math.PI;
  if (deg < 0) deg += 360;
  return start + (deg / 360) * SEARCH_DAYS * DAY;
}
const snapDay = (ms: number) => Math.round(ms / DAY) * DAY;
const shortDate = (ms: number) => new Date(ms).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });

function Bands({ ranges, r, cls, start }: { ranges: UtcRange[]; r: number; cls: string; start: number }) {
  return <>{ranges.map((b) => {
    const a0 = angleOf(Date.parse(b.start_utc), start), a1 = angleOf(Date.parse(b.end_utc), start);
    return a1 > a0 ? <path key={b.start_utc} d={arc(r, a0, a1)} className={`ring-band ${cls}`} pathLength={1} /> : null;
  })}</>;
}

export function LandingRing({ site, screenOf, settings, data, answer, onSettings, onJump }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<'knob' | 'mission' | null>(null);

  // Follow the pin every frame; hide when it turns away.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const p = screenOf(site), el = wrap.current;
      if (el) {
        if (p && p.facing) { el.style.transform = `translate(${p.x - C}px, ${p.y - C}px)`; el.style.opacity = '1'; }
        else el.style.opacity = '0';
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [site, screenOf]);

  const start = settings.searchStartMs;
  const knobA = angleOf(settings.notBeforeMs, start);
  const missionStart = answer?.kind === 'window' ? answer.bestMs : settings.notBeforeMs;
  const missionA0 = angleOf(missionStart, start), missionA1 = angleOf(missionStart + settings.missionDays * DAY, start);

  const onDown = (which: 'knob' | 'mission') => (e: RPointerEvent) => {
    drag.current = which;
    (e.target as Element).setPointerCapture(e.pointerId);
    e.stopPropagation();
  };
  const onMove = (e: RPointerEvent) => {
    if (!drag.current || !svg.current) return;
    const ms = msAt(e, svg.current, start);
    if (drag.current === 'knob') onSettings({ notBeforeMs: snapDay(ms) });
    else onSettings({ missionDays: Math.round((ms - missionStart) / DAY) });
  };
  const onUp = () => { drag.current = null; };
  const onWheel = (e: RWheelEvent) => {
    e.stopPropagation();
    const step = (e.shiftKey ? SYNODIC : 1) * DAY * Math.sign(e.deltaY || e.deltaX);
    onSettings({ notBeforeMs: snapDay(settings.notBeforeMs + step) });
  };

  const ready = data.status === 'ready' ? data : null;
  const ticks = [0, 15, 30, 45, 60, 75];
  const [kx, ky] = pt(R_LAND, knobA), [mx, my] = pt(R_LAND, missionA1);
  const [tx, ty] = pt(R_LABEL + 16, knobA);

  return (
    <div ref={wrap} className="la-ring" style={{ opacity: 0 }}>
      <svg ref={svg} width={S} height={S} viewBox={`0 0 ${S} ${S}`} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
        role="group" aria-label={`Landing ring: ${SEARCH_DAYS} days from ${shortDate(start)}, clockwise from the top`}>
        <circle cx={C} cy={C} r={R_SUN} className="ring-track" />
        <circle cx={C} cy={C} r={R_EARTH} className="ring-track" />
        <circle cx={C} cy={C} r={R_LAND} className="ring-track land" onWheel={onWheel} />
        {ticks.map((d) => {
          const [x, y] = pt(R_LABEL, (d / SEARCH_DAYS) * 360);
          return <text key={d} x={x} y={y} className="ring-tick" textAnchor="middle" dominantBaseline="middle">{shortDate(start + d * DAY)}</text>;
        })}
        {ready?.bands && <>
          <Bands ranges={ready.bands.sun} r={R_SUN} cls="sun" start={start} />
          <Bands ranges={ready.bands.earth} r={R_EARTH} cls="earth" start={start} />
        </>}
        {ready && ready.landing.opportunities.map((o) => {
          const a0 = angleOf(Date.parse(o.touchdown_from_utc), start), a1 = angleOf(Date.parse(o.touchdown_until_utc), start);
          const passed = Date.parse(o.touchdown_until_utc) < settings.notBeforeMs;
          const next = answer?.kind === 'window' && answer.opportunity === o;
          const label = `Landing window ${shortDate(Date.parse(o.touchdown_from_utc))} to ${shortDate(Date.parse(o.touchdown_until_utc))}`;
          return (
            <path key={o.touchdown_from_utc} d={arc(R_LAND, a0, Math.max(a1, a0 + 1.2))} pathLength={1}
              className={`ring-land${passed ? ' passed' : ''}${next ? ' next' : ''}`} tabIndex={0} role="button" aria-label={label}
              onClick={() => onJump(Date.parse(o.best_touchdown_utc))}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onJump(Date.parse(o.best_touchdown_utc)); } }}>
              <title>{label}</title>
            </path>
          );
        })}
        {answer?.kind === 'miss' && (
          <path d={arc(R_LAND, angleOf(answer.touchdownMs, start), angleOf(answer.touchdownMs + settings.missionDays * DAY, start))} className="ring-ghost">
            <title>Closest miss</title>
          </path>
        )}
        <path d={arc(R_LAND - 13, missionA0, Math.max(missionA1, missionA0 + 0.5))} className="ring-mission" />
        <circle cx={mx} cy={my} r={9} className="ring-handle" onPointerDown={onDown('mission')} tabIndex={0} role="slider"
          aria-label="Mission length" aria-valuemin={1} aria-valuemax={14} aria-valuenow={settings.missionDays} aria-valuetext={`${settings.missionDays} days`}
          onKeyDown={(e) => {
            if (e.key === 'ArrowRight' || e.key === 'ArrowUp') onSettings({ missionDays: settings.missionDays + 1 });
            if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') onSettings({ missionDays: settings.missionDays - 1 });
          }} />
        <g className="ring-knob" onPointerDown={onDown('knob')} onWheel={onWheel} tabIndex={0} role="slider"
          aria-label="Earliest launch" aria-valuetext={shortDate(settings.notBeforeMs)}
          aria-valuemin={start} aria-valuemax={start + SEARCH_DAYS * DAY} aria-valuenow={settings.notBeforeMs}
          onKeyDown={(e) => {
            const d = e.shiftKey ? SYNODIC : 1;
            if (e.key === 'ArrowRight' || e.key === 'ArrowUp') onSettings({ notBeforeMs: snapDay(settings.notBeforeMs + d * DAY) });
            if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') onSettings({ notBeforeMs: snapDay(settings.notBeforeMs - d * DAY) });
          }}>
          <line x1={C} y1={C} x2={kx} y2={ky} className="ring-knob-line" />
          <circle cx={kx} cy={ky} r={22} className="ring-hit" />
          <circle cx={kx} cy={ky} r={10} className="ring-knob-dot" />
        </g>
        <text x={tx} y={ty} className="ring-knob-label" textAnchor="middle" dominantBaseline="middle">from {shortDate(settings.notBeforeMs)}</text>
      </svg>
    </div>
  );
}
