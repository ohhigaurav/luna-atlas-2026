# Local verification record — 2026-10-25

**Build:** `0.4.0.dev0`
**Scope:** source-level tests, Python compilation, browser asset syntax, local HTTP startup, and default-catalogue integrity.
**This is not the real-data scientific validation report.**

## Results

| Check | Result | Evidence / interpretation |
|---|---|---|
| Python source compilation | PASS | `python -m compileall -q backend/lunar_core tools` |
| Automated test suite | PASS — 98 tests | `./scripts/verify_project.sh`; synthetic fixtures, API contracts, manifests, terrain-horizon math, window solver, finder, saved runs and export schemas |
| Frontend JavaScript syntax | PASS | `node --check frontend/app.js` |
| Git whitespace/conflict check | PASS | `git diff --check` |
| Ruff | SKIPPED | Ruff is not installed in this build container; CI is configured to install and run it |
| mypy | SKIPPED | mypy is not installed in this build container; CI is configured to install and run it |
| Official catalogue | Valid empty state | `catalogue_state=awaiting_official_source`; `official_site_count=0` |

## Local HTTP smoke test

The application was launched with the installed environment using `PORT=8124 ./scripts/run_local.sh --offline`. The following paths returned HTTP 200: `/`, `/static/app.css`, `/static/app.js`, `/api/health`, `/api/sites`, `/api/reference-sites`, `/api/assumptions`, `/api/sources`, `/api/runs`, and `/api/openapi.json`.

Health response at the time of the smoke test:

- `status=configuration_required`
- `spiceypy_installed=false`
- `science_core_ready=false`
- `official_site_count=0`
- `reference_site_count=7`
- `kernel_manifest_state=not_configured`
- `dem_manifest_state=not_configured`

This is the expected safe state for an unconfigured checkout. The API must not manufacture real-site output when dependencies or inputs are absent.

## Not performed / not claimed

- No actual NAIF kernels were downloaded or loaded in this container.
- The new `pckcov` check of the manifest-declared `MOON_PA_DE421` PCK frame class and `pxform` verification into `MOON_ME` at the run endpoints were tested with a fake SPICE adapter, not real kernels.
- No JPL Horizons golden comparison has been run; approved D-10 tolerances and saved reference observations are still required.
- No official 2026 challenge-site records have been staged in this checkout.
- No PGDA DEM assets have been registered; CRS and vertical-datum review remain open.
- No target-laptop performance, manual browser usability, accessibility scan, clean-install, or network-off demo with genuine computed results has been recorded.
- Dependency lock generation is still pending because the package registry was inaccessible in the build environment. Pinned direct dependencies are declared, but a reviewed `uv.lock` is required for a reproducible release build.

**Disposition:** prototype package can start locally and its current synthetic/API tests pass. It must remain labelled as not independently validated until the blocked evidence above is produced.
