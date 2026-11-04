// Phase 2 Answer card: the answer first, as a date and chips (no sentences on the main surface;
// the API's summary sentence is kept for screen readers and the tooltip). Tapping a chip moves the
// clock to the moment that number comes from.
import { useEffect, useState } from 'react';
import type { UtcRange } from '../api/plan';
import { fixes, formatDuration, formatIn, type Answer } from './answer';
import { SEARCH_DAYS, utcMidnight, type PlanData, type PlanSettings } from './usePlan';

const DAY = 86400e3, SYNODIC_MS = 29.530589 * DAY;

type Props = {
  siteName: string;
  live: boolean;
  settings: PlanSettings;
  data: PlanData;
  answer: Answer | null;
  onSettings: (p: Partial<PlanSettings>) => void;
  onJump: (ms: number) => void;
  onFlyDown: (ms: number) => void;
};

const bigDate = (ms: number) => {
  const d = new Date(ms), sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', ...(sameYear ? {} : { year: 'numeric' }) });
};
const timeOf = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

/** The ring unrolled, for narrow screens (PRD: same colours, same meaning). */
function Strip({ settings, data, onJump }: { settings: PlanSettings; data: PlanData; onJump: (ms: number) => void }) {
  if (data.status !== 'ready') return null;
  const start = settings.searchStartMs, span = SEARCH_DAYS * DAY;
  const pct = (ms: number) => Math.min(100, Math.max(0, ((ms - start) / span) * 100));
  const bands = (r: UtcRange[], cls: string) => r.map((b) => {
    const a = pct(Date.parse(b.start_utc)), z = pct(Date.parse(b.end_utc));
    return z > a ? <span key={b.start_utc} className={`la-band ${cls}`} style={{ left: `${a}%`, width: `${z - a}%` }} /> : null;
  });
  return (
    <div className="la-strip">
      {data.bands && <div className="la-track">{bands(data.bands.sun, 'sun')}</div>}
      {data.bands && <div className="la-track">{bands(data.bands.earth, 'earth')}</div>}
      <div className="la-track">
        {data.landing.opportunities.map((o) => {
          const a = pct(Date.parse(o.touchdown_from_utc)), z = Math.max(a + 1, pct(Date.parse(o.touchdown_until_utc)));
          return <button key={o.touchdown_from_utc} type="button" className="la-band land" style={{ left: `${a}%`, width: `${z - a}%` }}
            aria-label={`Landing window from ${o.touchdown_from_utc.slice(0, 10)}`} onClick={() => onJump(Date.parse(o.best_touchdown_utc))} />;
        })}
        <b className="la-now" style={{ left: `${pct(settings.notBeforeMs)}%` }} />
      </div>
    </div>
  );
}

