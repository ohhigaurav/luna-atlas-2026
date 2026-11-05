// Luna Atlas shell (PRD Phase 2): site index on the left, the 3D Moon in the middle, the answer for
// the selected site on the right, one shared clock along the bottom. Every lit pixel and every
// number comes from the API (or its baked copy in static mode); the HUD labels, it never invents.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react';
import './hud.css';
import { GlobeView, type GlobeHandle } from './GlobeView';
import { LandingRing } from './plan/LandingRing';
import { SitePanel } from './plan/SitePanel';
import { SEARCH_DAYS, usePlan, utcMidnight } from './plan/usePlan';
import { loadDataSource, type DataSource, type ReferenceSite } from './data/source';
import { fetchSkyGeometry, sampleTimesMs, skyAt, type SkyGeometry } from './api/sky';
import { isoZ } from './api/plan';
import type { PinSite } from './engine/pins';
import { formatLat, formatLon } from './state/format';
import { litFraction, moonPhase } from './state/phase';
import { siteNormal, siteNow, type SiteNow } from './state/siteState';
import { SiteIndex } from './ui/SiteIndex';
import { CommandBar, type Command } from './ui/CommandBar';
import { Mark, PlayIcon } from './ui/Icons';
import { ProofView } from './proof/ProofView';
import type { MissionCase } from './proof/evidence';
import { SurfaceView } from './surface/SurfaceView';

const SPEEDS = [3600, 6 * 3600, 86400] as const; // simulated seconds per real second
const SPEED_LABEL: Record<(typeof SPEEDS)[number], string> = { 3600: '1 h/s', 21600: '6 h/s', 86400: '1 d/s' };
const STEP_MS = 30 * 60e3;
const HOUR = 3600e3, DAY = 86400e3;
const D2R = Math.PI / 180;

const two = (n: number) => String(n).padStart(2, '0');
function utcParts(ms: number) {
  const d = new Date(ms);
  return {
    date: `${d.getUTCFullYear()}-${two(d.getUTCMonth() + 1)}-${two(d.getUTCDate())}`,
    time: `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}`,
  };
}
const localTime = (ms: number) => new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });

