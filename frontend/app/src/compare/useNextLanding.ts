// For each compared place, the next landing window at or after the compare moment. Asks
// /api/landing-windows one place at a time (the backend runs one analysis at a time), first with
// today's search (the warm, cached question the pins use), and, when that finds nothing after the
// moment, again from the moment's own day. Answers are shared through landingRequest's cache.
import { useEffect, useRef, useState } from 'react';
import type { LandingResult } from '../api/plan';
import { DEFAULT_MAX_SUN_DEG, SEARCH_DAYS, landingRequest, utcMidnight } from '../plan/usePlan';
import { nextLandingAt, searchStartFor, type NextLanding } from './nextLanding';

type Got = { results: LandingResult[] } | 'pending' | 'error';

export function useNextLanding(ids: string[], atMs: number, missionDays: number, enabled: boolean): Record<string, NextLanding> {
  // Answers are stored with the question they answer, so a changed date range or mission length
  // shows "Checking…" at once instead of the old answers under the new label.
  const [store, setStore] = useState<{ key: string; got: Record<string, Got> }>({ key: '', got: {} });
  const today = utcMidnight(Date.now());
  const start = searchStartFor(atMs, today, SEARCH_DAYS);
  const atRef = useRef(atMs);
  atRef.current = atMs;
  const key = JSON.stringify([ids, start, missionDays]);

  useEffect(() => {
    if (!enabled || !ids.length) return;
    let stop = false;
    setStore({ key, got: {} });
    (async () => {
      for (const id of ids) {
        let g: Got;
        try {
          const results = [await landingRequest(id, start, missionDays, DEFAULT_MAX_SUN_DEG)];
          const own = utcMidnight(atRef.current);
          if (!stop && own !== start && nextLandingAt(results, atRef.current).kind === 'none') {
            results.push(await landingRequest(id, own, missionDays, DEFAULT_MAX_SUN_DEG));
          }
          g = { results };
        } catch {
          g = 'error';
        }
        if (stop) return;
        setStore((m) => (m.key === key ? { key, got: { ...m.got, [id]: g } } : m));
      }
    })();
    return () => { stop = true; };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  const got = store.key === key ? store.got : {};
  return Object.fromEntries(ids.map((id) => {
    const g = got[id];
    return [id, !g || g === 'pending' ? { kind: 'pending' } : g === 'error' ? { kind: 'error' } : nextLandingAt(g.results, atMs)];
  }));
}
