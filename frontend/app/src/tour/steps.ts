// Guided tour (challenge C13, PRD F9): two short chapters over the real UI. The tour drives the
// app (sets the date, opens a site, opens Compare, ...) through the same callbacks a click uses;
// it makes no API calls of its own. Every number in a caption is listed in `sources` with the
// exact text of the evidence file it comes from; tests/tour.test.ts checks each one is there.

/** The tour's fixed date: the judge walkthrough's W5 date and a Gate P date for Site 001. */
export const TOUR_DATE_UTC = '2027-08-01T00:00:00Z';

export const SITE_001 = 'reference-lola-site-001';
export const SITE_004 = 'reference-lola-site-004';
export const MALAPERT = 'reference-malapert-massif';

/** What the app does when a step opens (App.tsx runs it). */
export type TourAction =
  | { kind: 'date' }
  | { kind: 'site'; siteId: string; details?: boolean }
  | { kind: 'compare'; siteIds: string[] }
  | { kind: 'evidence' }
  | { kind: 'forecast' };

/** A number in a caption and where it is written down. `file` is relative to the repo root. */
export type Source = { file: string; quote: string };

export type TourStep = {
  id: string;
  title: string;
  body: string;
  /** CSS selector of the element to light up; the caption still shows while it loads. */
  target: string;
  action: TourAction;
  sources?: Source[];
  link?: { href: string; label: string };
};

export type Chapter = { id: 'plan' | 'pole'; title: string; steps: TourStep[] };

const GATE_P = 'validation/evidence/power_check_2026-11-13.md';