type Sheet = { kind: 'proof' } | { kind: 'surface'; touchdownMs: number } | null;

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
  const [cmd, setCmd] = useState(false);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [grid, setGrid] = useState(false);
  const [hover, setHover] = useState<{ lat: number; lon: number } | null>(null);
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 900);
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
    const r = () => setNarrow(window.innerWidth <= 900);
    window.addEventListener('resize', r);
    return () => window.removeEventListener('resize', r);
  }, []);

  const live = data?.mode === 'live';
  const span = useMemo(() => sky && { start: Date.parse(sky.settings.start_utc), end: Date.parse(sky.settings.end_utc) }, [sky]);
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

  // Playback advances the shared clock; React hears about it at ~8 Hz, the scene every frame.
  useEffect(() => {
    if (!playing || !span) return;
    let raf = 0, last = performance.now(), lastUi = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      const next = cursorRef.current + dt * speed * 1000;
      if (next >= span.end) { setCursor(span.end); setPlaying(false); return; }
      cursorRef.current = next;
      if (now - lastUi > 120) { lastUi = now; setCursorMs(next); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, span, setCursor]);

  /** Load sky geometry for [startMs, endMs) so the scene can follow a plan, a replay or "now". */
  const loadSky = useCallback((startMs: number, endMs: number) => {
    return fetchSkyGeometry(isoZ(startMs), isoZ(endMs), 30).then(setSky, (e: Error) => setError(`Sky geometry: ${e.message}`));
  }, []);
  const covered = useCallback((ms: number) => !!span && ms >= span.start && ms <= span.end, [span]);

  const goNow = useCallback(() => {
    setPlaying(false);
    const now = Date.now();
    if (live && !covered(now)) loadSky(now - 2 * HOUR, now + 30 * DAY);
    setFollowNow(true);
  }, [live, covered, loadSky]);

  const jump = useCallback((ms: number) => {
    setFollowNow(false); setPlaying(false); setCursor(ms);
    if (live && !covered(ms)) loadSky(ms - 2 * DAY, ms + 30 * DAY);
  }, [setCursor, live, covered, loadSky]);

  const onSelect = useCallback((s: PinSite | null) => { setSelected(s as ReferenceSite | null); if (!s) setSheet(null); }, []);
  const plan = usePlan(selected?.site_id ?? null, live, Date.now());
  const screenOf = useCallback((s: PinSite) => globe.current?.screenOf(s) ?? null, []);

  // The ring covers SEARCH_DAYS from its start: load sky geometry for that window so any jump is lit.
  const planStart = plan.settings.searchStartMs;
  useEffect(() => {
    if (!selected || !live) return;
    loadSky(planStart - DAY, planStart + (SEARCH_DAYS + 1) * DAY);
  }, [selected, live, planStart, loadSky]);
  const onIntroDone = useCallback(() => setIntroDone(true), []);
  const byId = useCallback((id: string) => data?.sites.find((s) => s.site_id === id) ?? null, [data]);

  // Frame the globe in the space the panels leave free.
  useEffect(() => {
    if (narrow) globe.current?.setInsets(0, 0);
    else globe.current?.setInsets(312, selected ? 384 : 0);
  }, [selected, narrow, data]);
  useEffect(() => { globe.current?.setGrid(grid); }, [grid, data]);

  // Ctrl/⌘ K opens the command bar from anywhere.
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmd((c) => !c); }
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, []);

  // How much of the Moon is lit as seen from Earth at the cursor (from the API's Sun/Earth vectors).
  const phase = useMemo(() => {
    if (!sky || !times) return null;
    const a = skyAt(sky, times, cursorMs), b = skyAt(sky, times, cursorMs + HOUR);
    return moonPhase(litFraction(a.sunDir, a.earthDir), litFraction(b.sunDir, b.earthDir));
  }, [sky, times, cursorMs]);

  // "Right now on the Moon" (F24): day or night at every site at the clock's time, flat horizon.
  // Recomputed once per simulated 10 minutes; the scan is ~25 sites × the loaded samples.
  const stateKey = Math.floor(cursorMs / 600e3);
  const states = useMemo(() => {
    const out: Record<string, SiteNow> = {};
    if (!sky || !times || !data) return out;
    const t = stateKey * 600e3;
    for (const s of data.sites) out[s.site_id] = siteNow(sky, times, s.latitude_deg, s.longitude_deg, t);
    return out;
  }, [sky, times, data, stateKey]);
  useEffect(() => {
    const m: Record<string, string> = {};
    for (const [id, st] of Object.entries(states)) m[id] = st.day ? 'day' : 'night';
    globe.current?.setPinStates(m);
  }, [states]);

  // Readout under the pointer: where it is and how high the Sun stands there (smooth sphere).
  const hoverRaf = useRef(0);
  const onMove = useCallback((e: RPointerEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
    cancelAnimationFrame(hoverRaf.current);
    hoverRaf.current = requestAnimationFrame(() => setHover(globe.current?.pick(x, y) ?? null));
  }, []);
  const hoverSun = useMemo(() => {
    if (!hover || !sky || !times) return null;
    const n = siteNormal(hover.lat, hover.lon), s = skyAt(sky, times, cursorMs).sunDir;
    return Math.asin(Math.max(-1, Math.min(1, n[0] * s[0] + n[1] * s[1] + n[2] * s[2]))) / D2R;
  }, [hover, sky, times, cursorMs]);

  const pick = useCallback((s: ReferenceSite) => { globe.current?.flyToSite(s); }, []);
  const runCommand = useCallback((c: Command) => {
    if (c.kind === 'site') pick(c.site);
    else if (c.kind === 'date') {
      if (c.when.precision === 'instant') { goNow(); return; }
      if (selected && live) { const t = utcMidnight(c.when.ms); plan.update({ searchStartMs: t, notBeforeMs: t }); }
      else jump(c.when.ms + 12 * HOUR);
    } else if (c.id === 'proof') setSheet({ kind: 'proof' });
    else if (c.id === 'home') globe.current?.flyHome();
    else if (c.id === 'now') goNow();
    else if (c.id === 'earth') globe.current?.viewFromEarth();
    else if (c.id === 'grid') setGrid((g) => !g);
  }, [pick, goNow, selected, live, plan, jump]);

  const showMission = useCallback((c: MissionCase) => {
    const s = c.siteId ? byId(c.siteId) : null;
    if (!s || !c.whenUtc) return;
    const t = Date.parse(c.whenUtc);
    setSheet(null);
    setFollowNow(false); setPlaying(false);
    loadSky(t - 2 * DAY, t + 20 * DAY).then(() => setCursor(t));
    pick(s);
  }, [byId, loadSky, setCursor, pick]);

  if (fatal) {
    return <div className="la-app"><div className="la-toast" role="alert">{fatal}</div></div>;
  }
  if (!data || !sky || !span) {
    return (
      <div className="la-app">
        <div className="la-boot" role="status"><Mark /><span>Asking JPL SPICE where the Sun is…</span><div className="la-bar" /></div>
      </div>
    );
  }

  const now = utcParts(cursorMs);
  const sel = selected ? states[selected.site_id] ?? null : null;

  return (
    <div className={`la-app${selected ? ' side-open' : ''}${sheet ? ` sheet-open sheet-${sheet.kind}` : ''}`}>
      <div className="la-stage" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
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
      </div>

      <header className="la-top">
        <div className="la-brand"><Mark />Luna Atlas<small>{live ? 'live, JPL SPICE' : `as of ${data.sky.settings.start_utc.slice(0, 10)}`}</small></div>
        <span className="la-spacer" />
        {phase && (
          <div className="la-tele la-hide-narrow">
            <button type="button" onClick={() => globe.current?.viewFromEarth()} title="Turn the Moon to face Earth: the phase in your sky at this time">
              <span>From Earth</span><b>{Math.round(phase.fraction * 100)}% lit</b><span>{phase.name.toLowerCase()}</span>
            </button>
          </div>
        )}
        <div className="la-tele la-clock" title={`Local ${localTime(cursorMs)}`}>
          <i className={`la-live${followNow ? '' : ' off'}`} aria-hidden="true" />
          <b>{now.date}</b><b>{now.time}</b><span>UTC</span>
        </div>
      </header>

      <SiteIndex sites={data.sites} states={states} cursorMs={cursorMs} selectedId={selected?.site_id ?? null}
        onPick={pick} onSearch={() => setCmd(true)} onProof={() => setSheet({ kind: 'proof' })} />

      {selected && (
        <SitePanel
          site={selected}
          live={live}
          now={sel}
          cursorMs={cursorMs}
          settings={plan.settings}
          data={plan.data}
          answer={plan.answer}
          onSettings={plan.update}
          onJump={jump}
          onSurface={(ms) => { jump(ms); setSheet({ kind: 'surface', touchdownMs: ms }); }}
          onClose={() => globe.current?.flyHome()}
          onProof={() => setSheet({ kind: 'proof' })}
        />
      )}

      {selected && live && !sheet && (
        <LandingRing site={selected} screenOf={screenOf} settings={plan.settings} data={plan.data}
          answer={plan.answer} onSettings={plan.update} onJump={jump} />
      )}

      {introDone && !sheet && (
        <>
          <div className="la-readout" aria-hidden="true">
            {hover ? (
              <>
                <span>{formatLat(hover.lat)} {formatLon(hover.lon)}</span>
                {hoverSun !== null && <span>Sun <b className={hoverSun > 0 ? 'sun-c' : undefined}>{hoverSun.toFixed(1)}°</b> here, flat ground</span>}
              </>
            ) : <span>Drag to turn, scroll to zoom, click a site</span>}
          </div>
          <button type="button" className={`la-btn la-gridbtn${grid ? ' on' : ''}`} aria-pressed={grid} onClick={() => setGrid((g) => !g)}>
            Lat/lon grid
          </button>
          <div className="la-credits">Moon: NASA SVS CGI Moon Kit (LROC colour, LOLA relief)<br />Earth: Blue Marble, rotation not modelled · stars illustrative</div>
        </>
      )}

      {!introDone && !reducedMotion && (
        <button type="button" className="la-btn la-skip" onClick={() => globe.current?.skipIntro()}>Skip intro</button>
      )}

      {introDone && (
        <section className="la-time" aria-label="Time">
          <button type="button" className="la-play" aria-label={playing ? 'Pause' : 'Play'}
            onClick={() => { setFollowNow(false); setPlaying((p) => !p); }}>
            <PlayIcon playing={playing} size={14} />
          </button>
          <button type="button" className="la-speed" aria-label="Playback speed"
            onClick={() => setSpeed((s) => SPEEDS[(SPEEDS.indexOf(s) + 1) % SPEEDS.length])}>{SPEED_LABEL[speed]}</button>
          <div className="la-scrub">
            <input type="range" aria-label="Time" min={span.start} max={span.end} step={STEP_MS}
              value={Math.min(span.end, Math.max(span.start, cursorMs))}
              onChange={(e) => { setFollowNow(false); setPlaying(false); setCursor(Number(e.target.value)); }} />
          </div>
          <div className="la-when"><span>{now.date} {now.time} UTC</span><small>{localTime(cursorMs)}</small></div>
          {live && (
            <button type="button" className={`la-nowbtn${followNow ? ' on' : ''}`} onClick={goNow} aria-pressed={followNow}>
              <i className={`la-live${followNow ? '' : ' off'}`} aria-hidden="true" />Now
            </button>
          )}
        </section>
      )}

      {sheet?.kind === 'proof' && <ProofView live={live} onClose={() => setSheet(null)} onShow={showMission} />}
      {sheet?.kind === 'surface' && selected && (
        <SurfaceView site={selected} touchdownMs={sheet.touchdownMs} missionDays={plan.settings.missionDays} cursorMs={cursorMs}
          playing={playing}
          onPlay={(from) => {
            if (from === null) { setPlaying(false); return; }
            setFollowNow(false); setSpeed(SPEEDS[1]); setCursor(from); setPlaying(true);
          }}
          onJump={jump}
          onClose={() => { setPlaying(false); setSheet(null); }} />
      )}
      {cmd && <CommandBar sites={data.sites} selectedName={selected?.name ?? null} onRun={runCommand} onClose={() => setCmd(false)} />}
      {error && <div className="la-toast" role="alert" onClick={() => setError(null)}>{error}</div>}
    </div>
  );
}
