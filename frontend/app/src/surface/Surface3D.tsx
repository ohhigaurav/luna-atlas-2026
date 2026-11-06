// "Stand here": you on the ground at the site, in 3D (PRD F20). The skyline is the site's real
// horizon from the backend run; the Sun and Earth move across the sky with the shared clock; the
// battery card is the illustrative "Keep the lander alive" model on the run's sunlight.
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { spanText } from '../state/siteState';
import { Ground3D } from './Ground3D';
import { simulate, socAt, type PanelKind, type SunSample } from './power';
import { rowAt, RUN_DAYS, useRun } from './run';

type Props = {
  site: ReferenceSite;
  touchdownMs: number;
  missionDays: number;
  cursorMs: number;
  playing: boolean;
  onPlay: (fromMs: number | null) => void;   // null = pause
  onJump: (ms: number) => void;
  onClose: () => void;
};

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
const fmt = (ms: number) => new Date(ms).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) + ' UTC';

export function Surface3D({ site, touchdownMs, missionDays, cursorMs, playing, onPlay, onJump, onClose }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const g = useRef<Ground3D | null>(null);
  const [heading, setHeading] = useState(0);
  const [mast, setMast] = useState(2);
  const [panel, setPanel] = useState<PanelKind>('tracking');
  const [panelW, setPanelW] = useState(400);
  const [batteryWh, setBatteryWh] = useState(2000);
  const [loadW, setLoadW] = useState(60);
  const [settings, setSettings] = useState(false);
  const startMs = Math.floor(touchdownMs / 1800e3) * 1800e3;
  const st = useRun(site.site_id, startMs, mast);
  const aimed = useRef(false);

  useEffect(() => {
    if (!host.current) return;
    const v = new Ground3D(host.current);
    g.current = v;
    let last = -1;
    v.onHeading = (h) => { const r = Math.round(h); if (r !== last) { last = r; setHeading(r); } };
    fetch(`${import.meta.env.BASE_URL}textures/textures.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null)
      .then((t: { earth?: string | null } | null) => {
        const f = t ? t.earth : 'earth_bluemarble_5400.jpg';
        if (f) v.setEarthTexture(`${import.meta.env.BASE_URL}textures/${f}`);
      });
    return () => { v.dispose(); g.current = null; };
  }, []);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);

  const run = st.status === 'ready' ? st.run.sites[0] : null;
  useEffect(() => {
    if (!run || !g.current) return;
    g.current.setHorizon(run.horizon_profile.map((b) => ({ az: b.azimuth_deg, el: b.elevation_deg ?? 0 })));
  }, [run]);

  const now = st.status === 'ready' ? rowAt(st.run.sites[0].series, st.times, cursorMs) : null;
  useEffect(() => {
    if (!now || !g.current) return;
    g.current.setSky({
      sunAz: now.sun_azimuth_deg, sunEl: now.sun_elevation_deg, sunVisible: now.sun_visible_upper_limb,
      earthAz: now.earth_azimuth_deg, earthEl: now.earth_elevation_deg, earthVisible: now.earth_center_clear,
    });
    if (!aimed.current) { aimed.current = true; g.current.look(now.sun_azimuth_deg + 25, Math.max(3, now.sun_elevation_deg)); }
  }, [now]);

  const samples = useMemo<SunSample[]>(() => (st.status === 'ready'
    ? st.run.sites[0].series.map((r, i) => ({ tMs: st.times[i], sunElDeg: r.sun_elevation_deg, sunVisible: r.sun_visible_upper_limb })) : []), [st]);
  const res = useMemo(() => simulate(samples, { panelW, panel, batteryWh, loadW }, startMs), [samples, panelW, panel, batteryWh, loadW, startMs]);
  const soc = socAt(res, cursorMs);
  const nextOf = (key: 'sun_visible_upper_limb' | 'earth_center_clear') => {
    if (st.status !== 'ready' || !now) return null;
    const s = st.run.sites[0].series;
    for (let i = 0; i < s.length; i++) if (st.times[i] > cursorMs && s[i][key] !== now[key]) return st.times[i];
    return null;
  };
  const sunNext = nextOf('sun_visible_upper_limb'), earthNext = nextOf('earth_center_clear');
  const endMs = st.status === 'ready' ? st.times[st.times.length - 1] : startMs;
  const goalMs = touchdownMs + missionDays * 86400e3;
  const pct = soc === null ? null : Math.round((soc / batteryWh) * 100);
  // The model starts at the half hour before touchdown (the run's first sample).
  const madeIt = res.diedMs === null ? res.endMs >= goalMs : res.diedMs >= goalMs;

  // Compass ribbon: 120 degrees either side of where you look.
  const rel = (az: number) => { let d = az - heading; if (d > 180) d -= 360; if (d < -180) d += 360; return d; };
  const ticks = Array.from({ length: 24 }, (_, i) => i * 15).map((a) => ({ a, d: rel(a) })).filter((t) => Math.abs(t.d) <= 90);

  return (
    <section className="la-ground" aria-label={`Standing at ${site.name}`}>
      <div className="g-view" ref={host} />

      <header className="g-top">
        <button type="button" className="g-back" onClick={onClose}>‹ Back to the Moon</button>
        <div className="g-title">
          <h2>{site.name}</h2>
          <span>Standing on the ground, looking {COMPASS[Math.round(heading / 45) % 8]}. Drag to look around, scroll to zoom.</span>
        </div>
      </header>

      <div className="g-compass" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t.a} className={`t${t.a % 45 === 0 ? ' major' : ''}`} style={{ left: `${50 + (t.d / 90) * 50}%` }}>
            {t.a % 45 === 0 && <em>{COMPASS[t.a / 45]}</em>}
          </span>
        ))}
        {now && Math.abs(rel(now.sun_azimuth_deg)) <= 90 && <i className="m sun" style={{ left: `${50 + (rel(now.sun_azimuth_deg) / 90) * 50}%` }} />}
        {now && Math.abs(rel(now.earth_azimuth_deg)) <= 90 && <i className="m earth" style={{ left: `${50 + (rel(now.earth_azimuth_deg) / 90) * 50}%` }} />}
        <b className="here" />
      </div>
      {now && (
        <div className="g-find">
          <button type="button" onClick={() => g.current?.look(now.sun_azimuth_deg, Math.max(2, now.sun_elevation_deg), 50)}>Look at the Sun</button>
          <button type="button" onClick={() => g.current?.look(now.earth_azimuth_deg, now.earth_elevation_deg, 9)}>Look at Earth (zoom)</button>
        </div>
      )}

      {st.status === 'loading' && <div className="g-msg">Loading this site's real horizon and 30 days of Sun and Earth…<div className="la-bar" /></div>}
      {st.status === 'error' && <div className="g-msg"><p className="la-err" role="alert">{st.message}</p></div>}

      {now && (
        <div className="g-sky">
          <p className="g-line">
            <i className="dot sun" />
            <span>{now.sun_visible_upper_limb
              ? <>Sun <b>{now.sun_elevation_deg.toFixed(1)}°</b> above the horizon{sunNext ? <>, sets in <b>{spanText(sunNext - cursorMs)}</b></> : <>, up for the rest of these {RUN_DAYS} days</>}</>
              : <>Sun hidden ({now.sun_elevation_deg < 0 ? 'below the horizon' : 'behind the hills'}){sunNext ? <>, rises in <b>{spanText(sunNext - cursorMs)}</b></> : <>, no sunrise in these {RUN_DAYS} days</>}</>}</span>
          </p>
          <p className="g-line">
            <i className="dot earth" />
            <span>{now.earth_center_clear
              ? <>Earth <b>{now.earth_elevation_deg.toFixed(1)}°</b> up, radio line of sight{earthNext ? <>, Earthset in <b>{spanText(earthNext - cursorMs)}</b></> : ''}</>
              : <>Earth hidden{earthNext ? <>, Earthrise in <b>{spanText(earthNext - cursorMs)}</b></> : ''}: no direct radio link</>}</span>
          </p>
          <p className="g-note">No air on the Moon: the sky stays black in daylight and the horizon is the terrain itself. The skyline is this site's real {st.status === 'ready' && st.run.settings.horizon_mode === 'terrain' ? 'LOLA terrain horizon' : 'horizon (flat here: no terrain map)'}; the ground in between and Earth's rotation are illustrative.</p>
        </div>
      )}

      {st.status === 'ready' && (
        <div className="g-battery">
          <div className="b-head">
            <span>Lander battery</span>
            <button type="button" className="la-mlink" onClick={() => setSettings((v) => !v)}>{settings ? 'Hide settings' : 'Settings'}</button>
          </div>
          <div className="b-gauge" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? 0} aria-label="Battery charge">
            <i style={{ width: `${pct ?? 100}%` }} className={pct !== null && pct < 20 ? 'low' : undefined} />
            <b>{pct === null ? 'not landed yet' : `${pct}%`}</b>
          </div>
          <p className={`b-verdict ${res.diedMs === null || madeIt ? 'good-c' : 'bad-c'}`}>
            {res.diedMs === null ? `Survives all ${RUN_DAYS} days` : madeIt ? `${missionDays}-day mission done; battery empty after ${spanText(res.diedMs - touchdownMs)}` : `Battery empty after ${spanText(res.diedMs - touchdownMs)}: mission fails`}
          </p>
          <div className="b-actions">
            <button type="button" className="la-btn primary" onClick={() => onPlay(playing ? null : (cursorMs < touchdownMs || cursorMs >= endMs ? touchdownMs : cursorMs))}>
              {playing ? 'Pause' : cursorMs <= touchdownMs + 60e3 ? 'Play the mission' : 'Keep playing'}
            </button>
            <button type="button" className="la-btn" onClick={() => onJump(touchdownMs)}>Back to touchdown</button>
          </div>
          {settings && (
            <div className="b-settings">
              <label>Panel <select value={panel} onChange={(e) => setPanel(e.target.value as PanelKind)}><option value="tracking">upright, follows the Sun</option><option value="flat">flat on the deck</option></select></label>
              <label>Panel power <input type="range" min={100} max={1500} step={50} value={panelW} onChange={(e) => setPanelW(Number(e.target.value))} /> {panelW} W</label>
              <label>Battery <input type="range" min={500} max={10000} step={250} value={batteryWh} onChange={(e) => setBatteryWh(Number(e.target.value))} /> {(batteryWh / 1000).toFixed(2)} kWh</label>
              <label>Power use <input type="range" min={10} max={300} step={5} value={loadW} onChange={(e) => setLoadW(Number(e.target.value))} /> {loadW} W</label>
              <label>Panel height <select value={mast} onChange={(e) => setMast(Number(e.target.value))}>{[0, 1, 2, 5, 10].map((m) => <option key={m} value={m}>{m} m mast</option>)}</select></label>
              <p className="g-note">Illustrative power model (your settings, not a real lander's); sunlight from the analysis. A taller mast sees over nearby hills (asks the backend again).</p>
            </div>
          )}
          <p className="g-note">Touchdown {fmt(touchdownMs)}. Now {fmt(cursorMs)}.</p>
        </div>
      )}
    </section>
  );
}
