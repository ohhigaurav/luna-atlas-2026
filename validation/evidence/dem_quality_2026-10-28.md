# DEM quality at the horizon-controlling terrain: Site 004 and Site 001 (2026-10-28)

Run by the team at commit `0d69858` with `tools/dem_quality.py`, using the PGDA Product 78 count
(LDEC, LOLA spots per pixel) and total-uncertainty (TOTERR, RMS metres) maps:

| File | SHA-256 |
|---|---|
| Site04_final_adj_5mpp_ldec.tif | fcc8c2219ae2368d5b2a1f6aec05fcf96cf725f3035ac8d80efc312a4ff29227 |
| Site04_final_adj_5mpp_toterr.tif | 416c4baa3b64def0182bb3379a1a9228482efd8ce32a39309ea8de5d0330fbe6 |
| Site01_final_adj_5mpp_ldec.tif | 16d6ed21020ad48fa71d94e7437492acf5bf04118f52bcd292f57f22ead4cd23 |
| Site01_final_adj_5mpp_toterr.tif | cf2cf52f52d2aa51e60d058010d10b0ebfb1d3e920f5a2b9a46eb6c51054ab1c |

Downloaded from `https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site0N/`; each file's grid matched
the surface DEM (the tool refuses otherwise).

## Measured fraction and uncertainty around the published points

| Ring | Site 004: pixels with ≥1 LOLA spot | TOTERR median / max | Site 001: pixels with ≥1 spot | TOTERR median / max |
|---|---|---|---|---|
| 0-50 m | 13.1 % | 0.31 / 1.22 m | 12.1 % | 0.29 / 1.01 m |
| 50-100 m | 11.5 % | 0.27 / 1.23 m | 10.1 % | 0.31 / 0.97 m |
| 100-150 m | 12.7 % | 0.26 / 1.20 m | 8.2 % | 0.35 / 1.10 m |
| 150-300 m | 10.5 % | 0.30 / 1.49 m | 8.2 % | 0.36 / 1.00 m |
| at the point | | 0.72 m | | 0.23 m |

Consistent with PGDA's statement that ~90 % of 5 m pixels are interpolated.

## Horizon-controlling points

- Site 004: controlled at 30-105 m in every direction; TOTERR 0.17-1.08 m there;
  atan(TOTERR/distance) 0.13-1.38° (median ~0.35°). Lowest horizon 2.19° (az 60°).
- Site 001: controlled at 20-300 m except az 240-285° (regional DEM, 41-85 km, no uncertainty
  map); TOTERR 0.13-0.50 m; atan(TOTERR/distance) 0.03-0.93°, largest at az 135-210° where the
  controlling point is only 20-30 m away and the horizon is 1.0-1.8°.

## Interpretation (stated with its limits)

1. **The Site 004 depression is far larger than the published height error.** Rim heights of
   +5.7..+8.3 m at ~100 m (diagnostic tool) against TOTERR ~0.3 m (max 1.2 m) in that ring. By
   PGDA's own error model it is real topography, not an artefact of interpolation. (We have
   not independently verified TOTERR.)
2. **Site 004's 0 % is robust to about 1σ height error, not demonstrably more.** Sun upper limb
   reaches at most ~1.44° this month (1.17° + 0.27° semidiameter); the lowest horizon is 2.19°,
   a 0.75° gap. Site and rim errors combined in quadrature, sqrt(0.72² + 0.29²) ≈ 0.78 m at
   100 m, give ≈0.45°. Correlated errors would partly cancel; the 100 PGDA error clones are the
   way to settle it.
3. **Site 001 is sensitive to height error.** Its Sun margins are small (Sun 0.05-1.52°) and
   the angle indicator reaches 0.6-0.9° exactly where the horizon is 1.0-1.8°; its 69.3 %
   sunlit could move substantially within the DEM uncertainty.
4. **Position matters more than height error at both sites.** The location scan
   (`location_scan_2026-10-28.md`) moved Site 004 from 0 % to 96-100 % with a 100 m shift, a
   bigger effect than any TOTERR-scale change computed here.

The indicator atan(TOTERR/distance) is a scale, not a confidence interval: it ignores error
correlation, the observer-point error, and the other azimuths that may also block.
