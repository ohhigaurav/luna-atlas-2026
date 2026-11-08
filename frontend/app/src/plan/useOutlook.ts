// Asks /api/landing-windows for every site, one at a time, with the planner's default question
// (from today 00:00 UTC, or from the day the date bar rests on; 90 days, 10-day mission, Sun at most 20 deg up at touchdown). The backend runs
// one analysis at a time and caches answers, so: the selected site goes first, flat-horizon sites
// next (seconds), polar terrain sites last (slower the first time), and nothing is asked twice.
// lunar_core.warm asks the same questions when the server starts, so usually these are cache hits.
import { useEffect, useRef, useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { etaMs, OUTLOOK_DAYS, outlookOf, type Outlook, type Timing } from '../state/outlook';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS, SEARCH_DAYS, landingRequest } from './usePlan';

/** Which day the pins answer for: today by default, or the day the date bar rests on (walkthrough 8 Nov). */
/** searchMs: the landing search's start, the same rule as the site card's (today's 90-day search while
 *  it covers the next 30 days from the anchor, else a search from the anchor's own day), so pins and
 *  card share cache keys and a nearby date costs no new analysis. */
export type OutlookAnchor = { dayMs: number; atMs: number; searchMs: number };

const DAY = 86400e3;
export function anchorFor(atMs: number, nowMs: number, utcMidnight: (ms: number) => number): OutlookAnchor {
  const away = Math.abs(atMs - nowMs) > DAY;
  const at = away ? atMs : nowMs, dayMs = utcMidnight(at), today = utcMidnight(nowMs);
  const covered = at >= today && at + OUTLOOK_DAYS * DAY <= today + SEARCH_DAYS * DAY;
  return { dayMs, atMs: at, searchMs: covered ? today : dayMs };
}

export function useOutlook(sites: ReferenceSite[] | null, live: boolean, selectedId: string | null, anchor: OutlookAnchor) {
  // Answers stay on screen when the day changes (greyed by the caller) until the new day's answer
  // for that site arrives; `fresh` holds the sites already answered for the current day.
  const [st, setSt] = useState<{ day: number; map: Record<string, Outlook>; fresh: Set<string> }>({ day: anchor.dayMs, map: {}, fresh: new Set() });
  // Progress for the "finding landing windows" timer: when the last answer came and the time left then.
  const [progress, setProgress] = useState<{ etaMs: number | null; at: number }>({ etaMs: null, at: 0 });
  const selRef = useRef(selectedId);
  selRef.current = selectedId;
  const atRef = useRef(anchor.atMs);
  atRef.current = anchor.atMs;
  const searchRef = useRef(anchor.searchMs);
  searchRef.current = anchor.searchMs;

  useEffect(() => {
    if (!sites || !live) return;
    let stop = false;
    const done = new Set<string>();
    const day = anchor.dayMs;
    setSt((p) => ({ day, fresh: new Set(), map: Object.keys(p.map).length ? p.map : Object.fromEntries(sites.map((s) => [s.site_id, { kind: 'pending' } as Outlook])) }));
    const polar = (s: ReferenceSite) => s.latitude_deg <= -60;
    // Flat sites first (fast), but time one polar site second so the "time left" estimate knows
    // both kinds early instead of jumping when the slow ones start.
    const flat = sites.filter((s) => !polar(s)), pole = sites.filter(polar);
    const order = [...flat.slice(0, 1), ...pole.slice(0, 1), ...flat.slice(1), ...pole.slice(1)];
    const timings: Timing[] = [];
    (async () => {
      while (!stop && done.size < sites.length) {
        // The site in the user's hands jumps the queue.
        const next = order.find((s) => s.site_id === selRef.current && !done.has(s.site_id)) ?? order.find((s) => !done.has(s.site_id))!;
        done.add(next.site_id);
        let o: Outlook;
        const t0 = performance.now();
        try {
          o = outlookOf(await landingRequest(next.site_id, searchRef.current, DEFAULT_MISSION_DAYS, DEFAULT_MAX_SUN_DEG), atRef.current);
        } catch {
          o = { kind: 'error' };
        }
        if (stop) return;
        timings.push({ polar: polar(next), ms: performance.now() - t0 });
        const left = order.filter((s) => !done.has(s.site_id));
        setProgress({ etaMs: etaMs(timings, { polar: left.filter(polar).length, flat: left.filter((s) => !polar(s)).length }), at: performance.now() });
        setSt((p) => (p.day !== day ? p : { day, map: { ...p.map, [next.site_id]: o }, fresh: new Set(p.fresh).add(next.site_id) }));
      }
    })();
    return () => { stop = true; };
  }, [sites, live, anchor.dayMs]);

  return { outlook: st.map, fresh: st.fresh, startMs: anchor.dayMs, progress };
}
