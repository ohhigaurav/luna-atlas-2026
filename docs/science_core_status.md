# Science-core implementation status

**Release:** `0.7.0.dev0` (development build; science status unchanged by the UI refresh)
**Contract:** PRD v0.1 and `docs/modelling_contract.md`
**Local baseline:** the repository test suite currently has 111 passing tests; the build/verification script also checks Python compilation, JavaScript syntax and official-catalogue integrity. Ruff and mypy are configured in CI but could not run locally because these packages are not installed in the current build environment. Optional Ruff/mypy tools are reported as skipped if not installed.

This is an integrated software prototype. It is not a completed real-site scientific analysis because the official sites, actual kernel set and verified DEM assets have not been staged here. The API intentionally refuses to produce SPICE-backed output without its kernel prerequisites.

## Implemented

| Module | Implemented behaviour | Evidence available | Still not proven |
|---|---|---|---|
| `catalogue.py` / `models.py` | Typed official-site records, source-record preservation and convention validation | Schema, import and fail-closed tests | Actual official candidate rows and source-record review |
| `kernels.py` | Manifest schema, ordered loading, SHA-256 and byte-count checks, project-root path confinement, rehash before furnish and partial-load cleanup | Synthetic manifest/hash/path/load-failure tests | Actual kernel binaries and end-to-end load, plus execution of the BPC preflight against real kernels |
| `spk_coverage.py` | SPK coverage unions and continuous Moon/Sun/Earth requested interval check with light-time pre-roll | Synthetic interval/coverage tests | Loaded real SPK coverage across supported mission dates; BPC check is a separate preflight and has not yet run against real kernels |
| `geometry.py` | SPICE `azlcpo` surface observer, UTC→ET, explicit `MOON_ME`, `LT+S`, range/angle conversion, spherical PCK guard | Mock adapter checks call conventions and units | Real SpiceyPy execution and independent Horizons golden comparison |
| `terrain.py` | Rasterio DEM reads, CRS transforms, NoData semantics, raster scale/offset + physical-unit conversions, nested distance-based assets, horizon cache key with source hashes/settings/algorithm version | Fake/synthetic raster/manifest tests | Real product metadata inspection, CRS round-trip, vertical datum acceptance and coverage review |
| `horizon.py` | PRD SR-04 apparent-elevation rays, maximum terrain angle, controlling distance, analytical flat dip, azimuth interpolation with wrap and explicit incomplete flags | Synthetic flat, ridge, far-rim, missing-data and interpolation tests | Site-level DEM horizon review and 0.5° vs 0.25° convergence on real terrain |
| `visibility.py` | PRD SR-05 Sun upper-limb margin and SR-06 Earth-centre-clear margin; separate Earth-disc helper | Equation/boundary tests, including PRD's −1.034° example | Margins from validated real geometry and terrain |
| `events.py` | Coarse brackets, Brent root refinement, residuals, sampled-zero classification, local-extremum/grazing diagnostics, truncated boundaries | Synthetic crossing, short-window, tangency and convergence tests | Proof of complete event detection for the actual margin function and a validated real-run convergence study |
| `metrics.py` | SR-08 fractions and outage intervals, edge truncation, window count/median | Hand-calculated interval fixtures and export tests | Accepted end-to-end recomputation from saved real output |
| `finder.py` | SR-09 site/start-date grid, window clipping, enabled constraints, quantitative violations | Hand-checked site-date fixture | Validated real window data, performance benchmark and event-to-UI explanation from terrain blockers |
| `analysis_service.py` | Single shared geometry/horizon/margin/events/metrics path; same engine used for finder; saved runs and provenance | Type/unit tests, schema contracts and fail-closed API tests | Running it successfully with pinned real inputs; full science report and independent replay |
| `api.py` + `frontend/` | Four views, analysis/finder requests, saved-run index/load, JSON/CSV exports, assumptions/sources | API/TestClient and frontend static contract tests; `node --check` | Browser usability, accessibility checks and real-result presentation review |

## Critical mathematical limitation: event completeness

Brent's method refines a root once a continuous sign-changing bracket is known. The current solver additionally searches sampled local extrema to catch some windows hidden between same-sign coarse samples. This is a valuable defensive heuristic, **not a proof that every short visibility window is found**. A guarantee requires a justified bound on the margin's variation/derivative, conservative adaptive subdivision with a stopping certificate, or another demonstrably complete search method for the model. Until that is established, report sampled event-discovery limitations and test with multiple step sizes; do not claim that no window longer than a stated duration can be missed.

## Data contract and geometry limitations

- All user times must be explicit UTC. Convert each timestamp to SPICE ET using the loaded LSK; never subtract UTC strings or treat UTC seconds as ET.
- `MOON_ME` plus the DE421-associated lunar orientation is the current PRD convention. Kernel hashes establish byte identity, not correct frame semantics.
- The current geometry adapter fails closed when the loaded lunar PCK radii are not equal. An oblate-body geodetic implementation would be needed if the chosen kernels introduce unequal radii.
- SPK coverage is checked, including a conservative `LT+S` pre-roll. The BPC preflight now checks the manifest-declared stored frame class (the selected DE421 BPC uses `MOON_PA_DE421`) with `pckcov`, then verifies `pxform` into `MOON_ME` at both interval endpoints. These checks have synthetic tests but still require execution against the downloaded, hash-pinned NAIF kernel set.
- DEM CRS and vertical datum verification flags require a documented human review. Opening a raster successfully does not prove its coordinate system represents the same lunar frame/radius as the SPICE observer.
- Product 69 long-term illumination is a sanity-check overlay only. It is not the ground truth for a particular landing date.

