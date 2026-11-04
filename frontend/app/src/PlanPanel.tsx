// "When can I land here?" (an internal document (not published), step 2): two inputs, one button, an
// answer in one sentence, a timeline, the rules as chips and the caveats. Every number shown comes
// from /api/landing-windows or /api/check; nothing is computed or rounded into a claim here.
import { useEffect, useRef, useState } from 'react';
import { ApiError, checkSite, findLandingWindows, type CheckResult, type LandingResult, type UtcRange } from './api/plan';
import { formatUtc } from './state/format';

const SEARCH_DAYS = 60; // /api/check allows at most 60 days; both calls share one time axis
const DAY = 86400e3;

type Props = {
  siteId: string;
  siteName: string;
  live: boolean;
  cursorMs: number;
  /** A plan was run for [startMs, endMs): load sky geometry for it so the scene can follow. */
  onPlanned: (startMs: number, endMs: number) => void;
  /** Move the shared clock (scene lighting, dock) to this instant. */
  onJump: (ms: number) => void;
};

type State =
  | { kind: 'idle' }
  | { kind: 'loading'; since: number }
  | { kind: 'done'; landing: LandingResult; check: CheckResult; startMs: number }
  | { kind: 'error'; message: string };

function todayUtcDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function pct(ms: number, startMs: number): number {
  return Math.min(100, Math.max(0, ((ms - startMs) / (SEARCH_DAYS * DAY)) * 100));
}

function Bands({ ranges, startMs, cls }: { ranges: UtcRange[]; startMs: number; cls: string }) {
  return (
    <>
      {ranges.map((r) => {
        const a = pct(Date.parse(r.start_utc), startMs), b = pct(Date.parse(r.end_utc), startMs);
        return b > a ? <span key={r.start_utc} className={`la-band ${cls}`} style={{ left: `${a}%`, width: `${b - a}%` }} /> : null;
      })}
    </>
  );
}

// Colour plus a glyph or words, never colour alone: pass ✓, fail ✕, lower bound (the API says "at least").
const STATUS_TEXT: Record<string, string> = { pass: '✓', fail: '✕', unknown: '', no_limit: '' }; // unknown: the API text already says "at least"

