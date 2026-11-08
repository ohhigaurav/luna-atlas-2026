# Lunar South Pole Mission Planner

**Version:** `0.7.0.dev0` · **Target:** NASA Space Apps 2026 — Lunar Landing Site Navigator

**Architecture:** Python science core + FastAPI + local-first, dependency-free HTML/CSS/JavaScript UI
**Current status:** integrated software prototype; real-kernel and real-DEM validation are still required.

The planner compares south-pole sites across a UTC interval and searches candidate landing dates against a mission profile. The interface has four views: **Compare**, **Landing-window finder**, **Assumptions & sources**, and **Export**. The UI uses the Luna Atlas field-guide design, with a simple four-step navigation model and responsive layout. The interface opens with a clearly labelled synthetic preview so charts are not blank on first launch. The UI renders server results; ephemerides, terrain horizons, event times and metrics are computed in the Python science core.

> **Scientific status:** do not describe the current build as NASA-validated, flight-ready, landing-safety certified, or as guaranteeing power/communications. All analysis outputs must carry their own kernel/DEM hashes and validation status. Research-reference locations are not official challenge sites.

## 1. Run locally

Requires Python 3.11–3.14; the repository default is Python 3.13 because that is the environment used for this regression run. Use a clean virtual environment; `uv` is the preferred package manager.

```bash
./scripts/run_local.sh
```

This one command installs the pinned project/dev dependencies (using `uv` when available) and starts the app. On a machine without `uv`, it creates `.venv/` and installs `requirements.txt` plus `requirements-dev.txt`. The first setup requires package-registry access. Once dependencies are installed, run `./scripts/run_local.sh --offline` to start without attempting an install or contacting the registry. Default bind is `127.0.0.1:8000`; override with `HOST=0.0.0.0 PORT=8000` only when you explicitly intend to expose the service.

Open <http://127.0.0.1:8000>. The UI works offline once the Python dependencies are installed. The OpenAPI schema is at <http://127.0.0.1:8000/api/docs>.

The first boot intentionally shows a configuration status when kernels or official site data are missing. On the **Assumptions & sources** screen, the public-data setup card gives the bootstrap command and enumerates the remaining review gates. The same screen now includes a live **local terrain inventory**: file presence and SHA-256 state, embedded raster CRS, native resolution, registered range, publisher link, and the separate CRS/vertical-datum review gates. The polar context map draws footprints from actual raster bounds; outlines stay dashed/provisional until both review gates pass. These are coverage extents, not landing-safety zones. You can inspect the interface and load a labelled **UX preview**; annotated screen captures are in an internal document (not published). Preview numbers are illustrative UI data and are not saved as scientific output or accepted by the Horizons validator. The Compare date/time controls are displayed in the browser's local time zone and are converted to explicit UTC ISO-8601 before the request is sent; the stored results and exports remain UTC.

### Docker (optional)

```bash
docker compose up --build
```

The initial image build needs access to the Python package registry. Kernel and DEM rasters are not baked into the image; they remain local data assets mounted into the app directory. For an air-gapped demo, build the image beforehand and then run it without network access.

## 2. Install and test

```bash
./scripts/verify_project.sh
```

The portable verification script runs compilation, tests, JavaScript syntax and catalogue validation. This checkout currently passes 119 tests (run the script locally to reproduce). It runs Ruff and mypy when installed and reports missing tools as **SKIPPED**, not as passes. In the project environment, the individual CI-equivalent commands are `uv run pytest -q`, `uv run ruff check backend tests tools`, and `uv run mypy backend/lunar_core`.

The test suite uses synthetic fixtures for numerical edge cases and mocked SPICE calls. Passing tests establish correctness for those fixtures; they do not substitute for JPL Horizons golden tests or real DEM review. Ruff and mypy are enforced in CI; run both locally before merging. A committed `uv.lock` is required for release reproducibility; this checkout does not include one because lock resolution could not be completed in the offline build container. Generate and review it with `uv lock` on a registry-connected machine, commit it, and use `uv sync --locked` for the release build.

