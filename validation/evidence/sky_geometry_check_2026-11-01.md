# /api/sky-geometry on real kernels — 2026-11-01

**Result: PASS** on every check. Run by the team with `tools/check_sky_geometry.py` at commit `f048111`.
The limits were fixed in the tool's docstring at `c71176f`, before the first run. Report:
`data/derived/sky_geometry_check_20261101T161717Z.json` (on that machine). Kernel pool: preflighted.
Frame: MOON_ME, LT+S.

## A. Cross-check against the analysis path

A flat analysis at 0 m (run `de9b2e76-9a14-4820-a1a0-29c2f3b97513`) covered 2027-01-01 to 2027-01-04
with 30 min samples (n = 146 per site). Its local azimuth/elevation and range come from SPICE `azlcpo`
at the surface point. The check compares them with values rebuilt from the sky-geometry vectors
(`spkpos` from the Moon's centre minus the site position).

| site | Sun d_el (deg) | Sun d_az·cos el (deg) | Sun d_range (km) | Earth d_el (deg) | Earth d_az·cos el (deg) | Earth d_range (km) |
|---|---|---|---|---|---|---|
| Malapert (85.99 S, 357.07 E) | 2.97e-06 | 3.66e-06 | 9.21 | 2.74e-05 | 3.17e-06 | 0.028 |
| Apollo 11 (0.67 N, 23.47 E) | 4.27e-06 | 2.86e-06 | 9.29 | 8.95e-06 | 4.05e-06 | 0.170 |

Limits: 0.01 deg for angles; range 50 km (Sun) and 1 km (Earth).

* The largest angular difference is 2.7e-5 deg (0.1 arcsec). That is about 360 times smaller than
  the limit, and 1/36,000 of the 1 deg day/night-line requirement for the 3D globe.
* The ~9 km Sun range difference comes from rounding the unit vector to 1e-7. At 1 AU, 1e-7 is
  about 15 km, which is why this limit was set at 50 km.
* Apollo 11, near the equator, tests the longitude sign and the east/north axes away from the pole.
  A west-positive or axis-swap error would show up as degrees, not micro-degrees.
* Gate B (`gate_b_geometry_2026-10-28.md`) already ties `azlcpo` to JPL Horizons within 0.04 arcsec.
  The sky-geometry vectors therefore inherit that agreement, to within the differences above.

## B. Physical limits, 2027 (6 h step, 1457 samples)

| check | value | limit |
|---|---|---|
| max subsolar latitude | 1.552 deg | <= 1.6 |
| max sub-Earth latitude (libration) | 6.844 deg | <= 7.0 |
| max sub-Earth longitude (libration) | 7.768 deg | <= 9.0 |
| Sun distance | 146,705,287 to 152,438,687 km | 1.45e8 to 1.53e8 |
| Earth distance | 357,287 to 406,609 km | 3.50e5 to 4.10e5 |
| mean subsolar longitude rate | -12.1915 deg/day | -12.1907 ± 2 % |
| Earth lit fraction vs (1 - cos Sun–Moon–Earth angle)/2 | max 0.0014 | <= 0.005 |

The subsolar longitude rate is within 0.007 % of one synodic month per 360 deg, and the sign is
negative (the Sun moves west), as expected.

## What this does not show

These are consistency and plausibility checks. Absolute accuracy rests on Gate B. Eclipses are
not modelled by this endpoint.