export function AnswerCard({ siteName, live, settings, data, answer, onSettings, onJump, onFlyDown }: Props) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (data.status !== 'loading') return;
    const since = data.since;
    const t = setInterval(() => setElapsed(Math.round((performance.now() - since) / 1000)), 500);
    return () => clearInterval(t);
  }, [data]);

  if (!live) {
    return <p className="la-plan-note">Landing dates need the live backend: run <code>./scripts/run_local.sh</code>.</p>;
  }

  const quick: { label: string; act: () => void }[] = [
    { label: 'Today', act: () => { const t = utcMidnight(Date.now()); onSettings({ searchStartMs: t, notBeforeMs: t }); } },
    ...(answer?.kind === 'window' ? [{ label: 'Next window', act: () => onSettings({ notBeforeMs: answer.untilMs + 60e3 }) }] : []),
    { label: '+1 lunar day', act: () => {
      const k = settings.notBeforeMs + SYNODIC_MS;
      if (k > settings.searchStartMs + SEARCH_DAYS * DAY) onSettings({ searchStartMs: utcMidnight(k), notBeforeMs: k });
      else onSettings({ notBeforeMs: k });
    } },
    { label: 'Same day next year', act: () => onSettings({ searchStartMs: settings.searchStartMs + 365 * DAY, notBeforeMs: settings.notBeforeMs + 365 * DAY }) },
    { label: 'Artemis era (2028)', act: () => { const t = Date.UTC(2028, 0, 1); onSettings({ searchStartMs: t, notBeforeMs: t }); } },
  ];

  return (
    <div className="la-answer-card">
      {data.status === 'loading' && (
        <div className="la-skeleton" role="status">
          <span className="la-eyebrow">Next landing</span>
          <span className="la-big muted">…</span>
          <span className="la-plan-note">Finding landing dates at {siteName} · {elapsed} s</span>
        </div>
      )}
      {data.status === 'error' && <p className="la-plan-error" role="alert">{data.message}</p>}

      {data.status === 'ready' && answer?.kind === 'window' && (
        <div className="la-answer-body" title={data.landing.summary[0]}>
          <span className="sr-only">{data.landing.summary[0]}</span>
          <span className="la-eyebrow">Next landing</span>
          <button type="button" className="la-big" onClick={() => onJump(answer.bestMs)} aria-label={`Show touchdown at ${bigDate(answer.bestMs)}`}>
            {bigDate(answer.bestMs)} <small className="la-mono">{timeOf(answer.bestMs)}</small>
          </button>
          <div className="la-chips">
            <button type="button" className="la-chip2 sun" title="Daylight left after touchdown; tap to see sunset"
              onClick={() => onJump(answer.opportunity.sunset_utc && answer.bestMs === Date.parse(answer.opportunity.best_touchdown_utc)
                ? Date.parse(answer.opportunity.sunset_utc) : answer.bestMs + answer.daylightH * 3600e3)}>
              ☀ {formatDuration(answer.daylightH, answer.daylightIsLowerBound)}
            </button>
            <button type="button" className="la-chip2 earth" title="Earth in view during the mission" onClick={() => onJump(answer.bestMs)}>
              🌍 {Math.round(answer.earthPct)}%
            </button>
            <button type="button" className="la-chip2" title="From now to touchdown" onClick={() => onJump(answer.bestMs)}>
              ⏱ {formatIn(answer.inDays)}
            </button>
          </div>
          <div className="la-actions">
            <button type="button" className="la-btn primary" onClick={() => onFlyDown(answer.bestMs)}>Go there at touchdown</button>
            <button type="button" className="la-btn" onClick={() => onSettings({ notBeforeMs: answer.untilMs + 60e3 })}>Another window</button>
          </div>
        </div>
      )}

      {data.status === 'ready' && answer?.kind === 'miss' && (
        <div className="la-answer-body" title={data.landing.summary.join(' ')}>
          <span className="sr-only">{data.landing.summary.join(' ')}</span>
          <span className="la-eyebrow">No landing in {SEARCH_DAYS} days</span>
          <button type="button" className="la-big muted" onClick={() => onJump(answer.touchdownMs)}>Closest {bigDate(answer.touchdownMs)}</button>
          <div className="la-chips">
            <span className="la-chip2 sun">☀ {formatDuration(answer.daylightH)} of {formatDuration(answer.neededH)}</span>
            {fixes(answer, settings.missionDays, settings.maxSunDeg).map((f) => (
              <button key={f.label} type="button" className="la-chip2 fix" onClick={() => onSettings({
                ...(f.missionDays !== undefined ? { missionDays: f.missionDays } : {}),
                ...(f.maxSunDeg !== undefined ? { maxSunDeg: f.maxSunDeg } : {}) })}>{f.label}</button>
            ))}
          </div>
        </div>
      )}
      {data.status === 'ready' && answer?.kind === 'none' && <p className="la-plan-note">{data.landing.summary.join(' ')}</p>}

      <div className="la-mission" role="group" aria-label="Mission length">
        <span>Mission</span>
        <button type="button" className="la-step" aria-label="One day shorter" onClick={() => onSettings({ missionDays: settings.missionDays - 1 })}>−</button>
        <b className="la-mono">{settings.missionDays} d</b>
        <button type="button" className="la-step" aria-label="One day longer" onClick={() => onSettings({ missionDays: settings.missionDays + 1 })}>+</button>
        <span className="la-spacer" />
        <span className="la-hint">or drag the ring</span>
      </div>

      <Strip settings={settings} data={data} onJump={onJump} />

      <div className="la-quick">
        {quick.map((q) => <button key={q.label} type="button" className="la-chip2 quick" onClick={q.act}>{q.label}</button>)}
      </div>

      {data.status === 'ready' && (
        <div className="la-foot">
          <span className="la-mode-tag">{data.horizonMode === 'terrain' ? 'Real terrain (LOLA)' : 'Flat horizon (no terrain)'}</span>
          <ul className="la-caveats">{data.landing.caveats.map((c) => <li key={c}>{c}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
