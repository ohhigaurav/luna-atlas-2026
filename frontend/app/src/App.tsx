// Luna Atlas shell: the 3D globe (GlobeView) with the HUD floating over it.
// Every lit pixel comes from /api/sky-geometry (or its baked copy in static mode); the HUD only
// labels what the scene shows and never invents a number.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './hud.css';
import { GlobeView, type GlobeHandle } from './GlobeView';
import { AnswerCard } from './plan/AnswerCard';
import { LandingRing } from './plan/LandingRing';
import { SEARCH_DAYS, usePlan } from './plan/usePlan';
import { loadDataSource, type DataSource, type ReferenceSite } from './data/source';
import { fetchSkyGeometry, sampleTimesMs, skyAt, type SkyGeometry } from './api/sky';
import { isoZ } from './api/plan';
import type { PinSite } from './engine/pins';
import { formatLat, formatLocal, formatLon, formatUtc } from './state/format';
import { litFraction, moonPhase } from './state/phase';

const SPEEDS = [3600, 86400] as const; // simulated seconds per real second: 1 h/s, 1 day/s
const STEP_MS = 30 * 60e3;
const HOUR = 3600e3;

function positionTag(site: ReferenceSite): { text: string; warn?: boolean } | null {
  switch (site.position_kind) {
    case 'landed_hardware': return { text: 'Landed hardware' };
    case 'target_region_centre': return { text: 'Region centre, not a landing point', warn: true };
    case 'literature_reference_point': return { text: 'Literature reference point' };
    default: return site.kind === 'literature_reference_point' ? { text: 'Literature reference point' } : null;
  }
}

/** "14:22 IST · 08:52 UTC" style clock text for the top bar. */
function clockText(ms: number): string {
  const local = new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
  return `${local} · ${new Date(ms).toISOString().slice(11, 16)} UTC`;
}