export function PlanPanel({ siteId, siteName, live, cursorMs, onPlanned, onJump }: Props) {
  const [date, setDate] = useState(todayUtcDate);
  const [missionDays, setMissionDays] = useState(10);
  const [state, setState] = useState<State>({ kind: 'idle' });
  const [elapsed, setElapsed] = useState(0);
  const abort = useRef<AbortController | null>(null);

  // A different site starts fresh.
  useEffect(() => { abort.current?.abort(); setState({ kind: 'idle' }); }, [siteId]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    if (state.kind !== 'loading') return;
    const t = setInterval(() => setElapsed(Math.round((performance.now() - state.since) / 1000)), 500);
    return () => clearInterval(t);
  }, [state]);

  const run = async () => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    const startMs = Date.parse(`${date}T00:00:00Z`);
    setElapsed(0);
    setState({ kind: 'loading', since: performance.now() });
    onPlanned(startMs, startMs + SEARCH_DAYS * DAY);
    try {
      const [landing, check] = await Promise.all([
        findLandingWindows(siteId, startMs, SEARCH_DAYS, missionDays, ac.signal),
        checkSite(siteId, startMs, SEARCH_DAYS, ac.signal),
      ]);
      setState({ kind: 'done', landing, check, startMs });
      const first = landing.opportunities[0];
      if (first) onJump(Date.parse(first.best_touchdown_utc));
    } catch (e) {
      if ((e as Error).name === 'AbortError') return;
      const m = e instanceof ApiError ? `${e.message} (HTTP ${e.status})` : (e as Error).message;
      setState({ kind: 'error', message: m });
    }
  };

  if (!live) {
    return (
      <div className="la-plan">
        <p className="la-plan-note">Landing dates need the live backend. Run <code>./scripts/run_local.sh</code> to plan other dates.</p>
      </div>
    );
  }

  return (
    <div className="la-plan">
      <h3>When can a lander touch down here?</h3>
      <div className="la-plan-form">
        <label>
          <span>Start looking from</span>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
        </label>
        <label>
          <span>Mission length <b className="la-mono">{missionDays} days</b></span>
          <input type="range" min={1} max={14} step={1} value={missionDays} onChange={(e) => setMissionDays(Number(e.target.value))} />
        </label>
      </div>
      <button type="button" className="la-btn primary la-plan-go" onClick={run} disabled={state.kind === 'loading' || !date}>
        {state.kind === 'loading' ? 'Calculating…' : 'Find landing dates'}
      </button>

      {state.kind === 'loading' && (
        <p className="la-plan-note" role="status">
          Calculating sunlight and Earth visibility at {siteName} for {SEARCH_DAYS} days
          ({elapsed} s; real terrain takes longer the first time).
        </p>
      )}

      {state.kind === 'error' && <p className="la-plan-error" role="alert">{state.message}</p>}

      {state.kind === 'done' && (() => {
        const { landing, check, startMs } = state;
        const opp = landing.opportunities;
        const ticks = [0, 20, 40, 60];
        return (
          <div className="la-plan-result">
            <p className={`la-answer${opp.length ? ' good' : ' miss'}`}>{landing.summary[0]}</p>
            {landing.summary.slice(1).map((l) => <p key={l} className="la-plan-line">{l}</p>)}

            <div className="la-timeline" aria-label={`Next ${SEARCH_DAYS} days from ${date}`}>
              <div className="la-row"><span>Sunlight</span><div className="la-track"><Bands ranges={check.summary.bands.sun} startMs={startMs} cls="sun" /></div></div>
              <div className="la-row"><span>Earth in view</span><div className="la-track"><Bands ranges={check.summary.bands.earth} startMs={startMs} cls="earth" /></div></div>
              <div className="la-row"><span>Can land</span>
                <div className="la-track">
                  {opp.map((o) => {
                    const a = pct(Date.parse(o.touchdown_from_utc), startMs);
                    const b = Math.max(a + 0.8, pct(Date.parse(o.touchdown_until_utc), startMs));
                    return (
                      <button key={o.touchdown_from_utc} type="button" className="la-band land" style={{ left: `${a}%`, width: `${b - a}%` }}
                        title={`Touch down ${formatUtc(Date.parse(o.touchdown_from_utc))} to ${formatUtc(Date.parse(o.touchdown_until_utc))}`}
                        aria-label={`Landing window from ${formatUtc(Date.parse(o.touchdown_from_utc))}; show the best touchdown time`}
                        onClick={() => onJump(Date.parse(o.best_touchdown_utc))} />
                    );
                  })}
                </div>
              </div>
              <div className="la-row la-ticks"><span />
                <div className="la-track">
                  {ticks.map((d) => <i key={d} style={{ left: `${(d / SEARCH_DAYS) * 100}%` }}>{new Date(startMs + d * DAY).toISOString().slice(5, 10)}</i>)}
                  {cursorMs >= startMs && cursorMs <= startMs + SEARCH_DAYS * DAY && <b className="la-now" style={{ left: `${pct(cursorMs, startMs)}%` }} />}
                </div>
              </div>
            </div>

            <div className="la-numbers">
              <span><b className="la-mono">{Math.round(check.summary.numbers.sunlit_percent)}%</b> sunlit</span>
              <span><b className="la-mono">{Math.round(check.summary.numbers.earth_percent)}%</b> Earth in view</span>
              <span className="la-mode-tag">{check.chosen_settings.horizon_mode === 'terrain' ? 'Real terrain (LOLA)' : 'Flat horizon (no terrain)'}</span>
            </div>
            <div className="la-chips">
              {check.summary.limits.checks.map((c) => (
                <span key={c.key} className={`la-rule ${c.status}`}>
                  {c.label}: {STATUS_TEXT[c.status] ? `${STATUS_TEXT[c.status]} ` : ''}{c.text}
                </span>
              ))}
            </div>
            <ul className="la-caveats">
              {[...new Set([...landing.caveats, ...check.summary.caveats])].map((c) => <li key={c}>{c}</li>)}
            </ul>
          </div>
        );
      })()}
    </div>
  );
}
