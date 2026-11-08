// The pin key on the home card, and the answer to "which ones, and why?": each line opens the list
// of sites behind its number, with the reason in words, and a tap flies to the site.
// Green comes from /api/landing-windows (terrain where it exists, today's 90-day search); sunlit and
// night come from sky geometry over a smooth sphere at the date-bar time, so they say "no hills".
import { appNow } from '../data/staticMode';
import { useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { OUTLOOK_DAYS, type Outlook } from '../state/outlook';
import { missText } from '../state/rules';
import { terrainText } from '../state/terrain';
import { spanText, type SiteNow } from '../state/siteState';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS, utcMidnight } from '../plan/usePlan';

type Group = 'green' | 'day' | 'night';
type Props = {
  sites: ReferenceSite[];
  states: Record<string, SiteNow>;
  outlook: Record<string, Outlook>;
  /** Sites already answered for the anchor day; others still show the previous day's answer. */
  fresh: Set<string>;
  /** The day the pins answer for (today, or where the date bar rests). */
  anchor: { dayMs: number; atMs: number };
  live: boolean;
  cursorMs: number;
  onPick: (s: ReferenceSite) => void;
};

const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const deg = (x: number) => `${Math.abs(x).toFixed(1)}°`;
/** Ascending, with Infinity ("not in the window") last and no NaN from Infinity - Infinity. */
const asc = (a: number, b: number) => (a === b ? 0 : a < b ? -1 : 1);

type Row = { site: ReferenceSite; main: string; why: string; sort: number };

function greenRows(sites: ReferenceSite[], outlook: Record<string, Outlook>, fresh: Set<string>, nowMs: number): { yes: Row[]; no: Row[]; pending: number } {
  const yes: Row[] = [], no: Row[] = [];
  let pending = 0;
  for (const site of sites) {
    const o = outlook[site.site_id];
    if (!o || o.kind === 'pending' || !fresh.has(site.site_id)) { pending++; continue; }
    if (o.kind === 'window') {
      yes.push({ site, sort: o.fromMs, main: o.openNow ? 'Land now' : `Land from ${day(o.fromMs)}`,
        why: `${o.openNow ? `best touchdown ${day(o.bestMs)}` : `in ${spanText(o.fromMs - nowMs)}, best ${day(o.bestMs)}`} · ${terrainText(o.horizonMode, o.terrainM)}` });
    } else if (o.kind === 'none') {
      no.push({ site, sort: o.laterMs ?? Infinity, main: o.laterMs ? `Next ${day(o.laterMs)}` : 'None in 90 days',
        why: `${o.laterMs ? `after the ${OUTLOOK_DAYS}-day mark` : o.miss ? `closest try ${day(o.miss.atMs)}: ${missText(o.miss)}` : 'the Sun never stays up long enough'} · ${terrainText(o.horizonMode, o.terrainM)}` });
    } else {
      no.push({ site, sort: Infinity, main: 'Not checked', why: 'the backend did not answer' });
    }
  }
  return { yes: yes.sort((a, b) => asc(a.sort, b.sort)), no: no.sort((a, b) => asc(a.sort, b.sort)), pending };
}

function skyRows(sites: ReferenceSite[], states: Record<string, SiteNow>, cursorMs: number, sunlit: boolean): Row[] {
  return sites.flatMap((site) => {
    const s = states[site.site_id];
    if (!s || s.day !== sunlit) return [];
    const change = s.nextChangeMs === null
      ? `no ${sunlit ? 'sunset' : 'sunrise'} before ${day(s.horizonMs)}`
      : `${sunlit ? 'sets' : 'rises'} in ${spanText(s.nextChangeMs - cursorMs)}`;
    return [{ site, sort: s.nextChangeMs ?? Infinity, main: sunlit ? (s.sunElDeg < 0.3 ? 'Sun on the horizon' : `Sun ${deg(s.sunElDeg)} up`) : `Sun ${deg(s.sunElDeg)} down`, why: `${change}; Earth ${s.earthUp ? 'in view' : 'hidden'}` }];
  }).sort((a, b) => (sunlit ? asc(b.sort, a.sort) : asc(a.sort, b.sort)));
}

function List({ rows, onPick }: { rows: Row[]; onPick: (s: ReferenceSite) => void }) {
  return (
    <ul className="pk-list">
      {rows.map((r) => (
        <li key={r.site.site_id}>
          <button type="button" onClick={() => onPick(r.site)}>
            <span className="pk-name">{r.site.name}</span>
            <span className="pk-main">{r.main}</span>
            <span className="pk-why">{r.why}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function PinKey({ sites, states, outlook, fresh, anchor, live, cursorMs, onPick }: Props) {
  const [open, setOpen] = useState<Group | null>(null);
  const today = utcMidnight(appNow()) === anchor.dayMs;
  const from = today ? appNow() : anchor.atMs;
  const g = greenRows(sites, outlook, fresh, from);
  const day_ = skyRows(sites, states, cursorMs, true), night = skyRows(sites, states, cursorMs, false);
  const line = (k: Group, sym: string, label: string, n: number) => (
    <button type="button" className={`pk-line${open === k ? ' on' : ''}`} aria-expanded={open === k} onClick={() => setOpen(open === k ? null : k)}>
      <i className={`la-sym ${sym}`} />{label}<b>{n}</b><span className="pk-chev" aria-hidden>{open === k ? '−' : '+'}</span>
    </button>
  );
  return (
    <div className="hl-key" aria-label="What the pin colours mean; open a line to see the sites and why">
      {live && line('green', 'window', `Can land within ${OUTLOOK_DAYS} days${today ? '' : ` from ${day(anchor.dayMs)}`}`, g.yes.length)}
      {open === 'green' && (
        <div className="pk-open">
          <p className="pk-rule">Green means a {DEFAULT_MISSION_DAYS}-day mission can start here: Sun up with at least {DEFAULT_MISSION_DAYS} days of daylight left, Earth in view at touchdown, Sun at most {DEFAULT_MAX_SUN_DEG}° high. Checked from {today ? 'today' : day(anchor.dayMs)}, with the hills where we have a terrain map (each line says which).</p>
          <List rows={g.yes} onPick={onPick} />
          {g.no.length > 0 && <><p className="pk-sub">Not within {OUTLOOK_DAYS} days ({g.no.length})</p><List rows={g.no} onPick={onPick} /></>}
          {g.pending > 0 && <p className="pk-sub">Still checking {g.pending}…</p>}
        </div>
      )}
      {line('day', 'day', 'Sunlit now', day_.length)}
      {open === 'day' && (
        <div className="pk-open">
          <p className="pk-rule">The Sun's top edge is above a flat horizon at the date-bar time. No hills in this estimate: open a site for the terrain answer.</p>
          <List rows={day_} onPick={onPick} />
        </div>
      )}
      {line('night', 'night', 'Night now', night.length)}
      {open === 'night' && (
        <div className="pk-open">
          <p className="pk-rule">The Sun is below a flat horizon at the date-bar time (no hills). Sorted by the next sunrise.</p>
          <List rows={night} onPick={onPick} />
        </div>
      )}
    </div>
  );
}
