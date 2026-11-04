# Bug: at observer height 0 m the horizon could become a +90° wall (found and fixed 2026-11-04)

## How it was found

The pre-registered gate of `tools/shadow_match.py` compares a new ray march with the production
horizon code at four points before any LRO photo is scored. At Site 004 (observer 0 m) the
production horizon gave a Sun margin of −88.23°, i.e. a horizon about 90° high. The gate stopped the
run; nothing was scored.

## Cause

`build_horizon_from_dem_assets` samples each ray from distance 0. Apparent elevation is
`atan2(r_terrain·cos θ − r_observer, r_terrain·sin θ)`. At d = 0 this is `atan2(h_ground(ray) − h_ground(observer), 0)`.
With the observer above the ground it is −90° and harmless. At observer height 0 the numerator is the
difference between two bilinear samples of the same point, through slightly different
latitude/longitude arithmetic (the forward geodesic's `arcsin` near the pole), which can differ by
about 1e-9 m. The result was:

* +90° (numerator > 0): every azimuth is "blocked", so the point is never lit;
* 0° (numerator = 0): a 0° floor on the horizon, too high on peaks and slopes;
* −90°: no effect.

Reproduced in `tests/test_horizon_origin_sample.py`: 1e-9 m at the origin gives a 90.0° horizon with
the old formula.

## Fix

The distance-0 sample still proves that coverage starts at the observer, but it is never a horizon
candidate (`terrain.horizon_bins_from_samples`; same in `horizon.calculate_terrain_horizon`).
For observers above the ground the result is bit-for-bit unchanged (test). Horizon algorithm
version 2.1 → 2.2, so every cached horizon is rebuilt.

## What it affected

Only runs with the observer at exactly 0 m:

* the WAC single-site rerun at 0 m (Site 001 28.7%, Site 004 0%);
* the many-point WAC test (all points at 0 m), recorded as FAIL with the model too dark, worst on
  bright ground. A 0% or floor-clipped point biases the model low exactly there.
* any `/api/check` or `/api/landing-windows` call with `panel_height_m` = 0.

Not affected (observer 2 m): Gate B, Gate D (6/7), the stand-in site runs, the landing results, the
south-pole light map.

## What happens to the earlier results

They stay recorded as run. The WAC tests are rerun with the fixed code under their **unchanged**
pre-registered criteria, and both results are reported. This rerun is not tuning: the fix came from
an independent gate, and the pass rules do not change.
