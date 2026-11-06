// Right panel for the selected site (PRD Phase 2, F17/F18): the answer first, as a date and three
// readouts; every readout can be touched and moves the clock to where its number comes from.
// The API's sentences stay in tooltips and screen-reader text; the caveats stay visible.
import { useEffect, useState, type MouseEvent as RMouseEvent } from 'react';
import type { UtcRange, Verify } from '../api/plan';
import type { ReferenceSite } from '../data/source';
import { formatLat, formatLon } from '../state/format';
import { spanText, type SiteNow } from '../state/siteState';
import { CalIcon, ClockIcon, EarthIcon, SunIcon } from '../ui/Icons';
import { earthAfter, fixes, formatDuration, formatIn, type Answer } from './answer';
import { Calendar } from './Calendar';
import { EllipsePanel } from './EllipsePanel';
import { SEARCH_DAYS, utcMidnight, type PlanData, type PlanSettings } from './usePlan';

const DAY = 86400e3, SYNODIC_MS = 29.530589 * DAY;

type Props = {
  site: ReferenceSite;
  live: boolean;
  now: SiteNow | null;
  cursorMs: number;
  settings: PlanSettings;
  data: PlanData;
  answer: Answer | null;
  onSettings: (p: Partial<PlanSettings>) => void;
  onJump: (ms: number) => void;
  onSurface: (touchdownMs: number) => void;
  onClose: () => void;
  onProof: () => void;
  inCompare: boolean;
  onCompare: () => void;
  /** Only the expert parts (launch date, mission length, calendar, ellipse, caveats): the site card shows the rest. */
  details?: boolean;
};

const bigDate = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const timeOf = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
const utcShort = (iso: string) => `${iso.slice(5, 10)} ${iso.slice(11, 16)}`;

function positionTag(site: ReferenceSite): { text: string; warn?: boolean } | null {
  switch (site.position_kind) {
    case 'landed_hardware': return { text: 'Landed hardware' };
    case 'target_region_centre': return { text: 'Region centre, not a landing point', warn: true };
    default: return site.kind === 'literature_reference_point' ? { text: 'Literature reference point' } : null;
  }
}

/** The ring unrolled: 90 days of sunlight, Earth and landing windows on one axis. */
function Outlook({ settings, data, cursorMs, onJump, onSettings }: Pick<Props, 'settings' | 'data' | 'cursorMs' | 'onJump' | 'onSettings'>) {
  const start = settings.searchStartMs, span = SEARCH_DAYS * DAY;
  const pct = (ms: number) => Math.min(100, Math.max(0, ((ms - start) / span) * 100));
  const ready = data.status === 'ready';
  const bands = (r: UtcRange[] | undefined, cls: string) => r?.map((b) => {
    const a = pct(Date.parse(b.start_utc)), z = pct(Date.parse(b.end_utc));
    return z > a ? <span key={b.start_utc} className={`la-band ${cls}`} style={{ left: `${a}%`, width: `${z - a}%` }} /> : null;
  });
  const ticks: number[] = [];
  const s = new Date(start);
  for (let k = 1; k <= 3; k++) ticks.push(Date.UTC(s.getUTCFullYear(), s.getUTCMonth() + k, 1));
  const setKnob = (e: RMouseEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect();
    onSettings({ notBeforeMs: utcMidnight(start + ((e.clientX - b.left) / b.width) * span) });
  };
  return (
    <div className="la-outlook">
      <div className="la-orow"><span className="la-cap sun-c">Sun</span><div className="la-track">{ready && bands(data.bands?.sun, 'sun')}</div></div>
      <div className="la-orow"><span className="la-cap earth-c">Earth</span><div className="la-track">{ready && bands(data.bands?.earth, 'earth')}</div></div>
      <div className="la-orow">
        <span className="la-cap good-c">Land</span>
        <div className="la-track land" onClick={setKnob} title="Click to set the earliest launch">
          {ready && data.landing.opportunities.map((o) => {
            const a = pct(Date.parse(o.touchdown_from_utc)), z = Math.max(a + 0.6, pct(Date.parse(o.touchdown_until_utc)));
            const passed = Date.parse(o.touchdown_until_utc) < settings.notBeforeMs;
            return <button key={o.touchdown_from_utc} type="button" className={`la-band land${passed ? ' passed' : ''}`} style={{ left: `${a}%`, width: `${z - a}%` }}
              aria-label={`Landing window ${utcShort(o.touchdown_from_utc)} to ${utcShort(o.touchdown_until_utc)} UTC`}
              onClick={(e) => { e.stopPropagation(); onJump(Date.parse(o.best_touchdown_utc)); }} />;
          })}
          <b className="la-knobline" style={{ left: `${pct(settings.notBeforeMs)}%` }} />
          {cursorMs >= start && cursorMs <= start + span && <b className="la-cursorline" style={{ left: `${pct(cursorMs)}%` }} />}
        </div>
      </div>
      <div className="la-oticks">
        {ticks.map((t) => pct(t) < 96 && <i key={t} style={{ left: `${pct(t)}%` }}>{new Date(t).toLocaleDateString(undefined, { month: 'short', timeZone: 'UTC' })}</i>)}
      </div>
    </div>
  );
}

