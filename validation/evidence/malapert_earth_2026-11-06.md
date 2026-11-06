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

**Next:** `tools/find_summit.py` reads the DEM's highest point within 15 km and compares it with
the published point. Until it has run:
- the reference point stays exactly as published (we never edit a citation);
- the app must not present 0% Earth at "Malapert" without the reason. Suggested note: "This
  published point sits on the massif's far side from Earth; the crest, about N km away, sees Earth
  most of the time."
