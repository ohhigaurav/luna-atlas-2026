// "Launch slipped?" (task 5): move the earliest launch by a week, a month or three months and show
// the soonest landing window here and at the nearest catalogue sites. Same question as the pins and
// Compare (useNextLanding → /api/landing-windows, cached): mission length from the card, default
// rules. One place at a time, so the first answer for a new date takes a while.
import { useState } from 'react';
import { useNextLanding } from '../compare/useNextLanding';
import type { NextLanding } from '../compare/nextLanding';
import type { ReferenceSite } from '../data/source';
import { spanText } from '../state/siteState';
import { DEFAULT_MAX_SUN_DEG } from './usePlan';

const MOON_RADIUS_KM = 1737.4;
const NEARBY = 3;
const NEARBY_MAX_KM = 800;
const DAY = 86400e3;

export type Slip = { label: string; add: (ms: number) => number };
/** Calendar months, so "1 month" from 31 Jan is 3 Mar in a short year (the UTC calendar decides). */
const months = (n: number) => (ms: number) => { const d = new Date(ms); d.setUTCMonth(d.getUTCMonth() + n); return d.getTime(); };
export const SLIPS: Slip[] = [
  { label: '1 week', add: (ms) => ms + 7 * DAY },
  { label: '1 month', add: months(1) },
  { label: '3 months', add: months(3) },
];

/** Great-circle distance on a sphere of the Moon's mean radius (km). */
export function distanceKm(a: { latitude_deg: number; longitude_deg: number }, b: { latitude_deg: number; longitude_deg: number }): number {
  const r = Math.PI / 180, p1 = a.latitude_deg * r, p2 = b.latitude_deg * r, dl = (b.longitude_deg - a.longitude_deg) * r;
  const h = Math.sin((p2 - p1) / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * MOON_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** The nearest other catalogue sites within NEARBY_MAX_KM (clicked points are not candidates). */
export function nearbySites(site: ReferenceSite, sites: ReferenceSite[], n = NEARBY, maxKm = NEARBY_MAX_KM): { s: ReferenceSite; km: number }[] {
  return sites
    .filter((x) => x.site_id !== site.site_id && !x.site_id.startsWith('point:'))
    .map((s) => ({ s, km: distanceKm(site, s) }))
    .filter((x) => x.km <= maxKm)
    .sort((a, b) => a.km - b.km)
    .slice(0, n);
}

/** Soonest first; places with no window, still checking or failed after them. */
export function rankBySoonest<T extends { n: NextLanding }>(xs: T[]): T[] {
  const k = (x: T) => (x.n.kind === 'window' ? x.n.fromMs : x.n.kind === 'none' ? Infinity : Number.MAX_VALUE);
  return [...xs].sort((a, b) => k(a) - k(b));
}

const day = (ms: number) => new Date(ms).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

type Props = {
  site: ReferenceSite;
  sites: ReferenceSite[];
  cursorMs: number;
  missionDays: number;
  live: boolean;
  /** Opens a site with the date bar at ms. */
  onOpenAt: (s: ReferenceSite, ms: number) => void;
};

function Answer({ n, fromMs }: { n: NextLanding; fromMs: number }) {
  if (n.kind === 'pending') return <span className="dim-c">Checking…</span>;
  if (n.kind === 'error') return <span className="dim-c">Could not check</span>;
  if (n.kind === 'none') return <span className="dim-c">No window through {day(n.throughMs)}</span>;
  if (n.openAt) return <span className="good-c">Open on {day(fromMs)}</span>;
  return <span>From <b>{day(n.fromMs)}</b>, {spanText(n.fromMs - fromMs)} after the new launch date</span>;
}

export function SlipPanel({ site, sites, cursorMs, missionDays, live, onOpenAt }: Props) {
  const [open, setOpen] = useState(false);
  const [slip, setSlip] = useState<Slip | null>(null);
  const near = nearbySites(site, sites);
  const fromMs = slip ? slip.add(cursorMs) : cursorMs;
  const land = useNextLanding([site.site_id, ...near.map((x) => x.s.site_id)], fromMs, missionDays, live && !!slip);
  const here = land[site.site_id] ?? { kind: 'pending' };
  const ranked = rankBySoonest(near.map((x) => ({ ...x, n: land[x.s.site_id] ?? ({ kind: 'pending' } as NextLanding) })));
  const pending = Object.values(land).filter((x) => x.kind === 'pending').length;

  if (!open) {
    return (
      <div className="sc-slip">
        <button type="button" className="la-btn" onClick={() => setOpen(true)} disabled={!live}>Launch slipped?</button>
      </div>
    );
  }
  return (
    <section className="sc-slip open" aria-label="Launch slipped">
      <div className="sl-head">
        <span>Launch slips by</span>
        {SLIPS.map((s) => (
          <button key={s.label} type="button" className={slip?.label === s.label ? 'on' : undefined} aria-pressed={slip?.label === s.label} onClick={() => setSlip(s)}>{s.label}</button>
        ))}
        <button type="button" className="sl-x" aria-label="Close" onClick={() => { setOpen(false); setSlip(null); }}>×</button>
      </div>
      {!slip && <p className="sl-note">Pick how late the launch is. The search starts from {day(cursorMs)} (the date bar) plus the delay.</p>}
      {slip && (
        <>
          <p className="sl-new">New earliest launch: <b>{day(fromMs)}</b> ({day(cursorMs)} + {slip.label}).</p>
          <div className="sl-row here">
            <span className="sl-name">Here</span>
            <Answer n={here} fromMs={fromMs} />
            {here.kind === 'window' && <button type="button" className="la-btn" onClick={() => onOpenAt(site, here.bestMs)}>Go to {day(here.bestMs)}</button>}
          </div>
          {near.length > 0 ? (
            <>
              <p className="sl-sub">Nearest sites, soonest window first</p>
              {ranked.map(({ s, km, n }) => (
                <div key={s.site_id} className="sl-row">
                  <span className="sl-name">{s.name}<small>{Math.round(km)} km away</small></span>
                  <Answer n={n} fromMs={fromMs} />
                  {n.kind === 'window' && <button type="button" className="la-btn" onClick={() => onOpenAt(s, n.bestMs)}>Open at {day(n.bestMs)}</button>}
                </div>
              ))}
            </>
          ) : <p className="sl-sub">No other catalogue site within {NEARBY_MAX_KM} km.</p>}
          <p className="sl-note">
            Same question as the pins: a {missionDays}-day mission in sunlight, Earth in view at touchdown, Sun at most {DEFAULT_MAX_SUN_DEG}° up.
            {pending > 0 && ` Checking one place at a time (${pending} left); new dates take about 10–60 s each the first time.`}
          </p>
        </>
      )}
    </section>
  );
}
