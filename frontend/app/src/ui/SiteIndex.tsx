// Left rail: every site with its live state (PRD F24 "Right now on the Moon"): Sun up or down
// over a flat horizon at the clock's time, and when that changes. Polar sites carry the same
// geometry but hills decide there, so the column says "no terrain" and the site's own run (terrain
// where it exists) is the number to trust.
import type { ReferenceSite } from '../data/source';
import { shortName } from '../engine/pins';
import { spanText, type SiteNow } from '../state/siteState';

type Props = {
  sites: ReferenceSite[];
  states: Record<string, SiteNow>;
  cursorMs: number;
  selectedId: string | null;
  onPick: (s: ReferenceSite) => void;
  onSearch: () => void;
  onProof: () => void;
};

const GROUPS: { key: string; title: string; test: (s: ReferenceSite) => boolean }[] = [
  { key: 'pole', title: 'South polar region', test: (s) => s.latitude_deg <= -75 },
  { key: 'clps', title: 'CLPS', test: (s) => (s.group ?? '').startsWith('CLPS') },
  { key: 'apollo', title: 'Apollo', test: (s) => s.group === 'Apollo' },
  { key: 'other', title: 'Other landers', test: () => true },
];

function coord(lat: number, lon: number): string {
  const e = lon > 180 ? lon - 360 : lon;
  return `${Math.abs(lat).toFixed(2)}°${lat < 0 ? 'S' : 'N'}  ${Math.abs(e).toFixed(2)}°${e < 0 ? 'W' : 'E'}`;
}

export function SiteIndex({ sites, states, cursorMs, selectedId, onPick, onSearch, onProof }: Props) {
  const placed = new Set<string>();
  const groups = GROUPS.map((g) => {
    const members = sites.filter((s) => !placed.has(s.site_id) && g.test(s));
    members.forEach((s) => placed.add(s.site_id));
    return { ...g, members };
  }).filter((g) => g.members.length);

  return (
    <nav className="la-rail" aria-label="Landing sites">
      <div className="la-rail-head">
        <h1>Where and when can you land on the Moon?</h1>
        <p>Pick a site. Luna Atlas finds the touchdown dates when the Sun stays up for the whole mission and Earth stays in view for the radio link.</p>
        <button type="button" className="la-search" onClick={onSearch}>
          Search sites or type a date
          <span className="la-k">Ctrl K</span>
        </button>
      </div>
      <div className="la-colhead">
        <span className="la-cap">{sites.length} sites</span>
        <span className="la-cap" title="Sun over a smooth sphere at the clock's time. Hills are not included here.">Sun now, flat ground</span>
      </div>
      <div className="la-list">
        {groups.map((g) => (
          <div key={g.key} role="group" aria-label={g.title}>
            <div className="la-group"><span className="la-cap">{g.title}</span><span className="la-cap">{g.members.length}</span></div>
            {g.members.map((s) => {
              const st = states[s.site_id];
              const change = st?.nextChangeMs != null ? spanText(st.nextChangeMs - cursorMs) : null;
              return (
                <button key={s.site_id} type="button" className={`la-site${s.site_id === selectedId ? ' sel' : ''}`} onClick={() => onPick(s)}
                  aria-current={s.site_id === selectedId ? 'true' : undefined}>
                  <i className={`la-sw ${st ? (st.day ? 'day' : 'night') : ''}`} aria-hidden="true" />
                  <span className="nm">{shortName(s.name)}</span>
                  <span className="co">{coord(s.latitude_deg, s.longitude_deg)}</span>
                  {st && (
                    <span className="st">
                      <span className={st.day ? 'sun-c' : undefined}>{st.day ? 'Day' : 'Night'}</span>
                      <small>{change ? `${st.day ? 'sets' : 'rises'} ${change}` : `${st.day ? 'up' : 'dark'} ${spanText(st.horizonMs - cursorMs)}+`}</small>
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="la-rail-foot">
        <button type="button" className="la-proofbtn" onClick={onProof}>
          <b>5/6</b>
          <span>Our shadows vs real LRO photos</span>
          <small>also 6/7 real missions · JPL Horizons 0.04″</small>
        </button>
      </div>
    </nav>
  );
}
