// Asks /api/landing-windows for every site, one at a time, with the planner's default question
// (today 00:00 UTC, 90 days, 10-day mission, Sun at most 20 deg up at touchdown). The backend runs
// one analysis at a time and caches answers, so: the selected site goes first, flat-horizon sites
// next (seconds), polar terrain sites last (slower the first time), and nothing is asked twice.
// lunar_core.warm asks the same questions when the server starts, so usually these are cache hits.
import { appNow } from '../data/staticMode';
import { useEffect, useRef, useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { etaMs, outlookOf, type Outlook, type Timing } from '../state/outlook';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS, landingRequest, utcMidnight } from './usePlan';

export function useOutlook(sites: ReferenceSite[] | null, live: boolean, selectedId: string | null) {
  const [map, setMap] = useState<Record<string, Outlook>>({});
  // Progress for the "finding landing windows" timer: when the last answer came and the time left then.
  const [progress, setProgress] = useState<{ etaMs: number | null; at: number }>({ etaMs: null, at: 0 });
  const start = useRef(utcMidnight(appNow()));
  const selRef = useRef(selectedId);
  selRef.current = selectedId;

  useEffect(() => {
    if (!sites || !live) return;
    let stop = false;
    const done = new Set<string>();
    setMap(Object.fromEntries(sites.map((s) => [s.site_id, { kind: 'pending' } as Outlook])));
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
          o = outlookOf(await landingRequest(next.site_id, start.current, DEFAULT_MISSION_DAYS, DEFAULT_MAX_SUN_DEG), appNow());
        } catch {
          o = { kind: 'error' };
        }
        if (stop) return;
        timings.push({ polar: polar(next), ms: performance.now() - t0 });
        const left = order.filter((s) => !done.has(s.site_id));
        setProgress({ etaMs: etaMs(timings, { polar: left.filter(polar).length, flat: left.filter((s) => !polar(s)).length }), at: performance.now() });
        setMap((m) => ({ ...m, [next.site_id]: o }));
      }
    })();
    return () => { stop = true; };
  }, [sites, live]);

  return { outlook: map, startMs: start.current, progress };
}
