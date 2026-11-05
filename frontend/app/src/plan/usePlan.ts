// State and data for the Phase 2 planner (an internal document (not published), F17/F18): one site, a 90-day
// search window, a mission length, a launch knob. Landing windows come from /api/landing-windows;
// the ring's sunlight / Earth bands from /api/check (max 60 days per call, so two cached calls).
// Every request is cached by its body, so going back to a setting is instant.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, checkSite, findLandingWindows, type CheckResult, type LandingResult, type UtcRange } from '../api/plan';
import { nextLanding, type Answer } from './answer';

export const SEARCH_DAYS = 90;
export const DEFAULT_MISSION_DAYS = 10;
export const DEFAULT_MAX_SUN_DEG = 20;

/** One landing question, as the planner and the pin outlook both ask it (shared cache key). */
export function landingRequest(siteId: string, startMs: number, missionDays: number, maxSunDeg: number | null) {
  return cached(JSON.stringify(['L', siteId, startMs, missionDays, maxSunDeg]),
    () => findLandingWindows(siteId, startMs, SEARCH_DAYS, missionDays, undefined, maxSunDeg));
}
const DAY = 86400e3;

export type PlanSettings = {
  searchStartMs: number;   // ring start (00:00 UTC of a day)
  missionDays: number;     // 1-14
  maxSunDeg: number | null;
  notBeforeMs: number;     // launch knob
};

export type PlanData =
  | { status: 'idle' }
  | { status: 'loading'; since: number }
  | { status: 'ready'; landing: LandingResult; bands: { sun: UtcRange[]; earth: UtcRange[] } | null; horizonMode: string | null }
  | { status: 'error'; message: string };

const cache = new Map<string, Promise<unknown>>();
export function cached<T>(key: string, make: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = make();
    cache.set(key, p);
    p.catch(() => cache.delete(key)); // never cache a failure
  }
  return p;
}

export function utcMidnight(ms: number): number {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

export function usePlan(siteId: string | null, live: boolean, nowMs: number) {
  const [settings, setSettings] = useState<PlanSettings>(() => {
    const start = utcMidnight(Date.now());
    return { searchStartMs: start, missionDays: DEFAULT_MISSION_DAYS, maxSunDeg: DEFAULT_MAX_SUN_DEG, notBeforeMs: start };
  });
  const [data, setData] = useState<PlanData>({ status: 'idle' });
  const seq = useRef(0);

  const { searchStartMs, missionDays, maxSunDeg } = settings;
  useEffect(() => {
    if (!siteId || !live) { setData({ status: 'idle' }); return; }
    const my = ++seq.current;
    // Mission-length drags fire often: wait for the hand to settle, then ask.
    const t = setTimeout(() => {
      setData({ status: 'loading', since: performance.now() });
      const landingP = landingRequest(siteId, searchStartMs, missionDays, maxSunDeg);
      landingP.then(
        (landing) => {
          if (my !== seq.current) return;
          setData({ status: 'ready', landing, bands: null, horizonMode: landing.horizon_mode });
          // Bands are asked for only after the answer: the backend runs one analysis at a time, so
          // the answer never queues behind them.
          const c1 = cached(JSON.stringify(['C', siteId, searchStartMs, 60]), () => checkSite(siteId, searchStartMs, 60));
          const c2 = cached(JSON.stringify(['C', siteId, searchStartMs + 60 * DAY, 30]),
            () => checkSite(siteId, searchStartMs + 60 * DAY, SEARCH_DAYS - 60));
          Promise.all([c1, c2]).then(([a, b]: [CheckResult, CheckResult]) => {
            if (my !== seq.current) return;
            setData({ status: 'ready', landing, horizonMode: a.chosen_settings.horizon_mode,
              bands: { sun: [...a.summary.bands.sun, ...b.summary.bands.sun], earth: [...a.summary.bands.earth, ...b.summary.bands.earth] } });
          }, () => { /* the answer stands without bands */ });
        },
        (e: unknown) => {
          if (my !== seq.current) return;
          setData({ status: 'error', message: e instanceof ApiError ? `${e.message} (HTTP ${e.status})` : (e as Error).message });
        },
      );
    }, 350);
    return () => clearTimeout(t);
  }, [siteId, live, searchStartMs, missionDays, maxSunDeg]);

  const answer: Answer | null = useMemo(
    () => (data.status === 'ready' ? nextLanding(data.landing, settings.notBeforeMs, nowMs) : null),
    [data, settings.notBeforeMs, nowMs],
  );

  const update = useCallback((patch: Partial<PlanSettings>) => setSettings((s) => {
    const next = { ...s, ...patch };
    next.missionDays = Math.min(14, Math.max(1, Math.round(next.missionDays)));
    // Keep the knob on the ring.
    next.notBeforeMs = Math.min(next.searchStartMs + SEARCH_DAYS * DAY, Math.max(next.searchStartMs, next.notBeforeMs));
    return next;
  }), []);

  return { settings, update, data, answer };
}