## 3. Data intake — do not hand-edit derived manifests

### 3.1 Import the official site catalogue

The official challenge candidate list is the authority. Preserve its original dataset file separately under `data/raw/` and import a normalized CSV with these exact headers:

```csv
source_site_id,name,latitude_deg,longitude_deg,latitude_type,longitude_direction
```

`latitude_type` must be `planetocentric` or `planetographic`; longitude direction must be `east_positive` or `west_positive`. The importer canonicalizes longitude to east-positive degrees in `[0, 360)` while preserving the original CSV row and file SHA-256 in each site record.

```bash
uv run python tools/import_official_sites.py /absolute/path/official_sites.csv \
  --source-url 'https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/'
```

A header-only schema template is provided at `data/catalogue/official_sites_template.csv`. The importer validates the complete replacement before atomically writing `data/catalogue/sites.json`. It will reject malformed rows, duplicate IDs, absent source values, and non-HTTPS source URLs. It does not guess coordinates or turn literature landmarks into official sites. If the official file includes landing ellipses/polygons rather than points, preserve those original fields in a new versioned schema; do not reduce them silently to a centroid.

### 3.2 One-command public reference-data bootstrap

After the Python runtime dependencies are installed, run:

```bash
./scripts/bootstrap_public_reference.sh
```

This fetches the six pinned NAIF DE421/MOON_ME kernel candidates, Product 78 Site01 and Site04 5 m/pixel surface DEMs, and the Product 90 regional 240 m/pixel DEM spanning 60°S–90°S (about 210 MB according to the publisher). Site01 is mapped to the published `reference-lola-site-001` literature point; Site04 is mapped to `reference-lola-site-004`. The regional tile is mapped as a shared fallback and its actual coverage is checked against the current literature reference points. The files are not assigned to official challenge sites automatically. Use `--skip-regional-dem` to omit the regional raster, or `--kernels-only` to fetch only SPICE kernels. Use `--force` only when intentionally fetching fresh copies.

The downloader uses HTTPS-only allowlisted publisher hosts, validates redirects and response size, writes into temporary files, and only registers a raster after checking that the reference point transforms inside a non-NoData pixel. This is a data-integrity check, **not** a complete coverage, projection or vertical-datum validation. The manifest deliberately records `crs_contract_verified=false` and `vertical_datum_verified=false`; the API must keep terrain analysis blocked until those contracts have been reviewed and attested with a note.

### 3.3 Fetch or audit the pinned SPICE kernel candidate set

```bash
uv run python tools/fetch_kernels.py
```

The fetcher downloads from the NAIF HTTPS host, enforces per-file byte ceilings and Content-Length integrity, writes byte hashes in `data/manifests/kernels.json`, and does not package the binaries in Git. Existing local files are reused only if their digest and URL are already attested by the previous manifest; otherwise the command fails closed and requires explicit `--force` to fetch fresh bytes.

The candidate set includes an LSK, text PCK, Moon frame definitions, a DE421 planetary SPK and DE421-associated lunar orientation BPC. Kernel presence and hashes are not proof of frame correctness or epoch coverage. The BPC manifest entry declares `coverage_frame=MOON_PA_DE421`, the frame class stored in the selected DE421 binary PCK; the runtime checks that class with `pckcov` and verifies the transform to requested `MOON_ME` with `pxform` at both run endpoints. Verify frame transforms, body radii, loaded SPK/BPC interval coverage and target availability before running the golden geometry validation. Never mix a different SPK/frame chain without recording a decision and repeating the golden test.

### 3.4 Register DEMs and explicitly review the datum contract

```bash
uv run python tools/register_dem.py --help
```

