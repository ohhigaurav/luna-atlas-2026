// The compare shelf: the chosen places side by side, as big cards, for the date in the date bar
// (challenge O1c: pick a date, pick sites, see them side by side). Plain words and badges from the
// API's leaders (no combined score); the full number table is one click away.
import { nextText, type CompareRow } from '../api/compare';
import type { ReferenceSite } from '../data/source';
import { shortName } from '../engine/pins';
import { useCompare } from './useCompare';

const BADGES: [string, string][] = [
  ['most_both', 'Best for working and talking'],
  ['most_sunlight', 'Most sunlight'],
  ['shortest_darkness', 'Shortest night'],
  ['longest_until_sunset', 'Longest until sunset'],
  ['most_earth', 'Most time with Earth in view'],
  ['longest_until_earthset', 'Longest until Earthset'],
  ['highest_sun_now', 'Highest Sun now'],
];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

type Props = {
  places: ReferenceSite[];
  live: boolean;
  cursorMs: number;
  suggest: (() => void) | null;
  onRemove: (id: string) => void;
  onOpen: (s: ReferenceSite) => void;
  onTable: () => void;
  onClear: () => void;
};

export function CompareShelf({ places, live, cursorMs, suggest, onRemove, onOpen, onTable, onClear }: Props) {
  const ids = places.map((p) => p.site_id);
  const st = useCompare(ids, cursorMs, 30, live && places.length >= 2);
  const r = st.s === 'ready' ? st.r : st.s === 'loading' ? st.last : null;
  const rows: (CompareRow | null)[] = places.map((p) => r?.rows.find((x) => x.site.site_id === p.site_id
    || (Math.abs(x.site.latitude_deg - p.latitude_deg) < 1e-3 && Math.abs(x.site.longitude_deg - p.longitude_deg) < 1e-3)) ?? null);
  const day = new Date(Math.round(cursorMs / 3600e3) * 3600e3).toLocaleString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' });

  return (
    <section className="la-shelf" aria-label="Compare">
      <header>
        <h3>Compare on {day} UTC</h3>
        <span className="sh-hint">{places.length < 2 ? 'Tap sites on the Moon to add them (up to 6).' : 'Change the date at the top and the cards follow.'}</span>
        <span className="la-spacer" />
        {suggest && places.length < 2 && <button type="button" className="la-btn" onClick={suggest}>Add the south-pole sites</button>}
        {places.length >= 2 && <button type="button" className="la-btn" onClick={onTable}>All numbers</button>}
        <button type="button" className="la-btn" onClick={onClear}>Close</button>
      </header>
      {st.s === 'loading' && <p className="sh-status" role="status">Checking {places.length} places, one at a time: about 10–20 s each the first time, instant after.</p>}
      {st.s === 'error' && <p className="sh-status la-err" role="alert">{st.m}</p>}
      {!live && <p className="sh-status">Comparing needs the live backend.</p>}
      <div className="sh-cards">
        {places.map((p, i) => {
          const row = rows[i];
          const badges = row && r && places.length >= 2 ? BADGES.filter(([k]) => (r.leaders[k] ?? []).includes(row.key)).map(([, l]) => l) : [];
          return (
            <article key={p.site_id} className={`sh-card${st.s === 'loading' ? ' stale' : ''}`}>
              <button type="button" className="sh-x" aria-label={`Remove ${p.name}`} onClick={() => onRemove(p.site_id)}>×</button>
              <button type="button" className="sh-name" onClick={() => onOpen(p)}>{shortName(p.name)}</button>
              {row ? (
                <>
                  <p className="sh-line"><i className={`dot sun${row.now.sun.up ? '' : ' off'}`} /><b>{row.now.sun.up ? `Sun ${row.now.sun.elevation_deg.toFixed(1)}°` : 'Sun down'}</b><span>{cap(nextText(row.sun_next, r!.days))}</span></p>
                  <p className="sh-line"><i className={`dot earth${row.now.earth.up ? '' : ' off'}`} /><b>{row.now.earth.up ? 'Earth in view' : 'Earth hidden'}</b><span>{cap(nextText(row.earth_next, r!.days))}</span></p>
                  <p className="sh-pct">Sunlit <b>{row.period.sunlit_percent.toFixed(0)}%</b> of the next {r!.days} days</p>
                  <div className="sh-badges">{badges.map((b) => <span key={b}>{b}</span>)}</div>
                </>
              ) : (
                <p className="sh-line dim">{places.length < 2 ? 'Add one more place' : 'Waiting…'}</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
