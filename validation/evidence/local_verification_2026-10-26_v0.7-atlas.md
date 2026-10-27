# Local verification record — v0.7.0-dev Luna Atlas UI refresh

**Date:** 2026-10-26  
**Purpose:** repeatable local source verification for the Luna Atlas UI refresh and source-register updates.  
**Environment:** build container Python 3.13 (see the terminal's exact version when reproducing); no outbound DNS/network access was available during this build pass.

## Checks run

| Check | Result | Scope / caveat |
|---|---|---|
| Python compile check (`scripts/verify_project.sh`) | PASS | Syntax/bytecode compilation only; does not validate real ephemerides. |
| Python tests (`PYTHONPATH=backend pytest -q`) | PASS — 119 tests | Synthetic fixtures, mocked SPICE, API contracts and offline checks. |
| JavaScript syntax (`node --check frontend/app.js`) | PASS | Parse check; not a browser interaction test. |
| Catalogue integrity | PASS | Valid empty catalogue state: `awaiting_official_source`, `official_site_count=0`. |
| Ruff | SKIPPED | Ruff is not installed in the build container; CI installs it from dev dependencies. |
| mypy | SKIPPED | mypy is not installed in the build container; CI installs it from dev dependencies. |
| Real NAIF kernel fetch | NOT RUN | Outbound DNS was unavailable; no downloaded kernels are bundled. |
| Real PGDA raster fetch / metadata review | NOT RUN | Outbound DNS was unavailable; no new DEM rasters are bundled or certified. |
| JPL Horizons golden comparison | NOT RUN | No independent real-site epoch report was generated. |
| Browser-level visual/interaction test | NOT RUN | Local browser navigation was blocked by the build environment; no browser screenshot is claimed. |
| Uncoached usability test | NOT RUN | Must be conducted with representative users before claiming child-level usability. |

## UI changes represented by this record

- Replaced the dense dashboard with the Luna Atlas field-guide design and four-step navigation: Compare places, Pick a date, Data & science, Saved results.
- Preserved existing frontend IDs and API request contracts used by regression tests.
- Retained synthetic sample values as a labelled, non-exportable exploration preview; no synthetic numbers are presented as lunar predictions.
- Added a terrain-resolution caveat using NASA PGDA Product 78 metadata and Zhong et al. (2026), plus the paper to the API source register.
- Added selected-site map point/label and DEM-footprint styling with keyboard focus states.
- Added a research source and validation-matrix update for multi-resolution sensitivity.

## Scientific readiness remains blocked

- `data/manifests/kernels.json` is not configured with validated SPICE kernels.
- `data/catalogue/sites.json` contains no official 2026 challenge sites; the official challenge data release is scheduled for 2026-10-28 and must be re-checked then.
- `data/dems/manifest.json` has no reviewed real DEM assets. A raster is not usable for terrain horizons until file integrity, coverage, coordinate frame, axis conventions, physical units, NoData semantics, vertical datum and observer-radius compatibility are evidenced.
- No end-to-end real-data run, external ephemeris golden check, terrain clone/uncertainty ensemble or multi-resolution convergence study has passed.
- The application is an engineering prototype, not a landing-safety system, and is not scientifically validated for mission operations.

## Reproduction

From a clean checkout using the project environment:

```bash
node --check frontend/app.js
PYTHONPATH=backend pytest -q
./scripts/verify_project.sh
```

A skipped check is not a passed check. Real-data claims require attached raw inputs, hashes, coverage reports, independent comparison records, and reviewer sign-off.
