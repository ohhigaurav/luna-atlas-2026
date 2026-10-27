# Local Verification Record — 2026-10-26

**Build:** `0.5.0.dev0`  
**Environment:** Python 3.13.5, local Linux build container; browser interaction smoke test used Chromium with a mocked API payload and `Asia/Kolkata` timezone.  
**Scope:** code and contract checks only; no live NAIF or PGDA downloads were executed because this build environment has no working outbound DNS/package-registry access.

## Results

| Check | Result | Evidence / caveat |
|---|---|---|
| Python test suite | **PASS — 111 tests** | `PYTHONPATH=backend python -m pytest -q`; includes kernel, SPICE adapter, geometry/model contracts, terrain synthetic raster tests including native-resolution sampling, API contracts, export/save-run and public-input downloader/kernel fetch-integrity tests. |
| Python compilation | **PASS** | `python -m py_compile` for bootstrap, terrain manifest and DEM register modules; `scripts/verify_project.sh` also runs `compileall`. |
| JavaScript syntax | **PASS** | `node --check frontend/app.js` when Node is present. |
| Browser UI boot | **PASS — mocked API** | Chromium loads HTML/CSS/JS; no `pageerror` events; Compare and Assumptions views render. Does not test a live browser-to-server scientific analysis. |
| Browser timezone contract | **PASS — mocked API** | In `Asia/Kolkata`, input values were `2027-01-01T05:30` and `2027-01-31T05:30`; captured POST payload used `2027-01-01T00:00:00Z` and `2027-01-31T00:00:00Z`. |
| Browser configuration failure path | **PASS — mocked API** | `POST /api/analysis` returning HTTP 503 is shown as an explicit configuration error; no fake result is inserted. |
| Public input bootstrap `--help` | **PASS** | Documents default full reference bootstrap and `--kernels-only`, `--skip-regional-dem`, `--skip-kernels`, `--force` modes. |
| Atomic-download regressions | **PASS** | Unit tests cover allowlisted source, bad redirect, truncation, size cap, temporary-file cleanup and SHA/size output. |
| DEM registration provenance | **PASS** | Synthetic rasters exercise reference-point projection and metadata capture; manifest intentionally leaves CRS and vertical datum flags false. |
| Real NAIF kernels loaded | **NOT RUN** | SpiceyPy/kernel binaries not present in the build container; no real kernel coverage result is claimed. |
| Real PGDA raster download / inspect | **NOT RUN** | The internet fetch step was not executable here. The bootstrap must be run from a network-connected machine. |
| JPL Horizons golden comparison | **NOT RUN** | No raw saved Horizon response or real SPICE geometry sample exists yet. |
| Official candidate-site catalogue | **BLOCKED / NOT YET RELEASED AS OF BUILD DATE** | Official rows must be imported after the challenge publishes the actual candidate set. Reference points remain in their separate catalogue. |
| Ruff / mypy | **NOT CONFIRMED** | CI commands are configured; this record does not claim local pass if either tool was unavailable. |

| Kernel transfer size and truncation | **PASS — synthetic HTTP response fixtures** | Oversized Content-Length and truncated body are rejected; no incomplete destination file is left behind. |
| Native-resolution radial sampling | **PASS — synthetic GeoTIFF** | Requested 5 m step is raised to 80 m where the configured raster declares an 80 m native pixel scale; Product 78 5 m regions retain 5 m sampling. |
| Latest full test suite | **PASS — 111 tests** | Re-run `./scripts/verify_project.sh` for the build being delivered. |
| Vectorized terrain sampling | **PASS — synthetic raster samples** | Masked cells, non-finite values and raw NoData remain unknown after scale/offset/unit conversion. |

## Review interpretation

A passing synthetic test suite establishes algorithm behavior for the chosen fixtures only. It is not a substitute for a real-kernel geometry comparison, verified DEM datum/coverage review, independent review of a real horizon profile or performance measurement on the demo laptop. The system remains a development build until gates A–F in the PRD close with archived evidence.