export default function App() {
  const [data, setData] = useState<DataSource | null>(null);
  const [sky, setSky] = useState<SkyGeometry | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReferenceSite | null>(null);
  const [introDone, setIntroDone] = useState(false);
  const [cursorMs, setCursorMs] = useState(0);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(SPEEDS[0]);
  const [playing, setPlaying] = useState(false);
  const [followNow, setFollowNow] = useState(false);
  const cursorRef = useRef(0);
  const globe = useRef<GlobeHandle>(null);
  const reducedMotion = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, []);

  useEffect(() => {
    loadDataSource().then(
      (d) => {
        cursorRef.current = d.initialCursorMs; setCursorMs(d.initialCursorMs);
        setSky(d.sky); setData(d); setFollowNow(d.mode === 'live');
      },
      (e: unknown) => setFatal(e instanceof Error ? e.message : String(e)),
    );
  }, []);

  const live = data?.mode === 'live';
  const window_ = useMemo(() => sky && {
    start: Date.parse(sky.settings.start_utc),
    end: Date.parse(sky.settings.end_utc),
  }, [sky]);
  const times = useMemo(() => (sky ? sampleTimesMs(sky) : null), [sky]);

  const setCursor = useCallback((ms: number) => { cursorRef.current = ms; setCursorMs(ms); }, []);

  // Real time: in live mode the clock follows the wall clock until the user scrubs, plays or plans.
  useEffect(() => {
    if (!followNow) return;
    const tick = () => setCursor(Date.now());
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [followNow, setCursor]);

  // Playback advances the shared clock; the label/slider refresh at ~8 Hz, the scene every frame.
  useEffect(() => {
    if (!playing || !window_) return;
    let raf = 0, last = performance.now(), lastUi = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const next = cursorRef.current + dt * speed * 1000;
      if (next >= window_.end) { setCursor(window_.end); setPlaying(false); return; }
      cursorRef.current = next;
      if (now - lastUi > 120) { lastUi = now; setCursorMs(next); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, window_, setCursor]);

  /** Load sky geometry for [startMs, endMs) so the scene can follow a plan or "now". */
  const loadSky = useCallback((startMs: number, endMs: number) => {
    fetchSkyGeometry(isoZ(startMs), isoZ(endMs), 30).then(setSky, (e: Error) => setError(`Sky geometry: ${e.message}`));
  }, []);

  const goNow = useCallback(() => {
    setPlaying(false);
    const now = Date.now();
    if (live && window_ && (now < window_.start || now > window_.end)) loadSky(now - 2 * HOUR, now + 2 * 24 * HOUR);
    setFollowNow(true);
  }, [live, window_, loadSky]);

  const onSelect = useCallback((s: PinSite | null) => setSelected(s as ReferenceSite | null), []);
  const plan = usePlan(selected?.site_id ?? null, live, Date.now());
  const screenOf = useCallback((s: PinSite) => globe.current?.screenOf(s) ?? null, []);
  const jump = useCallback((ms: number) => { setFollowNow(false); setPlaying(false); setCursor(ms); }, [setCursor]);

  // The ring covers SEARCH_DAYS from its start: load sky geometry for that window so any jump is lit.
  const planStart = plan.settings.searchStartMs;
  useEffect(() => {
    if (!selected || !live) return;
    loadSky(planStart, planStart + SEARCH_DAYS * 86400e3);
  }, [selected, live, planStart, loadSky]);
  const onIntroDone = useCallback(() => setIntroDone(true), []);
  const byId = useCallback((id: string) => data?.sites.find((s) => s.site_id === id), [data]);

  // How much of the Moon is lit as seen from Earth at the cursor (from the API's Sun/Earth vectors).
  const phase = useMemo(() => {
    if (!sky || !times) return null;
    const a = skyAt(sky, times, cursorMs), b = skyAt(sky, times, cursorMs + HOUR);
    return moonPhase(litFraction(a.sunDir, a.earthDir), litFraction(b.sunDir, b.earthDir));
  }, [sky, times, cursorMs]);

  if (fatal) {
    return (
      <div className="la-app">
        <div className="la-error la-chip warn" role="alert">{fatal}</div>
      </div>
    );
  }
  if (!data || !sky || !window_) {
    return <div className="la-app"><div className="la-skip la-chip" role="status">Loading the Moon…</div></div>;
  }

  const im2 = byId('reference-clps-im-2');
  const apollo = byId('reference-apollo-11');
  const dateLabel = live ? 'right now' : `on ${formatUtc(data.initialCursorMs)}`;

  return (
    <div className="la-app">
      <GlobeView
        sites={data.sites}
        sky={sky}
        cursorRef={cursorRef}
        reducedMotion={reducedMotion}
        onSelect={onSelect}
        onIntroDone={onIntroDone}
        onError={setError}
        handle={globe}
      />

      <header className="la-top">
        <div className="la-brand">
          <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
            <circle cx="13" cy="13" r="11" fill="#1a2232" />
            <path d="M13,2 A11,11 0 0,1 13,24 A5,11 0 0,1 13,2 Z" fill="#d9d4cb" />
          </svg>
          Luna Atlas
        </div>
        <span className="la-chip la-mode">
          {live ? 'Live · Sun and Earth from JPL SPICE' : `Precomputed bundle · ${data.sky.settings.start_utc.slice(0, 10)} to ${data.sky.settings.end_utc.slice(0, 10)}`}
        </span>
        <span className="la-spacer" />
        {phase && (
          <button type="button" className="la-chip la-phase" onClick={() => globe.current?.viewFromEarth()}
            title="Fly to Earth's direction: the Moon as it looks in your sky at this time">
            <span className="la-mono">{Math.round(phase.fraction * 100)}%</span> lit from Earth · {phase.name}
          </button>
        )}
        <span className={`la-chip la-mono${followNow ? ' live' : ''}`} title={formatUtc(cursorMs)}>
          {followNow && <i className="la-dot" aria-hidden="true" />}{clockText(cursorMs)}
        </span>
      </header>

      <section className={`la-hero${selected || !introDone ? ' hidden' : ''}`} aria-hidden={!!selected || !introDone}>
        <span className="la-eyebrow">The Moon, lit as it is {dateLabel}</span>
        <h1>When can you land on the Moon?</h1>
        <p>
          Pick a landing site. Luna Atlas finds the days when the Sun stays up for your whole mission and
          Earth is in view for the radio link, from JPL SPICE ephemerides and NASA's laser altimeter.
        </p>
        <div className="la-actions">
          {im2 && <button type="button" className="la-btn primary" onClick={() => globe.current?.flyToSite(im2)}>Plan a south-pole landing (IM-2)</button>}
          {apollo && <button type="button" className="la-btn" onClick={() => globe.current?.flyToSite(apollo)}>Apollo 11</button>}
        </div>
        <span className="la-hint">Or click any site on the Moon · drag to turn · Esc for the whole Moon</span>
      </section>

      {selected && (
        <aside className="la-card" aria-label={selected.name}>
          <span className="la-eyebrow">{selected.group ?? 'South polar reference points'}</span>
          <h2>{selected.name}</h2>
          <span className="meta la-mono">{formatLat(selected.latitude_deg)}, {formatLon(selected.longitude_deg)}</span>
          {/* Terrain vs flat is decided by the backend per run; the plan result shows which was used. */}
          <div className="la-tags">
            <span className="la-tag">Reference site, not official</span>
            {(() => { const t = positionTag(selected); return t && <span className={`la-tag${t.warn ? ' warn' : ''}`}>{t.text}</span>; })()}
          </div>
          <AnswerCard
            siteName={selected.name}
            live={live}
            settings={plan.settings}
            data={plan.data}
            answer={plan.answer}
            onSettings={plan.update}
            onJump={jump}
            onFlyDown={(ms) => { jump(ms); globe.current?.flyToSite(selected); }}
          />
          <div className="row">
            {selected.source_url && <a className="la-hint" href={selected.source_url} target="_blank" rel="noreferrer">Coordinate source</a>}
            <span className="la-spacer" />
            <button type="button" className="la-btn" onClick={() => globe.current?.flyHome()}>Whole Moon (Esc)</button>
          </div>
        </aside>
      )}

      {selected && live && (
        <LandingRing site={selected} screenOf={screenOf} settings={plan.settings} data={plan.data}
          answer={plan.answer} onSettings={plan.update} onJump={jump} />
      )}

      {!introDone && !reducedMotion && (
        <button type="button" className="la-skip la-chip" onClick={() => globe.current?.skipIntro()}>Skip intro (any key)</button>
      )}

      {introDone && (
        <section className="la-dock" aria-label="Time">
          <button type="button" className="la-play" aria-label={playing ? 'Pause' : 'Play'} onClick={() => { setFollowNow(false); setPlaying((p) => !p); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
              {playing ? <path d="M6 4h4v16H6zM14 4h4v16h-4z" /> : <path d="M7 4l13 8-13 8z" />}
            </svg>
          </button>
          <button type="button" className="la-chip la-mono la-speed" onClick={() => setSpeed((s) => (s === SPEEDS[0] ? SPEEDS[1] : SPEEDS[0]))}>
            {speed === 3600 ? '1 h/s' : '1 day/s'}
          </button>
          <input
            type="range" aria-label="Time" min={window_.start} max={window_.end} step={STEP_MS}
            value={Math.min(window_.end, Math.max(window_.start, cursorMs))}
            onChange={(e) => { setFollowNow(false); setPlaying(false); setCursor(Number(e.target.value)); }}
          />
          <span className="la-mono la-dock-date">{formatLocal(cursorMs)}</span>
          {live && <button type="button" className={`la-chip${followNow ? ' live' : ''}`} onClick={goNow}>Now</button>}
        </section>
      )}

      {error && <div className="la-error la-chip warn" role="alert">{error}</div>}

      <footer className="la-credits">
        <span className="la-chip">Moon: NASA SVS CGI Moon Kit (LROC colour, LOLA relief)</span>
        <span className="la-chip">Earth: NASA Blue Marble, rotation not modelled</span>
        <span className="la-chip">Star field: illustrative</span>
      </footer>
    </div>
  );
}
