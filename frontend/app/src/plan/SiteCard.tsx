// The answer for one place on the chosen date, in plain words first (general audience), numbers
// second, expert controls behind "Details". Landing verdict: /api/landing-windows (terrain near
// the pole). Sun and Earth at that moment: /api/compare for this one place (terrain), with the
// flat-ground estimate shown, labelled, until it arrives.
import { useEffect, useState, type ReactNode } from 'react';
import { nextText } from '../api/compare';
import { useCompare } from '../compare/useCompare';
import type { ReferenceSite } from '../data/source';
import { terrainText } from '../state/terrain';
import { BestDate } from './BestDate';
import { staticIndex } from '../data/staticMode';
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
  /** Opens the 3D ground view at ms; note says why it starts there (handoff B). */
  onStand: (ms: number, note?: string) => void;
  onCompare: () => void;
  onClose: () => void;
  /** Opens a suggested nearby point (analysis_note.suggested_point) as a clicked point. */
  onTry: (lat: number, lon: number, label: string) => void;
};

/** Our measured findings live in the repo's validation/evidence folder. */
const EVIDENCE_BASE = 'https://github.com/ohhigaurav/luna-atlas-2026/blob/main/';

const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' });
const SOURCE_NAMES: Array<[RegExp, string]> = [
  [/lroc/i, 'LROC'], [/nssdc/i, 'NASA NSSDC'], [/10\.3847\/psj|\/psj\//i, 'Planetary Science Journal'],
  [/usgs/i, 'USGS gazetteer'], [/science\.nasa\.gov/i, 'NASA'], [/ncbi|pmc/i, 'peer-reviewed study'],
];
const sourceName = (s: ReferenceSite) => SOURCE_NAMES.find(([re]) => re.test(s.source_url ?? ''))?.[1];

/** Where the coordinates come from, always in words (an internal document (not published); handoff D). */
export function originLabel(site: ReferenceSite): string {
  if (site.site_id.startsWith('point:')) return 'Your point';
  if (site.origin === 'official') return 'Official challenge site';
  const src = sourceName(site), from = src ? ` · ${src}` : '';
  if (site.position_kind === 'landed_hardware') return `Landing site${from}`;
  if (site.position_kind === 'target_region_centre') return `Planned target, region centre${from}`;
  return `Published site${from}`;
}
/** The rest of the story, one hover away: the source and that it is not the challenge's own list. */
export function originTitle(site: ReferenceSite): string {
  if (site.site_id.startsWith('point:')) return 'A point you picked on the map.';
  if (site.origin === 'official') return 'From the Space Apps 2026 challenge site list.';
  const src = sourceName(site);
  return `Coordinates from ${src ?? 'a published source'}${site.source_record ? ` (${site.source_record})` : ''}. `
    + "Not from the challenge's own site list, which is released 13 Nov and marked \"Official challenge site\".";
}
const MISSION_CHIPS = [1, 3, 5, 7, 10, 14];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function SiteCard({ site, live, cursorMs, now, settings, data, answer, inCompare, details, onSettings, onJump, onStand, onCompare, onClose, onTry }: Props) {
  const [more, setMore] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (data.status !== 'loading') return;
    const t0 = Date.now(), t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [data.status]);
  const cmp = useCompare([site.site_id], cursorMs, 30, live);
  const row = cmp.s === 'ready' ? cmp.r.rows[0] : cmp.s === 'loading' && cmp.last?.rows[0]?.site.name === site.name ? cmp.last.rows[0] : null;
  const terrain = row ? terrainText(row.horizon_mode, row.terrain?.finest_resolution_m)
    : data.status === 'ready' ? terrainText(data.landing.horizon_mode, data.landing.terrain?.finest_resolution_m) : null;
  // The landing answer's own terrain; the compare row's when the landing answer does not say (older backend).
  const answerTerrain = data.status === 'ready'
    ? (data.landing.terrain?.finest_resolution_m != null || data.landing.horizon_mode !== 'terrain'
      ? terrainText(data.landing.horizon_mode, data.landing.terrain?.finest_resolution_m) : terrain) : null;
  const open = answer?.kind === 'window' && answer.fromMs <= cursorMs + 60e3;

  let verdict: ReactNode;
  if (!live) verdict = <p className="sc-v dim">Landing dates need the live backend.</p>;
  else if (data.status === 'loading') verdict = <p className="sc-v dim">Checking the next 90 days for a landing window… {elapsed} s</p>;
  else if (data.status === 'error') verdict = <p className="sc-v bad" role="alert">{data.message}</p>;
  else if (answer?.kind === 'window' && open) {
    verdict = (
      <>
        <p className="sc-v good"><i>✓</i> You can land on this date</p>
        <p className="sc-sub">{answer.opportunity.sun_above_horizon_at_best_deg !== undefined && <>Sun <b>{answer.opportunity.sun_above_horizon_at_best_deg.toFixed(1)}°</b> above the horizon at the best moment. </>}The window stays open until {day(answer.untilMs)}. Land by then and the Sun stays up for <b>{settings.missionDays} {settings.missionDays === 1 ? 'day' : 'days'}</b> (your mission), with Earth in view at touchdown.</p>
      </>
    );
  } else if (answer?.kind === 'window') {
    verdict = (
      <>
        <p className="sc-v warn">Not a good date to land here</p>
        <p className="sc-sub">Next chance: <b>{day(answer.fromMs)}</b>, in {spanText(answer.fromMs - cursorMs)}{answer.opportunity.sun_above_horizon_at_best_deg !== undefined ? `, Sun ${answer.opportunity.sun_above_horizon_at_best_deg.toFixed(1)}° above the horizon` : ''}.</p>
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
  // Start the 3D mission inside a landing window, never silently in the dark (handoff B).
  const stand = () => {
    if (answer?.kind === 'window' && open) onStand(cursorMs);
    else if (answer?.kind === 'window') onStand(answer.bestMs, `Starting at the next landing window, ${day(answer.bestMs)}.`);
    else if (live && data.status === 'ready') onStand(cursorMs, 'No landing window in the next 90 days: this shows the lander waiting in the dark.');
    else onStand(cursorMs);
  };
  const chips = live && data.status === 'ready' && (
    <div className="sc-chips" role="group" aria-label="Mission length">
      <span>Mission</span>
      {[...new Set([...MISSION_CHIPS, settings.missionDays])].sort((a, b) => a - b).map((d) => (
        <button key={d} type="button" className={d === settings.missionDays ? 'on' : undefined} aria-pressed={d === settings.missionDays}
          onClick={() => onSettings({ missionDays: d })}>{d} d</button>
      ))}
    </div>
  );
  return (
    <aside className="la-card" aria-label={site.name}>
      <div className="sc-top">
        <button type="button" className="sc-close" onClick={onClose} aria-label="Close (Esc)">×</button>
        <h2>{site.name}</h2>
        <p className="sc-where">
          <span className={`sc-origin${site.origin === 'official' ? ' official' : ''}`} title={originTitle(site)}>{originLabel(site)}</span>
          {formatLat(site.latitude_deg)}, {formatLon(site.longitude_deg)}{terrain ? `, ${terrain}` : ''}
        </p>
        {site.analysis_note && (
          <div className="sc-note">
            <p>
              {site.analysis_note.text}
              {site.analysis_note.evidence && <> <a href={EVIDENCE_BASE + site.analysis_note.evidence} target="_blank" rel="noreferrer">evidence ↗</a></>}
            </p>
            {site.analysis_note.suggested_point && (
              <button type="button" className="la-btn" onClick={() => { const sp = site.analysis_note!.suggested_point!; onTry(sp.latitude_deg, sp.longitude_deg, sp.label); }}>
                Try {site.analysis_note.suggested_point.label}
              </button>
            )}
          </div>
        )}
      </div>

      <div className="sc-verdict" aria-live="polite">{verdict}{answerTerrain && verdict && data.status === 'ready' && (
        <p className="sc-terr">Checked on {answerTerrain} · {staticIndex() ? 'precomputed by the same code' : data.landing.cache_hit ? 'from this server\'s cache' : `computed live in ${Math.max(1, Math.round(data.landing.compute_seconds ?? 0))} s`}.</p>
      )}{chips}</div>
      {live && data.status === 'ready' && (
        <BestDate siteId={site.site_id} cursorMs={cursorMs} missionDays={settings.missionDays} maxSunDeg={settings.maxSunDeg}
          onJump={onJump} onStand={onStand} />
      )}

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
        {row && <p className="sc-month">Next 30 days ({terrain}): sunlight {(row.period.sun_disc_percent ?? row.period.sunlit_percent).toFixed(0)}%{row.period.sun_disc_percent != null ? ` (any part of the Sun ${row.period.sunlit_percent.toFixed(0)}%)` : ''}, Earth in view {row.period.earth_percent.toFixed(0)}%, longest night {spanText(row.period.longest_darkness_h * 3600e3)}{row.period.longest_darkness_lower_bound ? '+' : ''}.</p>}
        {cmp.s === 'loading' && !row && <p className="sc-month dim">Working out the real horizon here…</p>}
      </div>

      <div className="sc-actions">
        <button type="button" className="la-btn primary" onClick={stand}>{answer?.kind === 'window' && !open ? 'Stand here at the next window' : 'Stand here in 3D'}</button>
        <button type="button" className={`la-btn${inCompare ? ' on' : ''}`} aria-pressed={inCompare} onClick={onCompare}>{inCompare ? '✓ Comparing' : '+ Compare'}</button>
        <button type="button" className="la-btn" aria-expanded={more} onClick={() => setMore((m) => !m)}>{more ? 'Fewer details' : 'Details'}</button>
      </div>
      {more && <div className="sc-details">{details}</div>}
    </aside>
  );
}