## Blockers to a defensible deployment

1. Import the official site list with the original file, exact URL, retrieval timestamp and SHA-256; do not use the reference-site catalogue as a substitute.
2. Fetch and pin the actual kernel set, verify SPK and BPC interval coverage, confirm frame transforms/radii and settle the D-07 frame chain.
3. Predeclare D-10 Horizons tolerances, save exact query parameters and raw reference output, then compare ≥3 epochs × ≥2 sites with one near-horizon case.
4. Stage product 78/90 DEMs, inspect geospatial metadata, prove coordinate round trips, establish the DEM vertical datum/reference-radius relation, and verify complete ray coverage.
5. Demonstrate event/metric/finder correctness on validated real results; reimport exported output and independently recompute metrics.
6. Generate and commit a reviewed `uv.lock`, pass CI lint/type checks, benchmark the demo laptop, test the web UI manually, and perform an offline run from a saved genuine result.

See `acceptance_matrix.md` for release-gate status and `requirements_traceability.md` for PRD FR/NFR/SR mapping.

## v0.6-dev addendum (2026-10-26)

- Added an HTTPS-only, publisher-host-allowlisted public-input bootstrap for the DE421/MOON_ME NAIF candidate kernels, PGDA Product 78 Site01 and Site04 5 m/pixel reference DEMs, and the Product 90 regional 240 m/pixel DEM covering 60°S–90°S.
- The bootstrap uses size caps, redirect validation, atomic temporary downloads, SHA-256 and byte counts, publisher URL and UTC retrieval timestamp; it inspects raster metadata and requires the literature point to map into a non-NoData sample.
- DEM provenance now supports `retrieved_utc` and `size_bytes`. `tools/register_dem.py` does not invent a retrieval timestamp for a manually supplied file: pass the actual value with `--retrieved-utc` or leave it unknown.
- Fixed the frontend's `datetime-local` conversion. Browser-local wall-clock values are now converted to UTC before JSON submission; default field values are constructed to represent exact UTC midnights in any browser timezone.
- Updated the compare map label layout for selected reference sites to use leader lines rather than stacking labels on top of the polar point cluster.
- These additions do not download real source binaries in this environment and do not change the official catalogue. Datum/frame validation and JPL Horizons validation remain external scientific acceptance gates.

- Browser integration smoke tests were run with Chromium and an explicit mocked API contract in `Asia/Kolkata`: the UI renders, local-time values convert to UTC instants, the UX preview is visibly labelled as simulated, and unconfigured real analysis presents an explicit prerequisite error.
- The NAIF fetcher now enforces per-kernel byte ceilings and validates Content-Length against bytes received; a partial or oversized response is deleted rather than committed.
- Terrain ray-distance sampling now changes by asset coverage boundaries and chooses `max(requested step, native pixel size)` per segment, avoiding unnecessary 5 m sampling over the regional 240 m DEM while retaining 5 m where Product 78 coverage exists. The algorithm version and cache key have been incremented.
- **Historical verification note:** at the time of that intermediate v0.6 snapshot, `./scripts/verify_project.sh` reported 111 tests passing. The later v0.6-dev addendum below records the current 118-test result after the coverage-inventory and nested-fallback additions. These remain synthetic/API checks, not live input validation.

- Horizon raster sampling now uses vectorized NumPy conversion per Rasterio chunk while preserving raw NoData masks, scale/offset semantics and declared units. A regression fixture confirms masked, non-finite and raw NoData values remain unknown. Cache algorithm version is now `terrain-horizon-1.4-vectorized-sampling-resolution-adaptive`.

## 0.6-dev addendum (2026-10-26)

- Added a terrain-coverage inventory endpoint and dynamic map overlays. The endpoint hashes each registered raster before exposing its footprint and marks outlines provisional unless the CRS and vertical datum review attestations are both present. Footprints are descriptive extents only; they never unlock terrain calculations.
- Corrected nested DEM sample selection: each radial sample is assigned to the finest source that returns a valid elevation; if a finer source returns NoData, the next eligible coarser asset may supply a real sample. Samples remaining unknown across all eligible assets stay NaN and make the relevant azimuth incomplete. Run provenance records accepted samples by asset, fallback sample count and remaining unknown samples.
- Terrain cache algorithm identifier is now `terrain-horizon-1.5-valid-sample-nested-fallback` so caches from earlier semantics cannot be silently reused.
- Added synthetic raster coverage and nested-fallback regression tests.


## v0.7-dev addendum (2026-10-26)

- The frontend was redesigned into the Luna Atlas field-guide navigation and responsive visual system. The scientific core and its input gates were not promoted to a higher validation tier by this redesign.
- `pytest -q`: 119 passed in the build environment. The suite uses synthetic fixtures/mocks and is not evidence of real-kernel or real-terrain acceptance.
- The source register includes PGDA Product 104 as a potential supplemental SDEM source for earlier Artemis III candidate regions only; no 2026 official-site coverage is inferred.
- No new external kernels/rasters were downloaded in this build environment because outbound DNS was unavailable. Real data acquisition, official catalogue import, Horizons comparison and datum review remain open.
