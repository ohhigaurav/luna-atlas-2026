# Scientific validation status — 0.7.2-dev

## Gate S (slope layer) — pass rule written, not yet run (2026-11-07)

Computed slope (Horn 3×3 on the 5 m PGDA Product 78 DEMs) is to be compared with PGDA's published slope maps at Sites 001 and 004 under `validation/slope_tolerances.json`, predeclared 2026-11-07T14:12:20Z before any comparison (status `proposed_before_run`; the team may still change the numbers before the first run). Run: `tools/validate_slope.py --fetch` then `tools/validate_slope.py`. Until it passes, slope answers say `validation.status: not_run`. Verified so far: analytic surfaces only (plane exact to 1e-12°, cone, NoData, scale factor, frame round-trips to 1e-6 m).

## Gate B passed (2026-10-28)

SPICE Sun/Earth geometry agrees with JPL Horizons to 0.0212 arcsec azimuth, 0.0413 arcsec elevation and 0.0107 km range at two south-polar reference points (20 comparisons, 8 near the horizon), against 1 arcsec / 1 arcsec / 1 km tolerances approved before the run. Evidence: `validation/evidence/gate_b_geometry_2026-10-28.md`. Still open: Gate C (terrain review), Gate D on real data, usability and release gates.


## What is verified in this checkout

- 119 unit/API tests pass, including synthetic numerical edge cases and mocked SPICE/API flows.
- FastAPI exposes the compare, finder, source/assumption, terrain-inventory, saved-run and export endpoints.
- Kernel and DEM manifests fail closed when real inputs or required review flags are missing.
- Provenance captures configuration/manifests/hashes for computed runs.
- The browser-local timestamp controls are converted to explicit UTC instants before API calls.
- Terrain horizons preserve missing/NoData semantics; incomplete horizons are not silently promoted to verified terrain.

## What is not verified

- No real SPICE kernels are present in the packaged checkout; the kernel manifest starts `not_configured`.
- No official 2026 challenge catalogue has been imported. Literature/reference points are a separate set.
- No real DEM raster is bundled/registered in the default checkout.
- No real SPICE frame/coverage preflight or JPL Horizons golden comparison has been run in this build environment.
- No real-terrain horizon result has passed CRS, frame, radial coverage, elevation-unit, vertical-datum or convergence review.
- Product 104 has been added to the source register as a potential supplement only. It has not been downloaded/registered or presumed to cover the 2026 official sites.
- DEM resolution sensitivity is a required open validation gate. Zhong et al. (2026) reported mean cumulative relative illumination increases of 27.5% (5 m) and 65.1% (20 m) versus a 1 m baseline for one Chang’e-7 study region; these are not universal correction factors. The current planner does not yet run clone ensembles or a complete multi-resolution sensitivity study.
- The scientific engine has not undergone an independent expert review. The test suite is necessary regression evidence, not scientific acceptance.

## Required pre-release gates

1. Import the unmodified official challenge site file, preserving all original fields and SHA-256.
2. Fetch the pinned NAIF kernel candidates from NAIF over HTTPS and record exact versions, hashes, load order and coverage; verify the BPC stored frame and the transform to `MOON_ME` over every requested epoch.
3. Use explicit, pinned leap-seconds, SPK, PCK, frame and aberration conventions. Preserve raw Horizons queries/responses, settings and retrieval time.
4. Compare SPICE topocentric azimuth/elevation against JPL Horizons at predeclared epochs across at least two sites, including a near-horizon case, with a tolerance approved before viewing differences.
5. Verify raster CRS, lunar frame/radius, axis order, pixel registration, scale/offset, NoData, elevation units and vertical datum for every terrain asset. Do not infer datum equivalence from a non-NoData sample.
6. Confirm site-centred coverage along every azimuth to the configured range. Use near-field high-resolution DEM where available and far-field products only under their declared range/resolution contract.
7. Run terrain clones/uncertainty ensembles where available; report distributions and sensitivity of event times/metrics, not only a single best estimate.
8. Check event-time convergence by halving the coarse step; demonstrate tangent/grazing-event handling and report unresolved edge intervals.
9. Recompute exported metrics independently from event windows; include time boundaries and truncated-outage lower bounds.
10. Run clean-install, offline, performance and user usability tests. Keep open gates visible in the release report.

## Mathematical contracts in scope

The horizon equation and visibility definitions are in `docs/modelling_contract.md`. For each azimuth, terrain elevation is transformed to apparent angle on the declared spherical Moon; the horizon is the maximum valid apparent elevation. Missing/uncovered rays are incomplete. Sun visibility uses upper-limb margin `e_s + asin(R_sun/r_sun) - H(a_s)`; Earth-centre visibility uses `e_E - H(a_E) - m`. Events are roots of those margins with bracket/refinement and grazing-event diagnostics. Metrics are based on refined windows and the requested interval denominator; a boundary-truncated outage is a lower bound. The date finder clips candidate mission windows to `[start, start + duration]` and reports individual constraint violations. None of these definitions certifies safe landing, actual power generation, or RF link availability.

## Environment note

Outbound DNS/network access was unavailable in the build container, so this package did not acquire fresh NAIF binaries or NASA rasters. The repository scripts are prepared to fetch the pinned candidates from their official HTTPS publishers on a connected machine. The official challenge data release is separate and should be ingested only from its authoritative source.
