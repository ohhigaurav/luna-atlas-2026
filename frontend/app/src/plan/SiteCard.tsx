// The answer for one place on the chosen date, in plain words first (general audience), numbers
// second, expert controls behind "Details". Landing verdict: /api/landing-windows (terrain near
// the pole). Sun and Earth at that moment: /api/compare for this one place (terrain), with the
// flat-ground estimate shown, labelled, until it arrives.
import { useEffect, useState, type ReactNode } from 'react';
import { nextText } from '../api/compare';
import { useCompare } from '../compare/useCompare';
import type { ReferenceSite } from '../data/source';
import { formatLat, formatLon } from '../state/format';
import { spanText, type SiteNow } from '../state/siteState';
import { fixes, type Answer } from './answer';
import type { PlanData, PlanSettings } from './usePlan';

type Props = {
  site: ReferenceSite;
  live: boolean;
  cursorMs: number;
  now: SiteNow | null;
  settings: PlanSettings;
  data: PlanData;
  answer: Answer | null;
  inCompare: boolean;
  details: ReactNode;
  onSettings: (p: Partial<PlanSettings>) => void;
  onJump: (ms: number) => void;
  onStand: (ms: number) => void;
  onCompare: () => void;
  onClose: () => void;
};

const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function SiteCard({ site, live, cursorMs, now, settings, data, answer, inCompare, details, onSettings, onJump, onStand, onCompare, onClose }: Props) {
  const [more, setMore] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (data.status !== 'loading') return;
    const t0 = Date.now(), t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [data.status]);
  const cmp = useCompare([site.site_id], cursorMs, 30, live);
  const row = cmp.s === 'ready' ? cmp.r.rows[0] : cmp.s === 'loading' && cmp.last?.rows[0]?.site.name === site.name ? cmp.last.rows[0] : null;
  const terrain = row ? (row.horizon_mode === 'terrain' ? `${row.terrain?.finest_resolution_m ?? ''} m terrain`.trim() : 'flat horizon') : null;
  const open = answer?.kind === 'window' && answer.fromMs <= cursorMs + 60e3;

  let verdict: ReactNode;
  if (!live) verdict = <p className="sc-v dim">Landing dates need the live backend.</p>;
  else if (data.status === 'loading') verdict = <p className="sc-v dim">Checking the next 90 days for a landing window… {elapsed} s</p>;
  else if (data.status === 'error') verdict = <p className="sc-v bad" role="alert">{data.message}</p>;
  else if (answer?.kind === 'window' && open) {
    verdict = (
      <>
        <p className="sc-v good"><i>✓</i> You can land on this date</p>
        <p className="sc-sub">The window stays open until {day(answer.untilMs)}. Land by then and the Sun stays up for {settings.missionDays} days, with Earth in view at touchdown.</p>
      </>
    );
  } else if (answer?.kind === 'window') {
    verdict = (
      <>
        <p className="sc-v warn">Not a good date to land here</p>
        <p className="sc-sub">Next chance: <b>{day(answer.fromMs)}</b>, in {spanText(answer.fromMs - cursorMs)}.</p>
        <button type="button" className="la-btn primary" onClick={() => onJump(answer.bestMs)}>Go to {day(answer.bestMs)}</button>
      </>
    );
  } else if (answer?.kind === 'miss') {
    const fx = fixes(answer, settings.missionDays, settings.maxSunDeg);
    verdict = (
      <>
        <p className="sc-v bad">No landing window in the next 90 days</p>
        <p className="sc-sub">The closest try, {day(answer.touchdownMs)}, gets {spanText(answer.daylightH * 3600e3)} of sunlight; a {settings.missionDays}-day mission needs {spanText(answer.neededH * 3600e3)}.</p>
        {fx.length > 0 && <div className="sc-fixes">{fx.map((f) => <button key={f.label} type="button" className="la-btn" onClick={() => onSettings({ ...(f.missionDays !== undefined ? { missionDays: f.missionDays } : {}), ...(f.maxSunDeg !== undefined ? { maxSunDeg: f.maxSunDeg } : {}) })}>{f.label}</button>)}</div>}
      </>
    );
  } else verdict = null;

  const sun = row ? row.now.sun : null, earth = row ? row.now.earth : null;
  return (
    <aside className="la-card" aria-label={site.name}>
      <div className="sc-top">
        <button type="button" className="sc-close" onClick={onClose} aria-label="Close (Esc)">×</button>
        <h2>{site.name}</h2>
        <p className="sc-where">{formatLat(site.latitude_deg)}, {formatLon(site.longitude_deg)}{terrain ? `, ${terrain}` : ''}</p>
      </div>

      <div className="sc-verdict" aria-live="polite">{verdict}</div>

      <div className="sc-now">
        <p className="sc-h">On {day(cursorMs)} at {new Date(cursorMs).toISOString().slice(11, 16)} UTC</p>
        <div className="sc-body">
          <i className={`sc-ico sun${(sun ? sun.up : now?.day) ? '' : ' off'}`} aria-hidden="true" />
          <div>
            {sun ? (
              <><b>{sun.up ? `Sun up, ${sun.elevation_deg.toFixed(1)}° high` : 'Sun down'}</b><span>{cap(nextText(row!.sun_next, 30))}</span></>
            ) : now ? (
              <><b>{now.day ? `Sun up, ${now.sunElDeg.toFixed(1)}° high` : 'Sun down'}</b><span>{now.nextChangeMs ? `${now.day ? 'Sunset' : 'Sunrise'} in ${spanText(now.nextChangeMs - cursorMs)}` : ''} (estimate, flat ground)</span></>
            ) : null}
          </div>
        </div>
        <div className="sc-body">
          <i className={`sc-ico earth${(earth ? earth.up : now?.earthUp) ? '' : ' off'}`} aria-hidden="true" />
          <div>
            {earth ? (
              <><b>{earth.up ? `Earth in view, ${earth.elevation_deg.toFixed(1)}° up` : 'Earth hidden: no radio link'}</b><span>{cap(nextText(row!.earth_next, 30))}</span></>
            ) : now ? (
              <><b>{now.earthUp ? 'Earth in view' : 'Earth hidden'}</b><span>{now.earthNextMs ? `${now.earthUp ? 'Earthset' : 'Earthrise'} in ${spanText(now.earthNextMs - cursorMs)}` : ''} (estimate, flat ground)</span></>
            ) : null}
          </div>
        </div>
        {row && <p className="sc-month">Next 30 days: sunlit {row.period.sunlit_percent.toFixed(0)}% of the time, Earth in view {row.period.earth_percent.toFixed(0)}%, longest night {spanText(row.period.longest_darkness_h * 3600e3)}{row.period.longest_darkness_lower_bound ? '+' : ''}.</p>}
        {cmp.s === 'loading' && !row && <p className="sc-month dim">Working out the real horizon here…</p>}
      </div>

      <div className="sc-actions">
        <button type="button" className="la-btn primary" onClick={() => onStand(cursorMs)}>Stand here in 3D</button>
        <button type="button" className={`la-btn${inCompare ? ' on' : ''}`} aria-pressed={inCompare} onClick={onCompare}>{inCompare ? '✓ Comparing' : '+ Compare'}</button>
        <button type="button" className="la-btn" aria-expanded={more} onClick={() => setMore((m) => !m)}>{more ? 'Fewer details' : 'Details'}</button>
      </div>
      {more && <div className="sc-details">{details}</div>}
    </aside>
  );
}
