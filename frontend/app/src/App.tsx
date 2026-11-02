// Luna Atlas shell: the 3D globe (GlobeView) with the HUD floating over it.
// Every lit pixel comes from /api/sky-geometry (or its baked copy in static mode); the HUD only
// labels what the scene shows and never invents a number.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import './hud.css';
import { GlobeView, type GlobeHandle } from './GlobeView';
import { loadDataSource, type DataSource, type ReferenceSite } from './data/source';
import type { PinSite } from './engine/pins';
import { formatLat, formatLocal, formatLon, formatUtc } from './state/format';

const SPEEDS = [3600, 86400] as const; // simulated seconds per real second: 1 h/s, 1 day/s
const STEP_MS = 30 * 60e3;

function positionTag(site: ReferenceSite): { text: string; warn?: boolean } | null {
  switch (site.position_kind) {
    case 'landed_hardware': return { text: 'Landed hardware' };
    case 'target_region_centre': return { text: 'Region centre, not a landing point', warn: true };
    case 'literature_reference_point': return { text: 'Literature reference point' };
    default: return site.kind === 'literature_reference_point' ? { text: 'Literature reference point' } : null;
  }
}

export default function App() {
  const [data, setData] = useState<DataSource | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ReferenceSite | null>(null);
  const [introDone, setIntroDone] = useState(false);
  const [cursorMs, setCursorMs] = useState(0);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(SPEEDS[0]);
  const [playing, setPlaying] = useState(false);
  const cursorRef = useRef(0);
  const globe = useRef<GlobeHandle>(null);
  const reducedMotion = useMemo(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false, []);

  useEffect(() => {
    loadDataSource().then(
      (d) => { cursorRef.current = d.initialCursorMs; setCursorMs(d.initialCursorMs); setData(d); },
      (e: unknown) => setFatal(e instanceof Error ? e.message : String(e)),
    );
  }, []);

  const window_ = useMemo(() => data && {
    start: Date.parse(data.sky.settings.start_utc),
    end: Date.parse(data.sky.settings.end_utc),
  }, [data]);

  // Playback advances the shared clock; the label/slider refresh at ~8 Hz, the scene every frame.
  useEffect(() => {
    if (!playing || !window_) return;
    let raf = 0, last = performance.now(), lastUi = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const next = cursorRef.current + dt * speed * 1000;
      if (next >= window_.end) { cursorRef.current = window_.end; setCursorMs(window_.end); setPlaying(false); return; }
      cursorRef.current = next;
      if (now - lastUi > 120) { lastUi = now; setCursorMs(next); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, window_]);

  const setCursor = useCallback((ms: number) => { cursorRef.current = ms; setCursorMs(ms); }, []);
  const onSelect = useCallback((s: PinSite | null) => setSelected(s as ReferenceSite | null), []);
  const onIntroDone = useCallback(() => setIntroDone(true), []);
  const byId = useCallback((id: string) => data?.sites.find((s) => s.site_id === id), [data]);

  if (fatal) {
    return (
      <div className="la-app">
        <div className="la-error la-chip warn" role="alert">{fatal}</div>
      </div>
    );
  }
  if (!data || !window_) {
    return <div className="la-app"><div className="la-skip la-chip" role="status">Loading the Moon…</div></div>;
  }

  const apollo = byId('reference-apollo-11');
  const im2 = byId('reference-clps-im-2');
  const live = data.mode === 'live';
  const dateLabel = live ? 'right now' : `on ${formatUtc(data.initialCursorMs)}`;

  return (
    <div className="la-app">
      <GlobeView
        sites={data.sites}
        sky={data.sky}
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
        <span className="la-chip la-mono" title={formatUtc(cursorMs)}>{formatLocal(cursorMs)}</span>
      </header>

      <section className={`la-hero${selected || !introDone ? ' hidden' : ''}`} aria-hidden={!!selected || !introDone}>
        <span className="la-eyebrow">The Moon, lit as it is {dateLabel}</span>
        <h1>Will the Sun and Earth be up when you land?</h1>
        <p>
          Spin the Moon and pick a landing site. Sunlight and Earth come from JPL SPICE kernels,
          the relief from NASA's laser altimeter, not from guesses.
        </p>
        <div className="la-actions">
          {apollo && <button type="button" className="la-btn primary" onClick={() => globe.current?.flyToSite(apollo)}>Fly to Apollo 11</button>}
          {im2 && <button type="button" className="la-btn" onClick={() => globe.current?.flyToSite(im2)}>IM-2 at the south pole</button>}
        </div>
        <span className="la-hint">Drag to turn · scroll to zoom · Tab to the sites · Esc for the whole Moon</span>
      </section>

      {selected && (
        <aside className="la-card" aria-label={selected.name}>
          <span className="la-eyebrow">{selected.group ?? 'South polar reference points'}</span>
          <h2>{selected.name}</h2>
          <span className="meta la-mono">{formatLat(selected.latitude_deg)}, {formatLon(selected.longitude_deg)}</span>
          <div className="la-tags">
            <span className="la-tag">Reference site, not official</span>
            {(() => { const t = positionTag(selected); return t && <span className={`la-tag${t.warn ? ' warn' : ''}`}>{t.text}</span>; })()}
            <span className={`la-tag${selected.terrain_status === 'verified' ? '' : ' warn'}`}>
              {selected.terrain_status === 'verified' ? 'Terrain horizon available' : 'Flat horizon only (no terrain)'}
            </span>
          </div>
          {selected.source_url && (
            <a className="la-hint" href={selected.source_url} target="_blank" rel="noreferrer">Coordinate source</a>
          )}
          <div className="row">
            <button type="button" className="la-btn" onClick={() => globe.current?.flyHome()}>Whole Moon (Esc)</button>
          </div>
        </aside>
      )}

      {!introDone && !reducedMotion && (
        <button type="button" className="la-skip la-chip" onClick={() => globe.current?.skipIntro()}>Skip intro (any key)</button>
      )}

      {introDone && (
        <section className="la-dock" aria-label="Time">
          <button type="button" className="la-play" aria-label={playing ? 'Pause' : 'Play'} onClick={() => setPlaying((p) => !p)}>
            <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
              {playing ? <path d="M6 4h4v16H6zM14 4h4v16h-4z" /> : <path d="M7 4l13 8-13 8z" />}
            </svg>
          </button>
          <button type="button" className="la-chip la-mono la-speed" onClick={() => setSpeed((s) => (s === SPEEDS[0] ? SPEEDS[1] : SPEEDS[0]))}>
            {speed === 3600 ? '1 h/s' : '1 day/s'}
          </button>
          <input
            type="range" aria-label="Time" min={window_.start} max={window_.end} step={STEP_MS} value={cursorMs}
            onChange={(e) => { setPlaying(false); setCursor(Number(e.target.value)); }}
          />
          {live && (
            <button type="button" className="la-chip" onClick={() => { setPlaying(false); setCursor(Math.min(window_.end, Math.max(window_.start, Date.now()))); }}>Now</button>
          )}
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
