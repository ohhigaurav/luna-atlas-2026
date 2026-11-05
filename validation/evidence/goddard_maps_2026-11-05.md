# Gate E: NASA Goddard south-pole maps (PGDA 69), 2026-11-05

The team ran `tools/compare_goddard_maps.py` at `8dd1cdd`. The point draw and the pass rules were
fixed in the tool's docstring in that same commit, before any run. This was the first run, and
no rule or setting was changed afterwards. Raw console output:
`goddard_comparison_2026-11-05.log`. The per-point JSON stays on a development machine as
`data/derived/goddard_comparison_20261105T132707Z.json`.

**References:**
- Maps: `AVGVISIB_85S_060M_201608.TIF` (Sun), `AVGVISIB_85S_060M_201608_EARTH.TIF` (Earth), `LPSR_85S_060M_201608.TIF` (permanent shadow). NASA Goddard PGDA product 69 (Mazarico et al. 2011), 85–90°S, 60 m/px.
- Scaling from the PDS labels: visibility = DN × 0.00004; PSR = DN × 0.000025 + 0.5.

**Our side:**
- The production terrain horizon (240 m regional LOLA DEM).
- An hourly Sun/Earth track from `/api/sky-geometry`: 163,067 samples, 18.6 years from 2009-07-13.
- The visible disc fraction per hour, averaged over the whole track.

## Result: PASS (verdict at 0 m, all three parts required)

|            | n  | median (ours − map) | mean   | within 0.10 | Spearman | verdict |
|------------|----|---------------------|--------|-------------|----------|---------|
| Sun, 0 m   | 48 | −0.016              | −0.013 | 100%        | 0.99     | PASS    |
| Earth, 0 m | 48 | −0.045              | −0.036 | 92%         | 0.99     | PASS    |
| PSR, 0 m   | 48 | agreement 94%       |        |             |          | PASS    |
| Sun, 2 m   | 48 | −0.009              | −0.005 | 100%        | 0.99     | (reported) |
| Earth, 2 m | 48 | −0.043              | −0.027 | 96%         | 0.99     | (reported) |
| PSR, 2 m   | 48 | agreement 94%       |        |             |          | (reported) |

Thresholds: |median| ≤ 0.05, ≥ 70% within 0.10 and Spearman ≥ 0.80 for Sun and Earth; ≥ 90% PSR
agreement.

**What it shows:** our Sun-visibility and Earth-visibility numbers agree with NASA Goddard's
independent product over 18.6 years. Before this run, only our sunlight and our Sun/Earth
directions had been validated (JPL Horizons, real missions, LRO photos). This is the first
external check of the "Earth in view" figures.

## Read with care

1. **48 points, not 60.** The ≥ 0.6 Sun stratum was empty. No pixel within 60 km of the pole
   with a 3×3 spread ≤ 0.10 reaches 0.6. The map's maximum, 0.884, sits on peaks and ridges, and
   the smoothness filter excludes those. The rules set no minimum n, so the verdict stands.
   - **This gate says nothing about the best-lit ridges (> 0.6).**
   - Those ridges are exactly where the many-point WAC test found us 16.7 points low.
   - The sharp-feature limit of a 240 m DEM is still open there.
2. **Earth passes narrowly on the median: −0.045 against a 0.05 limit.**
   - The gap is systematic, not scatter. Ours is lower at 33 of the 36 points where the map
     shows Earth at all. Taking only points with map Earth > 0.3, ours is about 9% lower
     (median ratio 0.91, median gap −0.046).
   - Raising the observer to 2 m barely changes it (−0.043).
   - Cause not established. Candidates:
     - the averaging span (the label does not state theirs; ours starts 2009-07-13);
     - our straight-horizon disc fraction;
     - horizons a fraction of a degree higher on the 240 m DEM. Earth stays within about 7° of
       the horizon at the pole, so small horizon changes matter.
   - Do not quote Earth visibility to better than about ±0.05 (absolute).
3. **The Sun is also slightly low** (40 of 48 points; median ratio 0.94 where map > 0.2). At 2 m
   the gap halves (−0.009). That fits a small horizon or height difference, but this is not
   tested.
4. **Four Earth points are off by more than 0.10:**
   - #31: map 0.185, ours 0.001
   - #7: 0.178 vs 0.067
   - #12: 0.168 vs 0.062
   - #40: 0.509 vs 0.404

   The smoothness filter was applied to the Sun map only. At these points Earth sits near the
   local horizon, where a 240 m DEM can hide or reveal it entirely.
5. **PSR 94%:** 3 of 48 points disagree. Which ones is in the per-point JSON on a development machine,
   not here.

## Allowed claims

- "Our average sunlight and Earth-visibility agree with NASA Goddard's published south-pole maps
  (PGDA 69): 48 points, Spearman 0.99 for both, Sun median gap −0.016, Earth −0.045. The test
  rules were fixed before the run."
- "Permanent-shadow call agrees with NASA's map at 94% of test points."

## Not allowed

- "Matches NASA exactly".
- Any claim about the brightest ridges (> 0.6 average Sun).
- Earth visibility quoted more precisely than ±0.05.
