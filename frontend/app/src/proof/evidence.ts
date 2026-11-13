// Every figure on the proof screen, copied from the committed evidence files (touchdown times from
// tools/check_mission_events.py) (PRD F21/F22: "each
// chip quotes the evidence file"). If a file changes, change it here; nothing is computed.

export type ShadowFrame = {
  frame: string;            // WAC movie frame id; the picture is /proof/{frame}_compare.png
  utc: string;
  sunTowardDegE: number;
  sunHeightDeg: number;     // at the pole
  agreementPct: number;
  shadowIoU: number;
  pass: boolean;
};

export const SHADOW_MATCH = {
  file: 'validation/evidence/shadow_match_2026-11-04.md',
  verdict: '5 of 6 frames pass',
  rule: 'A frame passes at ≥ 85% agreement and shadow IoU ≥ 0.70; the test passes if ≥ 2/3 of frames pass. Fixed before the first run.',
  setup: 'LRO WAC polar movie, Sept–Oct 2009 · 15 km disc around the south pole · observer at ground level · 240 m LOLA DEM · 200 m band at modelled shadow edges not scored',
  caveat: 'At a 1.4° Sun most of the disc is in shadow, so high agreement is partly easy. Quote the verdict and the table, not "99% accurate".',
  frames: [
    { frame: 'WAC_MOVIE_S20090920T0850', utc: '2009-09-20 08:50', sunTowardDegE: 164.7, sunHeightDeg: 1.33, agreementPct: 99.1, shadowIoU: 0.99, pass: true },
    { frame: 'WAC_MOVIE_S20090924T0707', utc: '2009-09-24 07:07', sunTowardDegE: 116.7, sunHeightDeg: 1.39, agreementPct: 94.0, shadowIoU: 0.94, pass: true },
    { frame: 'WAC_MOVIE_S20090928T0001', utc: '2009-09-28 00:01', sunTowardDegE: 71.5, sunHeightDeg: 1.45, agreementPct: 95.7, shadowIoU: 0.95, pass: true },
    { frame: 'WAC_MOVIE_S20091002T0015', utc: '2009-10-02 00:15', sunTowardDegE: 22.7, sunHeightDeg: 1.49, agreementPct: 82.7, shadowIoU: 0.74, pass: false },
    { frame: 'WAC_MOVIE_S20091010T0042', utc: '2009-10-10 00:42', sunTowardDegE: 285.1, sunHeightDeg: 1.51, agreementPct: 93.7, shadowIoU: 0.92, pass: true },
    { frame: 'WAC_MOVIE_S20091015T0124', utc: '2009-10-15 01:24', sunTowardDegE: 223.8, sunHeightDeg: 1.51, agreementPct: 99.7, shadowIoU: 1.0, pass: true },
  ] as ShadowFrame[],
};

export type MissionCase = {
  id: string; title: string; siteId: string | null; whenUtc: string | null;
  reference: string; model: string; pass: boolean; note?: string;
};

export const MISSION_EVENTS = {
  file: 'validation/evidence/mission_events_2026-11-02.md',
  verdict: '6 of 7 pass',
  cases: [
    { id: 'D4a', title: 'Apollo 11 at landing', siteId: 'reference-apollo-11', whenUtc: '1969-07-20T20:17:39Z',
      reference: 'ALSJ: Sun 10.65° / 88.81°, Earth 59.43° / 272.16°', model: 'Sun 10.70° / 88.81°, Earth 59.22° / 272.20°', pass: true },
    { id: 'D4b', title: 'Apollo 14 at landing', siteId: 'reference-apollo-14', whenUtc: '1971-02-05T09:18:13Z',
      reference: 'Sun 10.36° / 89.54°, Earth 66.10° / 96.70°', model: 'Sun 10.35° / 89.56°, Earth 65.95° / 96.87°', pass: true },
    { id: 'D4c', title: 'Apollo 15 at landing', siteId: 'reference-apollo-15', whenUtc: '1971-07-30T22:16:29Z',
      reference: 'Sun 12.05° / 95.73°, Earth 69.28° / 203.00°', model: 'Sun 12.02° / 95.72°, Earth 69.18° / 202.92°', pass: true },
    { id: 'D2', title: 'SLIM went dark', siteId: 'reference-intl-slim', whenUtc: '2024-01-31T09:34:00Z',
      reference: 'Sunset 31 Jan – 1 Feb 2024 (JAXA)', model: 'Sunset 2024-01-31 09:34 UTC (flat horizon)', pass: true },
    { id: 'D3', title: 'Chandrayaan-3 night', siteId: 'reference-intl-chandrayaan-3', whenUtc: '2023-09-04T07:31:00Z',
      reference: 'Sunset ~4–6 Sep, sunrise ~22 Sep 2023 (ISRO)', model: 'Sunset 4 Sep 07:31, sunrise 19 Sep 22:49 UTC (terrain)', pass: true },
    { id: 'D5', title: "Chang'e 4 needs a relay", siteId: 'reference-intl-change-4', whenUtc: '2019-01-03T02:26:00Z',
      reference: 'Far side: Queqiao relay needed (Jan 2019)', model: 'Earth never above −37.2°', pass: true },
    { id: 'D1', title: 'Blue Ghost 1 sunset', siteId: 'reference-clps-blue-ghost-1', whenUtc: '2025-03-16T20:55:00Z',
      reference: '~2025-03-16 18:30 UTC', model: '20:55 UTC (+2.4 h, flat horizon)', pass: false,
      note: 'Fails on the horizon, not the Sun: a flat model can only make sunset late. No terrain north of 60° S yet.' },
  ] as MissionCase[],
};