Register each original, unmodified GeoTIFF/COG with a unique asset ID, source URL, product ID, hash, native pixel scale and valid distance interval. `--elevation-units` is mandatory (`m`, `km`, `cm`, or `mm`): runtime sampling applies the raster band's GDAL scale and offset first, then converts the declared physical units to metres. Raw NoData is checked before scale/offset. These transformations are recorded in the DEM manifest's metadata notes and run provenance. Product 78 is a set of 5 m/pixel site DEMs in the south-polar stereographic system and MOON_ME / DE421 frame; its interpolated-cell fraction can be high. Terrain sampling respects the asset resolution: the requested 5 m near-field step is increased to at least the declared native pixel scale where only coarser terrain exists. Product 90 provides regional multi-resolution DEMs. Product 69 is a long-term illumination product and is a **sanity-check overlay only**, not a substitute for time-specific SPICE geometry.

The runtime refuses terrain-aware analysis until the asset manifest records both `crs_contract_verified` and `vertical_datum_verified` with meaningful review notes. Those flags are review attestations, not automatic conclusions from opening a GeoTIFF. Confirm the horizontal axis/projection, pixel registration, lunar radius/frame, height units and vertical origin before setting them. Use nested fine/coarse assets with distance bounds that cover the chosen maximum range. NoData remains unknown; it is never converted to zero elevation or open sky.

Keep source files and metadata reports outside version control. The repository ignores DEM/kernel binaries under `data/dems/assets/` and `data/kernels/`.

## 4. Main workflows

### Compare analysis

`POST /api/analysis` accepts 1–4 site IDs, a UTC interval, separate Sun observer and antenna heights, event tolerance, coarse step and flat/terrain horizon mode. It returns samples, refined windows/roots, metrics, horizon profiles, warnings and provenance. Flat horizon is useful for geometry smoke-testing but is not terrain-aware. Terrain mode requires registered hash-verified assets and a reviewed datum/CRS contract for each selected site.

Example request shape:

```json
{
  "site_ids": ["reference-malapert-massif", "reference-shackleton-crater"],
  "start_utc": "2027-01-01T00:00:00Z",
  "end_utc": "2027-01-03T00:00:00Z",
  "coarse_step_min": 30,
  "event_tolerance_s": 1.0,
  "sun_observer_height_m": 2.0,
  "antenna_height_m": 2.0,
  "earth_min_clearance_deg": 0.0,
  "horizon_mode": "flat"
}
```

This example is a schema example only; the reference sites are literature points. Use current official IDs for challenge claims. The API saves completed runs in `data/runs/` with a unique run ID. A preview is never treated as an analysis result.

### Landing-window finder

`POST /api/finder` uses the same engine and a mission profile (`mission_duration_days`, maximum continuous darkness, maximum Earth-centre-not-clear gap, maximum joint outage, minimum sunlit fraction). It evaluates every candidate date in the requested range and records all failed constraints and the size of each violation. Constraint limits are inputs chosen by the user, not mission-certified thresholds.

### Exports

- `GET /api/runs/{run_id}/export.json` gives the exact saved result and provenance.
- `GET /api/runs/{run_id}/export.csv` gives a rectangular CSV including samples, events, metrics and finder cells, with JSON payload columns for lossless expansion.
- `GET /api/runs/{run_id}` reopens a saved run.

Replaying a saved scenario requires the same code commit, data/kernel/DEM hashes and settings. The export makes this explicit; it does not bundle large source assets.

## 5. Service API

| Method | Endpoint | Role |
|---|---|---|
| `GET` | `/api/health` | Configuration, package presence, kernel and DEM preflight state |
| `GET` | `/api/sites` | Official catalogue only |
| `GET` | `/api/reference-sites` | Separate literature-reference points for exploratory UI/testing |
| `GET` | `/api/assumptions` | Model equations, contracts and non-claims |
| `GET` | `/api/sources` | Public data/source register |
| `POST` | `/api/analysis` | Site/date ephemerides, visibility, windows and metrics |
| `POST` | `/api/finder` | Site × candidate start-date feasibility grid |
| `GET` | `/api/runs` | List saved run summaries for offline demo selection |
| `GET` | `/api/runs/{run_id}` | Load a saved result |
| `GET` | `/api/runs/{run_id}/export.json` | JSON export |
| `GET` | `/api/runs/{run_id}/export.csv` | CSV export |

## 6. Science contract

