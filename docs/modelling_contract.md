# Modelling contract (transcribed from PRD v0.1)

This file is a reviewable contract, not evidence that any calculation has been implemented or validated.

## Time and frames

- Public inputs/outputs use UTC ISO 8601.
- UTC is converted to SPICE ephemeris time (TDB seconds past J2000) through a pinned leap-seconds kernel. UTC seconds are never treated as ET.
- The declared body-fixed frame is `MOON_ME`, using the DE421-associated lunar orientation because the planned PGDA terrain products reference it. Any other ephemeris/frame chain must be documented and validated.
- Azimuth is clockwise from local north; elevation is measured above the local tangent plane. Aberration correction is explicit.
- Observer radius is `r_obs = R + z0 + h`, where `R` is the reference radius, `z0` is DEM ground height relative to that radius, and `h` is height above local terrain. The observer/DEM vertical-datum contract remains an open question.

## Terrain horizon

For each azimuth bin `a`, compute the maximum apparent elevation over terrain samples along the ray:

`H(a) = max_d atan2(((R + z(d)) cos(theta) - r_obs), ((R + z(d)) sin(theta)))`, with `theta = d/R`.

For a flat spherical surface, the analytic reference is:

`H_flat = -acos(R / (R + h))`.

NoData before a controlling sample marks the azimuth bin incomplete. It must not be silently replaced by zero or an artificial wall. Horizon interpolation wraps across 0°/360° and must remain continuous for event refinement.

## Visibility margins

Sun upper-limb margin:

`g_sun(t) = e_s(t) + rho_s(t) - H(a_s(t))`, where `rho_s = asin(R_sun / r_sun)`.

Earth-centre-clear margin:

`g_dte(t) = e_e(t) - H(a_e(t)) - m`, where `m >= 0` is the declared minimum clearance angle.

A positive margin means geometrically visible under that definition. Earth-centre-clear must not be called "communications available". A possible Earth-disc-visible flag is a separate P1 metric.

The PRD's worked solar check is authoritative: `e_s = -1.0°`, `H = 0.3°`, and `rho_s = 0.266°` gives `g_sun = -1.034°` (not visible).

## Events and metrics

- Sample continuous margins on a coarse grid, bracket sign changes, and refine roots with Brent's method to the declared tolerance. Re-evaluate and report the residual at each root.
- Near-zero minima without sign changes trigger local subdivision for grazing/tangency detection.
- Windows touching the requested interval boundary are flagged as truncated; their durations are reported as lower bounds (`>=`). Numerical tolerance and physical/model uncertainty are distinct.
- All duration metrics are computed from refined windows, not coarse samples.
- The requested interval length `T` is the denominator for sunlight, DTE-clear, both-visible, and joint-outage fractions.
- The landing finder computes windows once over the search span plus mission duration; each candidate start clips the windows to its mission interval. Any outage already in progress at landing counts from landing time.
- Site A dominates B only if it is no worse on every selected metric and strictly better on at least one. No composite score without visible weights and sensitivity analysis.

## Required acceptance references

- Synthetic flat-sphere horizon error: `< 1e-6 rad` versus analytic dip.
- Event time tolerance: still an explicit decision; the PRD proposes 1 second but requires evidence and a decision record.
- Geometry tolerance against saved Horizons values: D-10 remains open and must be declared before comparisons run.
