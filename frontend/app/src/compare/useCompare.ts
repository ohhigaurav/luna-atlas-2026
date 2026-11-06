// One compare question (places, moment, days) at a time, cached by question, so the site card,
// the compare shelf and the full table share answers. The moment is rounded to the hour so
// scrubbing does not ask the backend for every half hour (each new place-hour is a full check).
import { useEffect, useState } from 'react';
import { comparePlaces, type CompareResult } from '../api/compare';

const HOUR = 3600e3;
const cache = new Map<string, Promise<CompareResult>>();

export type CompareState =
  | { s: 'idle' }
  | { s: 'loading'; since: number; last: CompareResult | null }
  | { s: 'ready'; r: CompareResult }
  | { s: 'error'; m: string };

export function useCompare(ids: string[], atMs: number, days: number, enabled: boolean, delayMs = 600): CompareState {
  const [st, setSt] = useState<CompareState>({ s: 'idle' });
  const at = Math.round(atMs / HOUR) * HOUR;
  const key = JSON.stringify([ids, at, days]);
  useEffect(() => {
    if (!enabled || !ids.length) { setSt({ s: 'idle' }); return; }
    let off = false;
    const hit = cache.get(key);
    const go = () => {
      let p = cache.get(key);
      if (!p) {
        p = comparePlaces(ids, at, days);
        cache.set(key, p);
        p.catch(() => cache.delete(key));
      }
      setSt((prev) => ({ s: 'loading', since: performance.now(), last: prev.s === 'ready' ? prev.r : prev.s === 'loading' ? prev.last : null }));
      p.then((r) => { if (!off) setSt({ s: 'ready', r }); }, (e: Error) => { if (!off) setSt({ s: 'error', m: e.message }); });
    };
    const t = setTimeout(go, hit ? 0 : delayMs);
    return () => { off = true; clearTimeout(t); };
  }, [key, enabled]); // eslint-disable-line react-hooks/exhaustive-deps
  return st;
}