/** "Verify with NASA JPL": our Sun position next to a link to JPL Horizons' own table for the same point and second. */
function VerifyLine({ v }: { v: Verify }) {
  return (
    <p className="la-verify" title={v.note}>
      Sun at {utcShort(v.utc)} UTC: ours az {v.sun.ours_azimuth_deg.toFixed(2)}°, el <b>{v.sun.ours_elevation_deg.toFixed(2)}°</b>{' '}
      <a href={v.sun.horizons_url} target="_blank" rel="noopener noreferrer">Verify with NASA JPL ↗</a>
      {v.earth && <>{' '}Earth el {v.earth.ours_elevation_deg.toFixed(2)}° <a href={v.earth.horizons_url} target="_blank" rel="noopener noreferrer">JPL ↗</a></>}
      <span className="la-dim"> {v.note}</span>
    </p>
  );
}

export function SitePanel({ site, live, now, cursorMs, settings, data, answer, onSettings, onJump, onSurface, onClose, onProof, inCompare, onCompare, details = false }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [cal, setCal] = useState(false);
  useEffect(() => {
    if (data.status !== 'loading') return;
    const since = data.since;
    const t = setInterval(() => setElapsed(Math.round((performance.now() - since) / 1000)), 500);
    return () => clearInterval(t);
  }, [data]);

  const tag = positionTag(site);
  const custom = site.site_id.startsWith('point:');
  // Earthset or Earthrise after the best touchdown, from the terrain check's Earth bands.
  const earthEv = data.status === 'ready' && data.bands && answer?.kind === 'window' ? earthAfter(data.bands.earth, answer.bestMs) : null;
  const polar = site.latitude_deg <= -75;
  const quick: { label: string; act: () => void }[] = [
    { label: 'Today', act: () => { const t = utcMidnight(Date.now()); onSettings({ searchStartMs: t, notBeforeMs: t }); } },
    { label: '+1 lunar day', act: () => {
      const k = settings.notBeforeMs + SYNODIC_MS;
      if (k > settings.searchStartMs + SEARCH_DAYS * DAY) onSettings({ searchStartMs: utcMidnight(k), notBeforeMs: k });
      else onSettings({ notBeforeMs: k });
    } },
    { label: 'Next year', act: () => onSettings({ searchStartMs: settings.searchStartMs + 365 * DAY, notBeforeMs: settings.notBeforeMs + 365 * DAY }) },
    { label: 'Artemis era 2028', act: () => { const t = Date.UTC(2028, 0, 1); onSettings({ searchStartMs: t, notBeforeMs: t }); } },
  ];

  return (
    <section className="la-carto-body site" aria-label={site.name}>
      <div className="la-side-scroll">
        {!details && (
        <section className="la-sec">
          <div className="la-headrow">
            <button type="button" className="la-back" onClick={onClose} aria-label="All sites, whole Moon (Esc)">‹ All sites</button>
            <button type="button" className={`la-addcmp${inCompare ? ' on' : ''}`} aria-pressed={inCompare} onClick={onCompare}>
              {inCompare ? '✓ In compare' : '+ Compare'}
            </button>
          </div>
          <div className="la-site-head">
            <h2>{site.name}</h2>
            <span className="co">{formatLat(site.latitude_deg)}  {formatLon(site.longitude_deg)}{site.group ? ` · ${site.group}` : ''}</span>
            <div className="la-tags">
              {custom ? (
                <>
                  <span className="la-tag">Your point</span>
                  <span className="la-tag warn" title="Points you click use the 240 m regional terrain map only (no 5 m tiles); outside it, a flat horizon.">
                    {data.status === 'ready' ? (data.horizonMode === 'terrain' ? '240 m terrain' : 'flat horizon, no terrain map here') : 'terrain: 240 m map near the pole'}
                  </span>
                </>
              ) : (
                <>
                  <span className="la-tag">Reference site, not official</span>
                  {tag && <span className={`la-tag${tag.warn ? ' warn' : ''}`}>{tag.text}</span>}
                </>
              )}
            </div>
          </div>
          {now && (
            <p className="la-nowline" title="Sun and Earth over flat ground at the clock's time; hills are not included in this line. The landing answer below uses terrain.">
              <i className={`la-sw ${now.day ? 'day' : 'night'}`} aria-hidden="true" />
              <span><b className={now.day ? 'sun-c' : undefined}>{now.day ? 'Day' : 'Night'}</b> at the clock's time, Sun <b>{now.sunElDeg.toFixed(1)}°</b>
                {now.nextChangeMs !== null ? <>, {now.day ? 'sunset' : 'sunrise'} in <b>{spanText(now.nextChangeMs - cursorMs)}</b></> : <>, no {now.day ? 'sunset' : 'sunrise'} for {spanText(now.horizonMs - cursorMs)}+</>}.
                {' '}Earth <b className={now.earthUp ? 'earth-c' : undefined}>{now.earthElDeg.toFixed(1)}°</b>
                {now.earthNextMs !== null ? <>, {now.earthUp ? 'Earthset' : 'Earthrise'} in <b>{spanText(now.earthNextMs - cursorMs)}</b></> : <>, {now.earthUp ? 'no Earthset' : 'no Earthrise'} for {spanText(now.horizonMs - cursorMs)}+</>}
                <span className="la-dim"> (flat ground)</span></span>
            </p>
          )}
        </section>
        )}

        {!live ? (
          <section className="la-sec"><p className="la-note">Landing dates need the live backend: run <code>./scripts/run_local.sh</code>.</p></section>
        ) : (
          <>
            {!details && (
            <section className="la-sec" aria-live="polite">
              {data.status === 'loading' && (
                <div className="la-loading" role="status">
                  <span className="la-cap">Next landing window</span>
                  <span className="la-big muted">Searching…</span>
                  <div className="la-bar" />
                  <span className="la-note">{SEARCH_DAYS} days at {polar ? 'real terrain' : 'this site'} · {elapsed} s{polar && elapsed > 8 ? ' · terrain runs take longer the first time' : ''}</span>
                </div>
              )}
              {data.status === 'error' && <p className="la-err" role="alert">{data.message}</p>}

              {data.status === 'ready' && answer?.kind === 'window' && (
                <>
                  <span className="sr-only">{data.landing.summary[0]}</span>
                  <span className="la-cap good-c">Next landing window</span>
                  <button type="button" className="la-big" onClick={() => onJump(answer.bestMs)} title={data.landing.summary[0]}>
                    <span>{bigDate(answer.bestMs)}</span> <small>{timeOf(answer.bestMs)}</small>
                  </button>
                  <span className="la-range">touchdown {utcShort(answer.opportunity.touchdown_from_utc)} → {utcShort(answer.opportunity.touchdown_until_utc)} UTC · Sun {answer.opportunity.sun_above_horizon_at_best_deg !== undefined ? `${answer.opportunity.sun_above_horizon_at_best_deg.toFixed(1)}° above the horizon (${answer.opportunity.sun_elevation_at_best_deg.toFixed(1)}° above level)` : `${answer.opportunity.sun_elevation_at_best_deg.toFixed(1)}°`} at best</span>
                  {answer.opportunity.verify && <VerifyLine v={answer.opportunity.verify} />}
                  <div className="la-tiles">
                    <button type="button" className="la-tile" title="Daylight left after touchdown. Click to see sunset."
                      onClick={() => onJump(answer.opportunity.sunset_utc && answer.bestMs === Date.parse(answer.opportunity.best_touchdown_utc)
                        ? Date.parse(answer.opportunity.sunset_utc) : answer.bestMs + answer.daylightH * 3600e3)}>
                      <span className="la-cap sun-c"><SunIcon size={12} />Daylight</span>
                      <b>{formatDuration(answer.daylightH, answer.daylightIsLowerBound)}</b>
                    </button>
                    <button type="button" className="la-tile" title="Share of the mission with Earth above the horizon; and when Earth next sets or rises after touchdown (terrain). Click to see it."
                      onClick={() => onJump(earthEv ? earthEv.ms : answer.bestMs)}>
                      <span className="la-cap earth-c"><EarthIcon size={12} />Earth</span>
                      <b>{Math.round(answer.earthPct)}%</b>
                      <small>{earthEv ? `${earthEv.event} +${spanText(earthEv.ms - answer.bestMs)}` : data.bands ? 'no change in 60 d' : '…'}</small>
                    </button>
                    <button type="button" className="la-tile" title="From now to touchdown" onClick={() => onJump(answer.bestMs)}>
                      <span className="la-cap"><ClockIcon size={12} />Until</span>
                      <b>{formatIn(answer.inDays)}</b>
                    </button>
                  </div>
                  <div className="la-actions">
                    <button type="button" className="la-btn primary" onClick={() => onSurface(answer.bestMs)}>Stand there at touchdown</button>
                    <button type="button" className="la-btn" onClick={() => onSettings({ notBeforeMs: answer.untilMs + 60e3 })}>Next window</button>
                  </div>
                </>
              )}

              {data.status === 'ready' && answer?.kind === 'miss' && (
                <>
                  <span className="sr-only">{data.landing.summary.join(' ')}</span>
                  <span className="la-cap bad-c">No landing window in {SEARCH_DAYS} days</span>
                  <button type="button" className="la-big muted" onClick={() => onJump(answer.touchdownMs)} title={data.landing.summary.join(' ')}>
                    Closest: {bigDate(answer.touchdownMs)}
                  </button>
                  <div className="la-tiles" style={{ gridTemplateColumns: '1fr' }}>
                    <div className="la-tile static">
                      <span className="la-cap sun-c"><SunIcon size={12} />Daylight after touchdown</span>
                      <b>{formatDuration(answer.daylightH)} of {formatDuration(answer.neededH)}</b>
                    </div>
                  </div>
                  <div className="la-quick">
                    <span className="la-cap" style={{ alignSelf: 'center' }}>Try</span>
                    {fixes(answer, settings.missionDays, settings.maxSunDeg).map((f) => (
                      <button key={f.label} type="button" className="la-q fix" onClick={() => onSettings({
                        ...(f.missionDays !== undefined ? { missionDays: f.missionDays } : {}),
                        ...(f.maxSunDeg !== undefined ? { maxSunDeg: f.maxSunDeg } : {}) })}>{f.label}</button>
                    ))}
                  </div>
                  {data.landing.closest_miss?.verify && <VerifyLine v={data.landing.closest_miss.verify} />}
                  <button type="button" className="la-btn" onClick={() => onSurface(answer.touchdownMs)}>Stand there anyway</button>
                </>
              )}
              {data.status === 'ready' && answer?.kind === 'none' && <p className="la-note">{data.landing.summary.join(' ')}</p>}
            </section>
            )}
            {details && answer?.kind === 'window' && answer.opportunity.verify && <section className="la-sec"><VerifyLine v={answer.opportunity.verify} /></section>}

            <section className="la-sec">
              <div className="la-ctl">
                <span className="la-cap">Mission</span>
                <div className="la-step" role="group" aria-label="Mission length">
                  <button type="button" aria-label="One day shorter" onClick={() => onSettings({ missionDays: settings.missionDays - 1 })}>−</button>
                  <b>{settings.missionDays} d</b>
                  <button type="button" aria-label="One day longer" onClick={() => onSettings({ missionDays: settings.missionDays + 1 })}>+</button>
                </div>
                <span className="la-cap">Launch after</span>
                <button type="button" className={`la-datebtn${cal ? ' on' : ''}`} aria-expanded={cal} onClick={() => setCal((c) => !c)}>
                  <CalIcon />{new Date(settings.notBeforeMs).toISOString().slice(0, 10)}
                </button>
              </div>
              {cal && <Calendar settings={settings} data={data} onSettings={onSettings} onClose={() => setCal(false)} />}
              <div className="la-quick">{quick.map((q) => <button key={q.label} type="button" className="la-q" onClick={q.act}>{q.label}</button>)}</div>
              <Outlook settings={settings} data={data} cursorMs={cursorMs} onJump={onJump} onSettings={onSettings} />
              <span className="la-note" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                Drag the knob on the ring around the site, or click the Land row, to set the earliest launch. Wheel on the ring: ±1 day (Shift: ±1 lunar day).
              </span>
            </section>

            {site.latitude_deg <= -60 && !custom && (
              <EllipsePanel siteId={site.site_id}
                startMs={answer?.kind === 'window' ? Math.floor(answer.bestMs / 3600e3) * 3600e3 : settings.searchStartMs} />
            )}

            {data.status === 'ready' && (
              <section className="la-sec">
                <span className="la-cap">{data.horizonMode === 'terrain' ? 'Horizon: real terrain (LOLA)' : 'Horizon: flat (no terrain here)'}</span>
                <ul className="la-caveats">{data.landing.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
              </section>
            )}
          </>
        )}

        <section className="la-sec">
          <button type="button" className="la-proofbtn" onClick={onProof}>
            <b>{polar ? '5/6' : '6/7'}</b>
            <span>{polar ? 'Shadow method checked against LRO photos' : 'Model checked against real missions'}</span>
            <small>open the evidence</small>
          </button>
          {site.source_url && <a className="la-link" href={site.source_url} target="_blank" rel="noreferrer">Coordinate source</a>}
        </section>
      </div>
    </section>
  );
}
