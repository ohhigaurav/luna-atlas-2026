# Stand-in landing sites on real kernels and DEMs — 2026-11-01

Run by the team on a development machine (`site-catalogue-import`, Python 3.14.7) with
`scripts/check_standin_sites.py`. Inputs: the six DE421-chain kernels and three PGDA DEMs, all
nine matching the manifest SHA-256 (`sha256sum -c`, 9/9 OK). `verify_project.sh` on
`science-validation` before the switch: 6/6 checks PASS, 169 tests passed. `health()`:
`ready_for_geometry`, 6 kernels verified, `terrain_analysis_ready: true`.

Window 2027-01-01T00:00Z to 2027-01-31T00:00Z, 30 min coarse step, 1 s event tolerance,
default observer and antenna heights.

| mode | site | sunlit % | Earth % | both % | run |
|---|---|---|---|---|---|
| terrain | IM-1 | 40.37 | 100.00 | 40.37 | bc9e2d6f |
| terrain | IM-2 | 48.45 | 72.09 | 45.24 | bc9e2d6f |
| terrain | Chandrayaan-3 | 48.52 | 100.00 | 48.52 | bc9e2d6f |
| terrain | CP-12 target (Schrödinger centre) | 49.85 | 0.00 | 0.00 | bc9e2d6f |
| flat | IM-1 | 52.19 | 100.00 | 52.19 | b2e2c8fd |
| flat | IM-2 | 55.05 | 64.81 | 49.96 | b2e2c8fd |
| flat | Chandrayaan-3 | 50.81 | 100.00 | 50.81 | b2e2c8fd |
| flat | CP-12 target | 51.63 | 0.00 | 0.00 | b2e2c8fd |
| flat | Apollo 11 / 15 / 17 | 49.61 / 49.51 / 49.51 | 100.00 | = sunlit | 269970ab |
| flat | Blue Ghost 1 | 49.48 | 100.00 | 49.48 | 269970ab |
| flat | Chang'e 4 / Chang'e 6 | 51.13 / 51.11 | 0.00 | 0.00 | 5f698698 |
| flat | SLIM / IM-3 target (Reiner Gamma) | 49.69 / 50.84 | 100.00 | = sunlit | 5f698698 |

Full run IDs: terrain `bc9e2d6f-206d-49d6-be2b-35bec304d73a`, flat polar
`b2e2c8fd-4f5f-4636-ae1b-60addec66f3a`, `269970ab-91de-41fb-b598-83e0bcfcd289`,
`5f698698-432c-484a-9de1-4084164fc0fd` (saved under `data/runs/` on that machine; not in Git).

## Plausibility checks (expected before the run, not tuned afterwards)

* Far-side sites (Chang'e 4 at 177.6° E, Chang'e 6 at 206.0° E, Schrödinger centre at 132.9° E):
  Earth 0 % in every mode. Passes.
* Near-side low-latitude sites: Earth 100 %, sunlit ≈ 50 % over ~1 synodic month. Passes.
* Polar sites, sunlit: terrain < flat for all four. Passes.
* Polar sites, Earth: IM-2 terrain (72.09 %) > flat (64.81 %). Flagged in advance as suspicious;
  investigated below.

## IM-2: terrain shows Earth more often than flat

Hypothesis: flat mode places the observer on the 1737.4 km sphere (ground height 0), terrain mode
at the DEM ground height. IM-2 sits on Mons Mouton, so terrain beyond the plateau can lie below
the observer's horizontal, giving a negative horizon where Earth hangs low.

Diagnostic over the same 1442 epochs of both runs:

| quantity | value |
|---|---|
| site ground elevation (terrain run) | 5320 m |
| Earth azimuth over the window | −37.4° to −21.7° |
| terrain horizon at the Earth's azimuth | −1.47° to −0.90° |
| flat horizon (2 m antenna dip on the sphere) | −0.087° |
| Earth elevation | −2.30° to 10.72° |
| epochs clear only in terrain / only in flat | 105 / 0 |

105 / 1442 = 7.28 %, which equals 72.09 − 64.81 = 7.28 percentage points: the whole difference
is epochs where Earth lies between the terrain horizon and the flat horizon. Terrain never
blocks Earth at an epoch where flat sees it. The terrain horizon (−0.9° to −1.5°) is much
shallower than the bare-sphere dip from 5320 m (≈ −4.5°), consistent with the surrounding
south-polar terrain itself being high. Conclusion: explained by observer elevation, not a sign
or frame error.

What this does not establish: the horizon values come from the production builder; an
independent re-sampling (`tools/horizon_diagnostics.py reference-clps-im-2`) has not been run.

## Limits

* Polar terrain uses the 240 m regional DEM (no 5 m tile covers IM-1, IM-2 or Chandrayaan-3).
  IM-1 is reported to rest on a ~12° slope inside a ~1 km crater; a 240 m grid does not resolve
  that, so its terrain Earth/Sun figures describe the surroundings, not the lander's spot.
* Sites north of 60° S were run flat only (no registered DEM, D-22).
* Flat mode ignores site elevation; at high-standing polar sites it underestimates Earth
  visibility (IM-2 above) and is not a conservative bound.
* The CP-12 and IM-3 entries are named-feature centres, not landing points.