- **Time:** parse explicit UTC; convert to SPICE ET/TDB through the loaded LSK. Never compare UTC strings as though they were ET seconds.
- **Frame:** default is MOON_ME associated with DE421 orientation. Record the exact FK/PCK/BPC/SPK chain and body radii. Do not change the chain without a decision record and renewed golden test.
- **Observer:** body-fixed point whose radius is `R + sampled_ground_height + observer_height`. The DEM vertical datum versus reference-radius relationship is an explicit reviewed contract.
- **Terrain horizon:** apparent elevation is calculated along spherical surface rays; per-azimuth controlling range and coverage are retained. Missing/uncovered data means incomplete coverage.
- **Sun margin:** `g_sun = elevation_sun + asin(R_sun / range_sun) - H_sun(azimuth_sun)`.
- **Earth-centre-clear margin:** `g_dte = elevation_earth - H_earth(azimuth_earth) - clearance`. This means geometric line of sight to Earth's centre under the specified rule, not a link budget or communications availability.
- **Events:** coarse sign-change bracketing + Brent refinement + a local-extremum/grazing diagnostic. Numerical root tolerance is not a completeness proof. A certified maximum margin-rate bound/adaptive scheme is still required before claiming that no short window can be missed.
- **Metrics:** integrate intervals derived from refined windows; truncated interval-edge outages are lower bounds (`>=`). Finder candidates clip those same windows to each mission interval.
- **Comparison:** hard constraints first; never create a universal “best site” score without visible weights and sensitivity analysis.

## 7. Independent validation, required before public scientific claims

1. **Site and terrain data gate:** source records, coordinate/latitude conventions, original files, CRS round-trip tests, vertical-datum review and per-site coverage map.
2. **SPICE geometry gate:** pin dependencies/kernels and record hashes; test at ≥3 epochs on ≥2 sites including near-horizon cases. Save full JPL Horizons query and raw response; normalize output to `validation/templates/horizons_reference_template.csv`.
3. **Tolerance gate:** before viewing the errors, approve `validation/horizons_tolerances.json` (`status=approved_before_run`, UTC `predeclared_utc`, reviewer, and numeric tolerances). The comparator refuses a missing/unapproved tolerance or one declared after the run started.
4. **Terrain gate:** analytical flat-sphere test, ridge/far-rim/NoData/0° wrap, observer height changes, azimuth resolution sensitivity, and a real horizon reviewed by a second person.
5. **Event/metrics gate:** synthetic crossings, short windows, tangencies, interval truncations, event-step convergence, and recomputation of metrics from exported windows.
6. **Performance and UX gate:** benchmark on the actual demo laptop (4 sites × 30 days; 4 × 90 finder starts), complete six PRD usability tasks without coaching, and rehearse with networking disabled.

Run the approved Horizons comparison only after a real run and a saved reference file exist:

```bash
uv run python tools/compare_horizons.py \
  data/runs/<real-run-id>.json validation/horizons_reference.csv \
  --tolerances validation/horizons_tolerances.json
```

The comparison has deliberately not been run in this starter environment: no actual SPICE kernels, official candidate sites or verified site DEMs are bundled. Never choose tolerances after looking at the observed errors.

## 8. Repository map

```text
backend/lunar_core/   science core, API models, SPICE/DEM adapters, finder, metrics, exports
frontend/             four-screen self-contained web app (no remote JS/fonts)
data/catalogue/       official candidate sites (initially empty, populated by importer)
data/reference/       literature reference points; never merged into the official catalogue
data/manifests/       pinned SPICE kernel hashes and ordered load set
data/dems/            DEM asset/provenance manifest and metadata notes
data/cache/horizons/  content-addressed DEM horizon cache (generated, ignored by Git)
data/runs/            saved JSON runs (generated, ignored by Git)
tools/                catalogue import, kernel fetch, DEM register, Horizons comparison
validation/           approved-tolerance contract, golden CSV template, output evidence
 tests/               deterministic synthetic and mocked-adapter tests
 docs/                 architecture, modeling contract, release gates, public copy and demo runbook
```

