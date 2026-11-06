// The chart's title block with its legend and gazetteer (PRD F24, "Right now on the Moon"):
// every site with its landing outlook (green: a window opens within 30 days, from
// /api/landing-windows) and whether the Sun is up there now (flat ground, from sky-geometry).
import type { ReferenceSite } from '../data/source';
import { shortName } from '../engine/pins';
import { OUTLOOK_DAYS, outlookText, type Outlook } from '../state/outlook';
import { spanText, type SiteNow } from '../state/siteState';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS } from '../plan/usePlan';

type Props = {
  sites: ReferenceSite[];
  live: boolean;
  states: Record<string, SiteNow>;
  outlook: Record<string, Outlook>;
  cursorMs: number;
  onPick: (s: ReferenceSite) => void;
  onSearch: () => void;
  onProof: () => void;
  onForecast: (() => void) | null;
  onComparePolar: (() => void) | null;
};

const GROUPS: { key: string; title: string; test: (s: ReferenceSite) => boolean }[] = [
  { key: 'pole', title: 'South polar region', test: (s) => s.latitude_deg <= -75 },
  { key: 'clps', title: 'Commercial landers (CLPS)', test: (s) => (s.group ?? '').startsWith('CLPS') },
  { key: 'apollo', title: 'Apollo', test: (s) => s.group === 'Apollo' },
  { key: 'other', title: 'Other landers', test: () => true },
];

function coord(lat: number, lon: number): string {
  const e = lon > 180 ? lon - 360 : lon;
  return `${Math.abs(lat).toFixed(2)}° ${lat < 0 ? 'S' : 'N'}, ${Math.abs(e).toFixed(2)}° ${e < 0 ? 'W' : 'E'}`;
}

export function Symbol({ kind }: { kind: 'window' | 'day' | 'night' }) {
  return <i className={`la-sym ${kind}`} aria-hidden="true" />;
}

export function Gazetteer({ sites, live, states, outlook, cursorMs, onPick, onSearch, onProof, onForecast, onComparePolar }: Props) {
  const placed = new Set<string>();
  const groups = GROUPS.map((g) => {
    const members = sites.filter((s) => !placed.has(s.site_id) && g.test(s));
    members.forEach((s) => placed.add(s.site_id));
    return { ...g, members };
  }).filter((g) => g.members.length);
  const vals = Object.values(outlook);
  const green = vals.filter((o) => o.kind === 'window').length;
  const checked = vals.filter((o) => o.kind !== 'pending').length;
  const day = sites.filter((s) => states[s.site_id]?.day).length;

  return (
    <nav className="la-carto-body" aria-label="Landing sites">
      <header className="la-title">
        <h1>Where and when can you land on the Moon?</h1>
        <p>Pick a site to see its next landing window: the Sun up for the whole mission and Earth in view for the radio link.</p>
      </header>

      <section className="la-key" aria-label="Legend">
        {live && (
          <div className="row"><Symbol kind="window" /><span>Landing window within {OUTLOOK_DAYS} days</span><b>{green}</b></div>
        )}
        <div className="row"><Symbol kind="day" /><span>Sun up now</span><b>{day}</b></div>
        <div className="row"><Symbol kind="night" /><span>Night now</span><b>{sites.length - day}</b></div>
        <p className="la-fine">
          {live
            ? <>Windows: {DEFAULT_MISSION_DAYS}-day mission, Sun at most {DEFAULT_MAX_SUN_DEG}° up and Earth in view at touchdown; real terrain near the pole. {checked < sites.length ? `Checking: ${checked} of ${sites.length} done.` : `All ${sites.length} checked.`}</>
            : <>Landing windows need the live backend. Day and night here are for flat ground.</>}
        </p>
      </section>

      {onForecast && (
        <button type="button" className="la-fcbtn" onClick={onForecast}>
          <b>Moon weather forecast</b>
          <span>Watch sunlight and Earth's line of sight sweep the south pole, every 2 hours through January 2027</span>
        </button>
      )}

      <button type="button" className="la-search" onClick={onSearch}>
        <span>Find a site or type a date</span><kbd>Ctrl K</kbd>
      </button>

      <div className="la-list">
        {groups.map((g) => (
          <div key={g.key} role="group" aria-label={g.title}>
            <h3 className="la-group">{g.title}
              {g.key === 'pole' && onComparePolar && <button type="button" className="la-grouplink" onClick={onComparePolar}>Compare these</button>}
            </h3>
            {g.members.map((s) => {
              const st = states[s.site_id], o = outlook[s.site_id];
              const change = st?.nextChangeMs != null ? spanText(st.nextChangeMs - cursorMs) : null;
              const sym = o?.kind === 'window' ? 'window' : st?.day ? 'day' : 'night';
              return (
                <button key={s.site_id} type="button" className="la-site" onClick={() => onPick(s)}>
                  <Symbol kind={sym} />
                  <span className="nm">{shortName(s.name)}</span>
                  <span className={`st ${o?.kind ?? ''}`}>{live && o ? outlookText(o) : ''}</span>
                  <span className="co">{coord(s.latitude_deg, s.longitude_deg)}</span>
                  <span className="dn">
                    {st ? `${st.day ? 'sunset' : 'sunrise'} ${change ?? `${spanText(st.horizonMs - cursorMs)}+`}, Earth${st.earthUp ? 'set' : 'rise'} ${st.earthNextMs != null ? spanText(st.earthNextMs - cursorMs) : `${spanText(st.horizonMs - cursorMs)}+`}` : ''}
                  </span>
                </button>
              );
            })}
          </div>
        ))}
      </div>

      <button type="button" className="la-proofbtn" onClick={onProof}>
        <b>5 of 6</b>
        <span>LRO photos match our shadows</span>
        <small>6 of 7 real missions · JPL Horizons within 0.04″ · see the evidence</small>
      </button>
    </nav>
  );
}
