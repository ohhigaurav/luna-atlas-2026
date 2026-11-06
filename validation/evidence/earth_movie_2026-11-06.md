# Forecast Earth layer: bake and check vs production, 2026-11-06

The team ran `tools/bake_earth_movie.py` and then `tools/check_earth_movie.py` at `77c84cf`. The
check's criteria were fixed in the tool before its first run (this one).

**Bake:** 120 Earth frames, every 6 h from 2027-01-01 00:00 to 01-30 18:00 UTC, on the Sun
movie's grid (320² at 250 m, ±40 km). It took about 70 min.

## Check: PASS

| | n | agreement | limit |
|---|---|---|---|
| all pixel-frames (12 pixels × 120 frames) | 1,440 | 99.86% | ≥ 95% |
| clear cases (production margin ≥ 0.5°) | 1,378 | 100.00% | ≥ 99% |

- Ten pixels agree on 120/120 frames; two agree on 119/120. Both misses were near-horizon frames,
  since every clear case agrees.
- Pixels: seed 20261106, 6 where Earth rises and sets during the month, 6 at random. The
  production side is the app's own analysis run at each pixel as a custom point (same 240 m DEM,
  2 m antenna).
- So the map and the side panel give the same answer for the same place and time.

## What the layer shows (Jan 2027, descriptive; no criterion)

- **Earth is above the terrain somewhere in the square only from 2027-01-09 18:00 to 01-24 12:00
  UTC** (60 of 120 frames). For the rest of the month, no pixel sees Earth. Earth's height at the
  pole follows the ±6.7° libration in latitude, so in this month it sits below the south-polar
  horizon for about half the time.
- **Coverage:** no pixel sees Earth for more than 49% of the month. 41% of the area never sees it
  this month.
- **Sun and Earth together** (Sun frames taken at the Earth frame times): at best 49.2% of the
  month; 59.6% of the area never has both.
- **Correction 2026-11-06:** the next line is the 240 m pixel. Site 001 with its 5 m tile gets Sun 69% and Earth 36% from 10 Jan (`resolution_site001_2026-11-06.md`).
- **Site 001 / brightest-Sun pixel** (89.45°S, 223.2°E): Sun 100% of the Earth frame times,
  Earth 46.7%. Earth is visible from 01-10 00:00 to 01-23 18:00 without a break.
- **Agrees with the custom-point landing run** for the same point (`sky_orientation_2026-11-06.md`):
  - best touchdown 01-09 21:00 with Earth required at landing, which falls between the movie's
    18:00 (no Earth) and 00:00 (Earth) frames;
  - Earth in view 100% of the 10-day mission to 01-19 21:00.

## Allowed claims

- "The forecast's Earth layer agrees with the app's own analysis at 99.86% of tested
  pixel-times, and at 100% of clear cases. The criteria were fixed before the run."
- "In January 2027 no spot within 40 km of the pole sees Earth for more than half the month."
  This is about the model, for this month, at 240 m terrain and a 2 m antenna.

## Limits

- 240 m terrain; terrain beyond 150 km is ignored.
- Earth's centre only, not its disc.
- Line of sight is not a radio link budget.
- Frames every 6 h: within a 6 h step the rise or set time is unresolved.
