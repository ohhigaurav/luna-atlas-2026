# PGDA error clone check and observer-height sweep at Site 004 (2026-10-28)

Run by the team at commit `f9fbe60`.

## What a Product 78 "clone" file is

`Site04_final_adj_5mpp_0001_err.tif`, downloaded from
`https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site04/Clones/`: same CRS (sphere 1737400 m, south
polar stereographic), size 3200 x 3200 and transform (5 m, origin -9000, 1000) as
`Site04_final_adj_5mpp_surf.tif`; float32, NoData NaN; values -2847.9 .. 1805.3 m. Despite the
`_err` name it is a complete surface. Pixel-wise against the nominal surface and TOTERR:

| Region | clone - surface mean / std | 0.1 / 1 / 50 / 99 / 99.9 percentiles (m) | (clone - surface) / TOTERR std | abs(z) > 3 |
|---|---|---|---|---|
| Whole tile (10,240,000 px) | 0.001 / 0.467 m | -1.835 / -1.192 / -0.002 / 1.208 / 1.805 | 0.998 | 0.14 % |
| Site ±300 m (14,641 px) | -0.056 / 0.383 m | -1.394 / -1.061 / -0.037 / 0.870 / 1.187 | 0.962 | 0.17 % |

Largest |difference| 7.04 m at row 244, col 1876, where TOTERR is 7.64 m.

Conclusion: the clone is the nominal surface plus an error realisation whose amplitude matches
TOTERR (normalised std ≈ 1). This supports using clones as an ensemble of plausible
terrains (D-20). It does not verify that PGDA's error model is itself correct.

## Observer height at the published Site 004 point (January 2027, Sun and antenna at the same height)

| Height | Sunlit % | Earth-visible % |
|---|---|---|
| 2 m | 0.0 | 0.0 |
| 5 m | 22.4 | 23.7 |
| 10 m | 100.0 | 44.4 |

Consistent with the 6-8 m rim at 30-100 m found by the horizon diagnostic. NASA's VSAT
programme targets vertical arrays deploying up to 32 ft (~9.8 m); this sweep does not model any
specific array, only an unobstructed point at the stated height.
