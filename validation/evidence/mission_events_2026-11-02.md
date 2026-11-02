# Gate D: model vs real missions, 2026-11-02

Run by the team with `tools/check_mission_events.py` at `642c0cf`; pass rules fixed in the tool's
docstring at `c11b91b`, before the first run. Report `data/derived/mission_events_20261102T142544Z.json`
(on that machine). Observer 2 m, 30 min step, 10 s event precision, production `run_analysis`.

**Result: 6 of 7 PASS, 1 FAIL.**

| case | reference | model | verdict |
|---|---|---|---|
| D1 Blue Ghost 1 sunset (flat) | ~2025-03-16 18:30 UTC (landing + 346 h of daylight; last contact 23:25 UTC, ~5 h after sunset) | 2025-03-16 20:55 UTC (+2.41 h); Sun 3.43° up at landing | **FAIL** (limit ±2 h) |
| D2 SLIM sunset (flat) | 31 Jan to 1 Feb 2024 (JAXA, press) | 2024-01-31 09:34 UTC; Sun 37.2° up at landing | PASS |
| D3 Chandrayaan-3 (terrain) | sunset ~4–6 Sep, next sunrise ~22 Sep 2023 ("from 20 Sep onwards", ISRO) | sunset 2023-09-04 07:31 UTC, sunrise 2023-09-19 22:49 UTC | PASS |
| D4 Apollo 11 at landing | ALSJ: Sun 10.65°/88.81°, Earth 59.43°/272.16° | Sun 10.70°/88.81°, Earth 59.22°/272.20° | PASS (max 0.21°) |
| D4 Apollo 14 at landing | Sun 10.36°/89.54°, Earth 66.10°/96.70° | Sun 10.35°/89.56°, Earth 65.95°/96.87° | PASS (max 0.17°) |
| D4 Apollo 15 at landing | Sun 12.05°/95.73°, Earth 69.28°/203.00° | Sun 12.02°/95.72°, Earth 69.18°/202.92° | PASS (max 0.10°) |
| D5 Chang'e-4, January 2019 | Far side: needed the Queqiao relay | Earth never above −37.2° | PASS |

Not scored: Chandrayaan-3 with a flat horizon gives sunset 2023-09-04 18:05 and sunrise 2023-09-19
17:23 UTC. Terrain moves that sunset 10.6 h earlier.

## What this shows

* **Dates and positions agree with real missions.** Sun and Earth positions at three Apollo
  landings agree within 0.21° (Sun within 0.05°) with NASA's Apollo Lunar Surface Journal. The
  SLIM sunset and the Chandrayaan-3 sunset and sunrise fall on the dates the agencies reported.
  The far side never sees Earth. Gate B (JPL Horizons, 0.04 arcsec) already covered the
  geometry; this adds independent real-world events.
* **D1 fails because of the horizon, not the Sun.** The Sun moves about 0.51° per hour across
  the lunar sky, so a 2.4 h late sunset means the real western horizon at Blue Ghost stands
  about 1.2° above the flat horizon we model north of 60° S (no DEM there, decision D-22). The
  sign is the expected one: a flat model can only make sunset later than reality. This is a
  hypothesis until a terrain model of that horizon is checked.
* **The pattern across all tests:** every failure so far (the WAC many-point test, D1) is about
  terrain and horizons. None is about where the Sun or Earth is, or when.

## Next

1. D-22: get terrain north of 60° S (SLDEM2015 or a global LOLA product). Then predict Blue
   Ghost's western horizon and rerun D1 with the same rule. Write the prediction down before
   the run.
2. Until then, the app must label every non-polar result "flat horizon: real sunset/sunrise can
   differ by hours". `/api/check` already adds this caveat.
