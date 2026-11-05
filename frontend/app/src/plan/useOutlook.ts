// Asks /api/landing-windows for every site, one at a time, with the planner's default question
// (today 00:00 UTC, 90 days, 10-day mission, Sun at most 20 deg up at touchdown). The backend runs
// one analysis at a time and caches answers, so: the selected site goes first, flat-horizon sites
// next (seconds), polar terrain sites last (slower the first time), and nothing is asked twice.
import { useEffect, useRef, useState } from 'react';
import type { ReferenceSite } from '../data/source';
import { outlookOf, type Outlook } from '../state/outlook';
import { DEFAULT_MAX_SUN_DEG, DEFAULT_MISSION_DAYS, landingRequest, utcMidnight } from './usePlan';

export function useOutlook(sites: ReferenceSite[] | null, live: boolean, selectedId: string | null) {
  const [map, setMap] = useState<Record<string, Outlook>>({});
  const start = useRef(utcMidnight(Date.now()));
  const selRef = useRef(selectedId);
  selRef.current = selectedId;

  useEffect(() => {
    if (!sites || !live) return;
    let stop = false;
    const done = new Set<string>();
    setMap(Object.fromEntries(sites.map((s) => [s.site_id, { kind: 'pending' } as Outlook])));
    const order = [...sites].sort((a, b) => Number(a.latitude_deg <= -60) - Number(b.latitude_deg <= -60));
    (async () => {
      while (!stop && done.size < sites.length) {
        // The site in the user's hands jumps the queue.
        const next = order.find((s) => s.site_id === selRef.current && !done.has(s.site_id)) ?? order.find((s) => !done.has(s.site_id))!;
        done.add(next.site_id);
        let o: Outlook;
        try {
          o = outlookOf(await landingRequest(next.site_id, start.current, DEFAULT_MISSION_DAYS, DEFAULT_MAX_SUN_DEG), Date.now());
        } catch {
          o = { kind: 'error' };
        }
        if (stop) return;
        setMap((m) => ({ ...m, [next.site_id]: o }));
      }
    })();
    return () => { stop = true; };
  }, [sites, live]);

  return { outlook: map, startMs: start.current };
}