export const CHAPTERS: Chapter[] = [
  {
    id: 'plan',
    title: 'Plan a landing',
    steps: [
      {
        id: 'date', title: 'Pick a date',
        body: 'Everything answers for the date in this bar. The tour sets a fixed date so every step has something to show; you can type any date, or press Now.',
        target: '.la-datebar', action: { kind: 'date' },
      },
      {
        id: 'site', title: 'Open Site 001',
        body: 'A site near the south pole, from published sources. The card says first whether you can land on that date, and if not, when the next landing window opens. The answer uses the real terrain horizon.',
        target: '.la-card .sc-verdict', action: { kind: 'site', siteId: SITE_001 },
      },
      {
        id: 'best', title: 'Best date',
        body: 'Looks ahead and gives three answers: the soonest window, the one with the most sunlight after touchdown, and the one with the most Earth in view. They trade off, so there is no single magic date.',
        target: '.la-card .sc-best', action: { kind: 'site', siteId: SITE_001 },
      },
      {
        id: 'ellipse', title: 'The landing ellipse',
        body: 'A lander comes down somewhere inside an ellipse, not on the dot. This runs the whole ellipse and can colour it by slope. Our slope matched NASA\'s published slope map at Sites 001 and 004 (Gate S). It takes a few minutes, so the tour only shows where it is.',
        target: '[data-tour="ellipse"]', action: { kind: 'site', siteId: SITE_001, details: true },
        sources: [{ file: 'validation/evidence/slope_check_2026-11-08.md', quote: 'Gate S: computed slope vs PGDA published slope — PASS' }],
      },
      {
        id: 'compare', title: 'Compare',
        body: 'Places side by side on one date: Sun and Earth now, time to sunset and Earthset, sunlight on a panel, longest darkness. "Best" marks the leader in each row; there is no combined score. Site 004\'s published point sits in a small pit, which the 5 m terrain shows.',
        target: '.la-sheet.compare', action: { kind: 'compare', siteIds: [SITE_001, SITE_004] },
        sources: [{ file: 'validation/evidence/resolution_site001_2026-11-06.md', quote: "Site 004's pit rim" }],
      },
      {
        id: 'evidence', title: 'The evidence',
        body: 'Every check we ran, the failures included: shadows against LRO photos, positions against NASA JPL Horizons, real landings, Goddard\'s sunlight maps, slope and sunlight on a panel. The gates had their pass rules written down before the run.',
        target: '.la-sheet[aria-label="Evidence"]', action: { kind: 'evidence' },
      },
    ],
  },
  {
    id: 'pole',
    title: 'Why the pole is hard',
    steps: [
      {
        id: 'skim', title: 'The Sun skims the horizon',
        body: 'At the south pole the Sun stays within about 1.5° of level, so a bump 0.3 m high, 10 m away, is taller in the sky than the Sun can climb. This is a month of sunlight and shadow on the polar cap, from our shadow model.',
        target: '.la-drawer', action: { kind: 'forecast' },
        sources: [{ file: 'validation/evidence/wac_illumination_2026-11-01.md', quote: 'With the Sun within ~1.5° of the horizon, a 0.3 m bump 10 m away subtends 1.7°' }],
      },
      {
        id: 'sunrise', title: 'No air, slow sunrise',
        body: 'The Moon has no air: no twilight, no haze, so the horizon is the terrain itself. A lunar day lasts about 29.5 Earth days (NASA). At Site 001 the first sunrise took 15.8 to 37.7 h to clear the whole Sun in our 2027 runs; on Earth it takes minutes. In Jan 2027 the Sun set again with only 0.11% of its disc ever up.',
        target: '[data-tour="power"]', action: { kind: 'site', siteId: SITE_001 },
        sources: [
          { file: GATE_P, quote: 'the first sunrise takes 15.8 h (Oct) to 37.7 h (Aug)' },
          { file: GATE_P, quote: 'with only 0.11% of the disc ever up' },
        ],
        link: { href: 'https://svs.gsfc.nasa.gov/12739/', label: 'NASA: what is a lunar day? ↗' },
      },
      {
        id: 'panels', title: 'Panels stand up',
        body: 'With the Sun this low, a flat panel gets 0.9–2.8% of the sunlight a vertical panel facing the Sun gets (Gate P, Site 001). That is why polar landers mount panels upright. The numbers are sunlight on a panel, before panel efficiency.',
        target: '[data-tour="power"]', action: { kind: 'site', siteId: SITE_001 },
        sources: [{ file: GATE_P, quote: 'A flat panel gets 0.9–2.8% of what a vertical Sun-facing panel gets' }],
      },
      {
        id: 'earth', title: 'Earth bobs on the horizon',
        body: 'Earth does not cross the sky; it hangs over the near-side horizon and wobbles (libration). At Site 001 it moved between −7.5° and +6.2° from level in our Gate B run, so it is in view only part of each month. In view means line of sight, not a radio link.',
        target: '.la-card .sc-now', action: { kind: 'site', siteId: SITE_001 },
        sources: [{ file: 'validation/evidence/gate_b_geometry_2026-10-28.md', quote: '−7.54° to +6.15°' }],
      },
      {
        id: 'metres', title: 'A few kilometres change everything',
        body: 'Malapert is known for its view of Earth, but its published point is on the far flank: Earth 0%. The crest 10.7 km east sees Earth 70% (Nov 2026, 240 m terrain). Tap "Try" on the card to check it yourself.',
        target: '.la-card .sc-note', action: { kind: 'site', siteId: MALAPERT },
        sources: [
          { file: 'validation/evidence/malapert_earth_2026-11-06.md', quote: 'Published point is on the massif\'s far side from Earth (0% Earth). The DEM crest 10.7 km east' },
          { file: 'validation/evidence/malapert_earth_2026-11-06.md', quote: 'sees Earth 70%' },
        ],
      },
    ],
  },
];

/** Shown-once flag. Storage can throw (private mode, blocked cookies): then the tour just shows again. */
const SEEN_KEY = 'luna-atlas.tour.v1';
export function tourSeen(): boolean {
  try { return window.localStorage.getItem(SEEN_KEY) === '1'; } catch { return false; }
}
export function markTourSeen(): void {
  try { window.localStorage.setItem(SEEN_KEY, '1'); } catch { /* storage blocked: nothing to remember */ }
}