export const HORIZONS = {
  file: 'validation/evidence/gate_b_geometry_2026-10-28.md',
  verdict: 'Pass',
  headline: 'Sun and Earth positions vs JPL Horizons: worst 0.04″ elevation, 0.02″ azimuth, 0.011 km range',
  tolerance: 'Tolerance 1″ / 1″ / 1 km, committed before the run · 20 comparisons, 8 near the horizon',
};

export const GODDARD = {
  file: 'validation/evidence/goddard_maps_2026-11-05.md',
  verdict: 'Pass',
  headline: 'Average sunlight and Earth in view vs NASA Goddard south-pole maps (PGDA 69), 18.6 years hourly',
  rule: 'Sun and Earth each: median gap ≤ 0.05, ≥ 70% of points within 0.10, Spearman ≥ 0.80; permanent shadow ≥ 90% agreement. Fixed before the first run.',
  rows: [
    { what: 'Sun visibility', n: 48, medianGap: -0.016, within: '100%', spearman: 0.99, pass: true },
    { what: 'Earth visibility', n: 48, medianGap: -0.045, within: '92%', spearman: 0.99, pass: true },
  ],
  psrAgreementPct: 94,
  caveat: 'Earth reads about 9% low (cause open), so it passes narrowly; brightest ridges (> 0.6) not tested. Their DEM 60 m, ours 240 m.',
};

/** Further checks, each quoted from its evidence file (passes and the open problems alike). */
export const MORE_CHECKS: Array<{ name: string; verdict: 'PASS' | 'FAIL' | 'OPEN'; text: string; file: string }> = [
  { name: 'Slope (Gate S)', verdict: 'PASS', file: 'validation/evidence/slope_check_2026-11-08.md',
    text: "Our slope of the 5 m terrain matches NASA's published slope maps (PGDA) at Sites 001 and 004: 95% of pixels within 0.70° / 0.92° (limit 1.5°), median difference under 0.01°. Rule fixed the day before the run." },
  { name: 'Sunlight on a panel (Gate P)', verdict: 'PASS', file: 'validation/evidence/power_check_2026-11-13.md',
    text: "Sunlight reaching a panel (before panel efficiency) agrees with the Goddard-checked Sun visibility and stays inside physical limits at Sites 001 and 004, 3 × 30 days. A consistency check, not an independent validation. At Site 001 the first sunrise takes 15.8–37.7 h to clear the whole Sun; a flat panel gets under 3% of a vertical one." },
  { name: 'Average sunlight and Earth (Gate E)', verdict: 'PASS', file: 'validation/evidence/goddard_maps_2026-11-05.md',
    text: "vs NASA Goddard's south-pole maps over 18.6 years: Sun median gap −0.016, Earth −0.045 (Earth reads a little low, cause open), permanent shadow 94% agreement. Brightest ridges (> 0.6) not tested." },
  { name: 'Observed illumination (LROC WAC)', verdict: 'OPEN', file: 'validation/evidence/wac_illumination_2026-11-01.md',
    text: "Agrees with LROC's observed illumination at 100 m pixels (median −0.6 points), except on the brightest ridges, where the model is about 17 points too dark. Open; candidate causes are listed in the file. An earlier run failed because of a bug; both runs stay on record." },
  { name: 'Forecast Earth layer', verdict: 'PASS', file: 'validation/evidence/earth_movie_2026-11-06.md',
    text: "The Earth layer matches the app's own analysis at the same 240 m terrain on 99.86% of 1,440 tested pixel-times. A consistency check, not a check against 5 m site answers." },
  { name: 'Sky orientation (stars, Earth’s face)', verdict: 'FAIL', file: 'validation/evidence/sky_orientation_2026-11-06.md',
    text: 'Failed as pre-registered on one part (Moon pole direction): the limit assumed the pole wobble was under 1°, but its 18.6-year term is 3.9°. Earth sub-point vs JPL Horizons passed at all 13 dates. Recorded as a FAIL; the post-hoc check is not a gate.' },
];
