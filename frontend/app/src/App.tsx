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
import { siteNow, type SiteNow } from './state/siteState';
import { DateBar } from './ui/DateBar';
import { SiteCard } from './plan/SiteCard';
import { CompareShelf } from './compare/CompareShelf';
import { useOutlook } from './plan/useOutlook';
import { OutlookProgress } from './ui/OutlookProgress';
import { ForecastPanel, type Layers, type Probe } from './forecast/ForecastPanel';
import { earthFrameAt, loadForecast, pixelOf, sunFrameAt, unpackFrame, bitAt, type ForecastData } from './forecast/forecastData';
import { pointId } from './api/plan';
import { shortName } from './engine/pins';
import { outlookText } from './state/outlook';
import { CommandBar, type Command } from './ui/CommandBar';
import { ProofView } from './proof/ProofView';
import type { MissionCase } from './proof/evidence';
import { Surface3D } from './surface/Surface3D';
import { CompareView } from './compare/CompareView';

const SPEEDS = [3600, 6 * 3600, 86400] as const; // simulated seconds per real second
const SPEED_LABEL: Record<(typeof SPEEDS)[number], string> = { 3600: '1 h/s', 21600: '6 h/s', 86400: '1 d/s' };
const HOUR = 3600e3, DAY = 86400e3;