## 9. Known limits / current delivery status

- Actual NAIF kernels have not been downloaded in this development container, and no SPICE geometry comparison against JPL Horizons has been executed.
- Official challenge candidate data and per-site DEM assets are not bundled; site records and assets must be imported with provenance.
- The science core and UI/API are integrated, but the product remains a **prototype pending independent scientific validation**; CI lint/type checks must be green before release.
- There is no public GitHub remote or hosted deployment configured by this repository; these are release actions, not completed artifacts.
- No landing hazard certification, power/battery sizing, RF link budget, DSN schedule, thermal model or guaranteed comms uptime is claimed.

## 10. Authoritative public references

- NASA Space Apps 2026 — [Lunar Landing Site Navigator](https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/).
- NASA PGDA — [High-Resolution LOLA Topography for Lunar South Pole Sites, Product 78](https://pgda.gsfc.nasa.gov/products/78) and [South Pole Landing Site LOLA DEM downloads](https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/).
- NASA PGDA — [A New View of the Lunar South Pole from LOLA, Product 90](https://pgda.gsfc.nasa.gov/products/90).
- NASA PGDA — [Lunar Polar Illumination, Product 69](https://pgda.gsfc.nasa.gov/products/69).
- NAIF — [CSPICE `azlcpo_c`](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/azlcpo_c.html) and [binary-PCK coverage `pckcov_c`](https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/pckcov_c.html).
- JPL — [Horizons API documentation](https://ssd-api.jpl.nasa.gov/doc/horizons.html).
- LOLA landing site uncertainty methods: Barker et al. (2021), [doi:10.1016/j.pss.2020.105119](https://doi.org/10.1016/j.pss.2020.105119); PGDA Product 90: Barker et al. (2023), [doi:10.3847/PSJ/acf3e1](https://doi.org/10.3847/PSJ/acf3e1).
- Literature reference points: [NASA Malapert region](https://science.nasa.gov/image-detail/20100618/), [open-access south-pole exploration study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10518707/), [LOLA Site 001/004 paper](https://doi.org/10.3847/psj/aca590).

Exact retrieval timestamps, raw filenames, file sizes, hashes and product-specific citation metadata must be recorded when the official data are staged. See `NOTICE.md` and `data/dems/manifest.json`.


## 6. Luna Atlas UI refresh (0.7.0-dev)

The front end has been redesigned as a lunar field atlas rather than a dense operations console. The default journey is: **Compare places → Pick a date → Data & science → Saved results**. Visual language uses paper/stone surfaces, a dark navigation rail, amber for the Sun, teal for Earth, larger form labels, responsive layouts and no external font/CDN dependency. Existing API contracts and IDs used by the frontend are preserved, and UTC conversion is stated beside the date controls.

The data-source register now also links NASA PGDA Product 104, a 5 m/pixel shape-from-shading product for 13 earlier Artemis III candidate regions. It is a supplemental dataset, not the authority for the 2026 challenge site catalogue. The UI also flags a key scientific caveat from Zhong et al. (2026): one Chang’e-7 region study found 5 m and 20 m DEMs overestimated cumulative illumination relative to a 1 m baseline. This is a reason to run site-specific resolution sensitivity analysis—not a correction factor the app applies. The build environment used for this release had no outbound DNS/network access; no new kernel or DEM binaries were downloaded into this archive. Run `./scripts/bootstrap_public_reference.sh` from an internet-connected machine when appropriate. The official 2026 challenge catalogue remains empty until the official source file is released and imported.

See an internal document (not published), [`docs/SCIENCE_VALIDATION_STATUS.md`](docs/SCIENCE_VALIDATION_STATUS.md), and an internal document (not published) for the design specification, current scientific gates, source register and validation matrix. For local/Docker deployment and release-blocking gates, see [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). The current validation scoreboard (every gate, PASS and FAIL, with its evidence file) is [`docs/SCIENCE_VALIDATION_STATUS.md`](docs/SCIENCE_VALIDATION_STATUS.md).
