# Malapert: the published point sees no Earth, the higher ground nearby does (2026-11-06)

**Found by:** the event-day rehearsal (an internal document (not published)). The Malapert Massif reference point
(85.99°S, 357.07°E, from NASA's image page https://science.nasa.gov/image-detail/20100618/) had
**Earth 0% and no landing window** in the 90 days from 6 Nov 2026.

**Why it matters:** Malapert is known for Earth visibility. NASA's page says it has "exceptional
Earth visibility", and its summit has been proposed for a radio station. A judge who knows that
would read 0% as a bug.

**Diagnostic** (`tools/try_compare.py`, 2026-11-06 + 30 d, 240 m terrain, 2 m antenna; raw:
`malapert_points_2026-11-06.log`):

| point | ground | Earth horizon now | Earth 30 d | Sun 30 d |
|---|---|---|---|---|
| 85.99°S, 357.07°E (published) | 4,841 m | **+13.49°** | **0%** | 58% |
| 85.99°S, 2.93°E (mirrored longitude) | **5,122 m** | −1.86° | 76% | 55% |
| 86.00°S, 0.00°E | 4,797 m | +6.61° | 32% | 65% |
| 85.90°S, 2.90°E | 4,688 m | −3.17° | 100% | 44% |

**Reading it:**
- The calculation behaves physically. Earth is up wherever the terrain toward Earth (local north,
  the near side) is low, and blocked where it is high.
- The published point has terrain 13.5° high toward Earth: the massif's crest stands between it
  and Earth. It is on the hidden flank, which Wikipedia's Malapert article describes as the
  ridge's "radio shadow".
- The highest of the four points is at the **mirrored** longitude (2.93°E, 280 m higher). That
  hints the page's 357.07°E may be a sign slip for 2.93°E, but four points cannot establish that.

## Summit from the DEM (`tools/find_summit.py`; raw: `malapert_summit_2026-11-06.log`)

The highest points of the 240 m regional DEM within 15 km of the published point, at least 1 km
apart:

| point | height | from published 357.07°E | from mirrored 2.93°E |
|---|---|---|---|
| 85.9886°S, 2.1013°E | **5,168.8 m** | 10.67 km | 1.76 km |
| 85.9945°S, 2.7840°E | 5,141.2 m | 12.11 km | **0.34 km** |
| 85.9640°S, 2.4257°E | 5,117.5 m | 11.42 km | 1.33 km |
| 86.0252°S, 3.0340°E | 5,103.5 m | 12.63 km | 1.09 km |
| 85.9738°S, 1.6430°E | 5,098.7 m | 9.73 km | 2.78 km |

Compare, 6 Nov 2026 + 30 d:
- **Published point** (4,841 m): Sun 58%, **Earth 0%**, both 0%. The terrain toward Earth stands
  at +13.49°.
- **DEM summit** (5,169 m): Sun 84%, **Earth 70%**, both 67%. The terrain toward Earth sits at
  −1.17°.

**Conclusions, with their strength:**
1. **Established:** the published coordinate lies about 10.7 km west of the massif crest, on its
   Earth-hidden side. That is why it gets 0% Earth. The model is behaving correctly.
2. **Strongly suggested, not established:** NASA's page coordinate may carry a longitude sign slip.
   - Its latitude (85.99°S) matches the crest line exactly.
   - All five high spots lie at 1.6–3.0°E.
   - The mirrored longitude (2.93°E) is 0.34 km from the second-highest spot and 1.76 km from the
     highest.
   - The published longitude is about 10 km from all of them.

   This does not prove a slip: the page may intentionally show a point on the massif's flank. We do
   not edit the citation.
3. **Earth at the summit is 70% this month, not "constant"** (240 m terrain, 2 m antenna, one month).
   Literature claims of constant Earth visibility at the summit are not reproduced here and not
   contradicted beyond this month. Earth's height at about 86°S on the near side swings by roughly
   ±6.7° around about +4°, so a horizon at −1.2° loses Earth for part of the month.

## What the app shows

A note on the Malapert reference point, from `data/reference/site_notes.json` through
`/api/site-index` (`analysis_note`). The citation itself is untouched:
"Published point is on the massif's far side from Earth (0% Earth). The DEM crest 10.7 km east
(85.989°S, 2.101°E, 5,169 m) sees Earth 70% and Sun 84% in Nov 2026. Try it as a clicked point."

## Landing windows, 2027-01-01 + 90 d (`tools/try_landing.py`; raw: `r5_check_2026-11-06.log`)

- **Published point:** no window. All 4,321 candidates fail "Earth up at touchdown".
- **DEM crest (85.9886°S, 2.1013°E):** 3 windows.
  - First: touchdown 01-09 04:00 – 01-21 21:00 UTC, giving 22.7 days of sunlight, with Earth in
    view for 100% of the mission.
  - The Sun at best touchdown reads **−2.9°** from the level horizontal. From a 5.2 km summit the
    real horizon dips lower, so the Sun shines while "below the horizontal".
  - Answers now also give `sun_above_horizon_at_best_deg` (Sun height above the local horizon)
    so this reads correctly.