type Sheet = { kind: 'proof' } | { kind: 'surface'; touchdownMs: number } | { kind: 'compare' } | null;

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
  // Moon weather forecast (F29)
  const [forecast, setForecast] = useState(false);
  const [fc, setFc] = useState<ForecastData | null>(null);
  const [layers, setLayers] = useState<Layers>({ earth: false, both: false });
  const [cmp, setCmp] = useState<ReferenceSite[]>([]);   // compare list, up to 6 places
  const [comparing, setComparing] = useState(false);       // compare mode: pins add to the list
  const [hello, setHello] = useState(true);
  const [probe, setProbe] = useState<Probe>({ lat: -89.45, lon: 222.69, name: null });
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
    const r = () => { setNarrow(window.innerWidth <= 900); };
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

  // In the forecast, playback loops over the forecast month like a weather radar.
  const loop = useMemo<[number, number] | null>(() => (forecast && fc ? [fc.sunMs[0], fc.sunMs[fc.sunMs.length - 1]] : null), [forecast, fc]);
  // Playback advances the shared clock; React hears about it at ~8 Hz, the scene every frame.
  useEffect(() => {
    if (!playing || !span) return;
    let raf = 0, last = performance.now(), lastUi = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      let next = cursorRef.current + dt * speed * 1000;
      if (loop && next > loop[1]) next = loop[0];
      if (next >= span.end) { setCursor(span.end); setPlaying(false); return; }
      cursorRef.current = next;
      if (now - lastUi > 120) { lastUi = now; setCursorMs(next); }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, span, setCursor, loop]);

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

  const onSelect = useCallback((s: PinSite | null) => { setSelected(s as ReferenceSite | null); setForecast(false); if (!s) setSheet(null); }, []);
  const plan = usePlan(selected?.site_id ?? null, live, Date.now());
  // Date first: with a site open, the landing question starts from the date in the date bar.
  const cursorHour = Math.floor(cursorMs / HOUR);
  useEffect(() => {
    if (!selected || playing) return;
    const t = setTimeout(() => {
      // Inside the 90 days already searched only the "earliest launch" moves (no new search);
      // outside them, search again from that day.
      const c = cursorRef.current, s = plan.settings;
      const inside = c >= s.searchStartMs && c <= s.searchStartMs + (SEARCH_DAYS - 10) * DAY;
      if (!inside) plan.update({ searchStartMs: utcMidnight(c), notBeforeMs: c });
      else if (Math.abs(s.notBeforeMs - c) > HOUR) plan.update({ notBeforeMs: c });
    }, 400);
    return () => clearTimeout(t);
  }, [selected, cursorHour, playing]); // eslint-disable-line react-hooks/exhaustive-deps
  const screenOf = useCallback((s: PinSite) => globe.current?.screenOf(s) ?? null, []);

  // The ring covers SEARCH_DAYS from its start: load sky geometry for that window so any jump is lit.
  const planStart = plan.settings.searchStartMs;
  useEffect(() => {
    if (!selected || !live) return;
    if (covered(planStart) && covered(planStart + SEARCH_DAYS * DAY)) return;
    loadSky(planStart - DAY, planStart + (SEARCH_DAYS + 1) * DAY);
  }, [selected, live, planStart, loadSky]); // eslint-disable-line react-hooks/exhaustive-deps
  const onIntroDone = useCallback(() => setIntroDone(true), []);
  const byId = useCallback((id: string) => data?.sites.find((s) => s.site_id === id) ?? null, [data]);

  // Frame the globe in the space the panels leave free.
  useEffect(() => {
    // Keep the Moon clear of the card (left) or the drawer (right) when one is open.
    if (narrow) globe.current?.setInsets(0, 0);
    else globe.current?.setInsets(selected || (!forecast && !comparing) ? 440 : 0, forecast ? 440 : 0);
  }, [narrow, data, selected, forecast, comparing]);
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
  const { outlook, progress } = useOutlook(data?.sites ?? null, live, selected?.site_id ?? null);
  // The forecast frame at the clock's time (null outside the forecast month or when it is off).
  const fcFrame = useMemo(() => {
    if (!forecast || !fc) return null;
    const s = sunFrameAt(fc, cursorMs);
    if (!s) return null;
    return { ...s, j: earthFrameAt(fc, cursorMs) };
  }, [forecast, fc, cursorMs]);
  const unpacked = useRef(new Map<string, Uint8Array>());
  const frameBytes = useCallback((bits: Uint8Array, kind: string, i: number) => {
    const key = `${kind}${i}`, m = unpacked.current;
    let v = m.get(key);
    if (!v && fc) {
      v = unpackFrame(bits, i, fc.n);
      m.set(key, v);
      if (m.size > 8) m.delete(m.keys().next().value!);
    }
    return v!;
  }, [fc]);
  const litShare = useMemo(() => {
    if (!fcFrame || !fc) return 0;
    const a = frameBytes(fc.litBits, 's', fcFrame.k);
    let n = 0;
    for (let i = 0; i < a.length; i++) n += a[i] ? 1 : 0;
    return n / a.length;
  }, [fcFrame?.k, fc, frameBytes]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!fc || !fcFrame) { globe.current?.setForecast(null); return; }
    globe.current?.setForecast({
      n: fc.n, halfM: fc.halfM, mix: fcFrame.mix,
      litA: frameBytes(fc.litBits, 's', fcFrame.k), litB: frameBytes(fc.litBits, 's', fcFrame.k1),
      earth: fcFrame.j === null ? null : frameBytes(fc.earthBits, 'e', fcFrame.j),
      earthOn: layers.earth, bothOn: layers.both,
    });
  }, [fc, fcFrame, layers, frameBytes]);

  useEffect(() => {
    const m: Record<string, string> = {}, notes: Record<string, string> = {};
    for (const [id, st] of Object.entries(states)) {
      const o = outlook[id];
      m[id] = `${st.day ? 'day' : 'night'}${o?.kind === 'window' ? ' window' : ''}`;
      notes[id] = o && o.kind !== 'pending' ? outlookText(o) : st.day ? 'Sun up now' : 'night now';
    }
    // In the forecast, sites inside the square show the forecast itself: sunrise arriving.
    if (fc && fcFrame && data) {
      for (const s of data.sites) {
        const p = pixelOf(fc, s.latitude_deg, s.longitude_deg);
        if (!p) continue;
        const lit = bitAt(fc.litBits, fcFrame.k, fc.n, p.r, p.c);
        const ea = fcFrame.j !== null && bitAt(fc.earthBits, fcFrame.j, fc.n, p.r, p.c);
        m[s.site_id] = lit ? 'day' : 'night';
        notes[s.site_id] = `${lit ? 'sunlit' : 'in shadow'}${ea ? ', Earth in view' : ''} (forecast)`;
      }
    }
    globe.current?.setPinStates(m);
    globe.current?.setPinNotes(notes);
  }, [states, outlook, fc, fcFrame, data]);

  // Readout under the pointer: where it is and how high the Sun stands there (smooth sphere).
  const hoverRaf = useRef(0);
  const onMove = useCallback((e: RPointerEvent<HTMLDivElement>) => {
    const b = e.currentTarget.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
    cancelAnimationFrame(hoverRaf.current);
    hoverRaf.current = requestAnimationFrame(() => setHover(globe.current?.pick(x, y) ?? null));
  }, []);

  const hoverFc = useMemo(() => {
    if (!hover || !fc || !fcFrame) return null;
    const p = pixelOf(fc, hover.lat, hover.lon);
    if (!p) return null;
    const i = p.r * fc.n + p.c;
    return {
      lit: bitAt(fc.litBits, fcFrame.k, fc.n, p.r, p.c),
      earth: fcFrame.j !== null && bitAt(fc.earthBits, fcFrame.j, fc.n, p.r, p.c),
      sunPct: (fc.litHours[i] / fc.sunMs.length) * 100, earthPct: (fc.earthHours[i] / fc.earthMs.length) * 100,
    };
  }, [hover, fc, fcFrame]);

  const pick = useCallback((s: ReferenceSite) => { setForecast(false); globe.current?.flyToSite(s); }, []);

  const openForecast = useCallback(async () => {
    let f = fc;
    if (!f) {
      try { f = await loadForecast(`${import.meta.env.BASE_URL}data/shadow_movie/`); setFc(f); }
      catch (e) { setError(`Forecast data: ${e instanceof Error ? e.message : String(e)}`); return; }
    }
    const t0 = f.sunMs[0], t1 = f.sunMs[f.sunMs.length - 1];
    // Probe starts on a catalogue site inside the square (LOLA Site 001 when present).
    const inside = (data?.sites ?? []).filter((x) => pixelOf(f, x.latitude_deg, x.longitude_deg));
    const first = inside.find((x) => x.site_id === 'reference-lola-site-001') ?? inside[0];
    if (first && probe.name === null) setProbe({ lat: first.latitude_deg, lon: first.longitude_deg, name: shortName(first.name) });
    setSheet(null); setSelected(null); setComparing(false); setForecast(true);
    setFollowNow(false); setPlaying(false); setSpeed(SPEEDS[1]);
    const start = cursorRef.current >= t0 && cursorRef.current <= t1 ? cursorRef.current : t0;
    const ready = live && !covered(t0) ? loadSky(t0 - DAY, t1 + 2 * DAY) : Promise.resolve();
    ready.then(() => {
      setCursor(start);
      globe.current?.flyToSouthPole();
      if (!reducedMotion) setTimeout(() => setPlaying(true), 2600);
    });
  }, [fc, live, covered, loadSky, setCursor, reducedMotion, data, probe.name]);
  const toggleCompare = useCallback((s: ReferenceSite) => {
    setCmp((c) => (c.some((x) => x.site_id === s.site_id) ? c.filter((x) => x.site_id !== s.site_id) : [...c, s].slice(-6)));
  }, []);
  const polarSix = useCallback(() => (data?.sites ?? []).filter((s) => s.latitude_deg <= -75).slice(0, 6), [data]);
  // Compare: date first (the bar at the top), then tap sites; pins add to the list instead of flying.
  const startCompare = useCallback(() => {
    setForecast(false); setSelected(null); setSheet(null); setComparing(true);
    globe.current?.flyHome();
  }, []);
  useEffect(() => {
    globe.current?.setPickOnly(comparing ? (s: PinSite) => toggleCompare(s as ReferenceSite) : null);
  }, [comparing, toggleCompare, data]);
  const closeForecast = useCallback(() => { setForecast(false); setPlaying(false); globe.current?.flyHome(); }, []);

  const goPoint = (lat: number, lonDeg: number) => {
    const lon = ((lonDeg % 360) + 360) % 360;
    const site: ReferenceSite = {
      site_id: pointId(lat, lon), latitude_deg: lat, longitude_deg: lon,
      name: `Point ${Math.abs(lat).toFixed(3)}° ${lat < 0 ? 'S' : 'N'}, ${lon.toFixed(3)}° E`,
    };
    setForecast(false);
    globe.current?.flyToSite(site);
  };
  // A click on the Moon (not on a pin): in the forecast it moves the probe; elsewhere it asks the
  // landing question for that exact point (any point, 240 m terrain; docs/frontend_api.md).
  const down = useRef<{ x: number; y: number; t: number } | null>(null);
  const onDown = useCallback((e: RPointerEvent<HTMLDivElement>) => { down.current = { x: e.clientX, y: e.clientY, t: performance.now() }; }, []);
  const onUp = useCallback((e: RPointerEvent<HTMLDivElement>) => {
    const d = down.current;
    down.current = null;
    if (!d || (e.target as HTMLElement).tagName !== 'CANVAS' || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 5 || performance.now() - d.t > 500) return;
    const b = e.currentTarget.getBoundingClientRect(), p = globe.current?.pick(e.clientX - b.left, e.clientY - b.top);
    if (!p) return;
    if (forecast && fc && pixelOf(fc, p.lat, p.lon)) { setProbe({ lat: p.lat, lon: p.lon, name: null }); return; }
    if (forecast) return;
    goPoint(p.lat, p.lon);
  }, [forecast, fc]);
  const runCommand = useCallback((c: Command) => {
    if (c.kind === 'site') pick(c.site);
    else if (c.kind === 'point') goPoint(c.lat, c.lon);
    else if (c.kind === 'date') {
      if (c.when.precision === 'instant') { goNow(); return; }
      if (selected && live) { const t = utcMidnight(c.when.ms); plan.update({ searchStartMs: t, notBeforeMs: t }); }
      else jump(c.when.ms + 12 * HOUR);
    } else if (c.id === 'proof') setSheet({ kind: 'proof' });
    else if (c.id === 'home') globe.current?.flyHome();
    else if (c.id === 'now') goNow();
    else if (c.id === 'earth') globe.current?.viewFromEarth();
    else if (c.id === 'grid') setGrid((g) => !g);
    else if (c.id === 'forecast') openForecast();
    else if (c.id === 'compare') startCompare();
  }, [pick, goNow, selected, live, plan, jump, openForecast, startCompare]);

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
        <div className="la-boot" role="status"><span>Asking JPL SPICE where the Sun is…</span><div className="la-bar" /></div>
      </div>
    );
  }

  const sel = selected ? states[selected.site_id] ?? null : null;

  const legendCounts = {
    green: Object.values(outlook).filter((o) => o.kind === 'window').length,
    day: data.sites.filter((x) => states[x.site_id]?.day).length,
  };
  const checked = Object.values(outlook).filter((o) => o.kind !== 'pending').length;

  return (
    <div className={`la-app${selected ? ' site-open' : ''}${sheet ? ` sheet-open sheet-${sheet.kind}` : ''}${comparing ? ' comparing' : ''}${forecast ? ' fc-open' : ''}`}>
      <div className="la-stage" onPointerMove={onMove} onPointerLeave={() => setHover(null)} onPointerDown={onDown} onPointerUp={onUp}>
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

      <header className="la-topbar">
        <button type="button" className="tb-brand" onClick={() => { setForecast(false); setComparing(false); globe.current?.flyHome(); }}>
          Luna Atlas<small>{live ? 'live from JPL SPICE' : `precomputed, as of ${data.sky.settings.start_utc.slice(0, 10)}`}</small>
        </button>
        {introDone && (
          <DateBar ms={cursorMs} live={live} following={followNow} playing={playing} speedLabel={SPEED_LABEL[speed]}
            range={loop ?? [span.start, span.end]}
            onSet={(ms) => { setFollowNow(false); setPlaying(false); setCursor(ms); if (live && !covered(ms)) loadSky(ms - 2 * DAY, ms + 30 * DAY); }}
            onPlay={() => { setFollowNow(false); setPlaying((p) => !p); }}
            onSpeed={() => setSpeed((x) => SPEEDS[(SPEEDS.indexOf(x) + 1) % SPEEDS.length])}
            onNow={goNow} />
        )}
        <nav className="tb-nav" aria-label="Tools">
          <button type="button" className={comparing ? 'on' : undefined} aria-pressed={comparing} onClick={() => (comparing ? setComparing(false) : startCompare())}>Compare sites</button>
          <button type="button" className={forecast ? 'on' : undefined} aria-pressed={forecast} onClick={() => (forecast ? closeForecast() : openForecast())}>Moon weather</button>
          <button type="button" onClick={() => setSheet({ kind: 'proof' })}>Evidence</button>
          <button type="button" className="tb-search" aria-label="Search (Ctrl K)" onClick={() => setCmd(true)}>Search<kbd>Ctrl K</kbd></button>
        </nav>
      </header>

      {introDone && !selected && !forecast && !comparing && !sheet && (
        <aside className="la-hello">
          {hello ? (
            <>
              <h1>When can you land on the Moon?</h1>
              <p>Pick a date at the top, then tap a site. Luna Atlas tells you if the Sun stays up for the mission and Earth is in view for the radio link.</p>
              <button type="button" className="la-btn" onClick={() => setHello(false)}>Got it</button>
            </>
          ) : null}
          <div className="hl-key" aria-label="What the pin colours mean">
            {live && <span><i className="la-sym window" />Can land within 30 days <b>{legendCounts.green}</b></span>}
            <span><i className="la-sym day" />Sunlit now <b>{legendCounts.day}</b></span>
            <span><i className="la-sym night" />Night now <b>{data.sites.length - legendCounts.day}</b></span>
          </div>
          {live && checked < data.sites.length && (
            <OutlookProgress checked={checked} total={data.sites.length} etaMs={progress.etaMs} at={progress.at} />
          )}
          {phase && (
            <button type="button" className="la-mlink hl-phase" onClick={() => globe.current?.viewFromEarth()}>
              From Earth the Moon is {Math.round(phase.fraction * 100)}% lit ({phase.name.toLowerCase()}). Show me
            </button>
          )}
        </aside>
      )}

      {selected && !forecast && !sheet && (
        <SiteCard
          site={selected} live={live} cursorMs={cursorMs} now={sel}
          settings={plan.settings} data={plan.data} answer={plan.answer}
          inCompare={cmp.some((x) => x.site_id === selected.site_id)}
          onSettings={plan.update} onJump={jump}
          onStand={(ms) => { jump(ms); setSheet({ kind: 'surface', touchdownMs: ms }); }}
          onCompare={() => toggleCompare(selected)}
          onClose={() => globe.current?.flyHome()}
          details={
            <SitePanel site={selected} live={live} now={sel} cursorMs={cursorMs} settings={plan.settings} data={plan.data} answer={plan.answer}
              onSettings={plan.update} onJump={jump} onSurface={(ms) => { jump(ms); setSheet({ kind: 'surface', touchdownMs: ms }); }}
              onClose={() => globe.current?.flyHome()} onProof={() => setSheet({ kind: 'proof' })}
              inCompare={cmp.some((x) => x.site_id === selected.site_id)} onCompare={() => toggleCompare(selected)} details />
          }
        />
      )}

      {forecast && fc && (
        <aside className="la-drawer">
          <ForecastPanel fc={fc} cursorMs={cursorMs} frame={fcFrame ? { k: fcFrame.k, j: fcFrame.j, litShare } : null}
            layers={layers} probe={probe} onLayers={setLayers} onJump={(ms) => { setPlaying(false); setCursor(ms); }} onClose={closeForecast} />
        </aside>
      )}

      {selected && live && !sheet && !forecast && (
        <LandingRing site={selected} screenOf={screenOf} settings={plan.settings} data={plan.data}
          answer={plan.answer} onSettings={plan.update} onJump={jump} />
      )}

      {introDone && hover && !sheet && (hoverFc || forecast) && (
        <div className="la-hover">
          {formatLat(hover.lat)} {formatLon(hover.lon)}
          {hoverFc && <>: <b className={hoverFc.lit ? 'sun-c' : undefined}>{hoverFc.lit ? 'sunlit' : 'in shadow'}</b>, <b className={hoverFc.earth ? 'earth-c' : undefined}>{hoverFc.earth ? 'Earth in view' : 'Earth hidden'}</b> (forecast, 240 m)</>}
        </div>
      )}

      {!introDone && !reducedMotion && (
        <button type="button" className="la-btn la-skip" onClick={() => globe.current?.skipIntro()}>Skip intro</button>
      )}

      {comparing && !sheet && (
        <CompareShelf places={cmp} live={live} cursorMs={cursorMs}
          suggest={live ? () => setCmp(polarSix()) : null}
          onRemove={(id) => setCmp((c) => c.filter((x) => x.site_id !== id))}
          onOpen={(s) => { setComparing(false); pick(s); }}
          onTable={() => setSheet({ kind: 'compare' })}
          onClear={() => { setComparing(false); }} />
      )}
      {sheet?.kind === 'compare' && (
        <CompareView places={cmp} live={live} clockMs={cursorMs} onRemove={(id) => setCmp((c) => c.filter((x) => x.site_id !== id))}
          onOpen={(s) => { setSheet(null); setComparing(false); pick(s); }} onClose={() => setSheet(null)} />
      )}
      {sheet?.kind === 'proof' && <ProofView live={live} onClose={() => setSheet(null)} onShow={showMission} />}
      {sheet?.kind === 'surface' && selected && (
        <Surface3D site={selected} touchdownMs={sheet.touchdownMs} missionDays={plan.settings.missionDays} cursorMs={cursorMs}
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
