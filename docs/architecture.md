# Architecture and implementation boundaries

## Implemented dependency graph

```text
Self-hosted HTML/CSS/JavaScript UI
        │ HTTP/JSON; UI does not calculate physics
        ▼
FastAPI + Pydantic ─────────────── saved-run JSON/CSV export
        │
        ▼
Python science/service layer
  catalogue → time conversion → SPICE geometry
  DEM manifest → Rasterio/pyproj → terrain horizon
  visibility margins → event solver → interval metrics → finder
        │
        ├── NAIF kernel assets + manifest (local, hash-verified)
        ├── PGDA DEM assets + manifest (local, hash-verified)
        ├── official site catalogue (versioned, source-preserving)
        └── run manifests and horizon cache (generated, ignored by Git)
```

The browser only presents the API response and controls. It does not read kernel/DEM files or implement celestial/terrain calculations. The science code is importable and can be tested without launching the web server. CSPICE access is serialized because its kernel pool is process-global.

## Runtime endpoints

| Method | Route | Behaviour |
|---|---|---|
| GET | `/` | Local web app |
| GET | `/api/health` | Dependency, catalogue, kernel and DEM preflight status; readiness is not validation |
| GET | `/api/sites` | Official candidate catalogue only; initially empty until official data are imported |
| GET | `/api/reference-sites` | Separate literature points for exploration; not official challenge sites |
| GET | `/api/assumptions` | Model semantics and non-claims |
| GET | `/api/sources` | Public data references and roles |
| POST | `/api/analysis` | SPICE-backed time series, margins, refined events, metrics and provenance |
| POST | `/api/finder` | Extended time series plus site × candidate-date constraint grid |
| GET | `/api/runs` | Small summaries of persisted valid run manifests |
| GET | `/api/runs/{run_id}` | Load a saved run without recalculation |
| GET | `/api/runs/{run_id}/export.json` | Full JSON result and provenance |
| GET | `/api/runs/{run_id}/export.csv` | Rectangular analysis/finder export with lossless JSON payload columns |

## Module boundaries

| Module | Responsibility | Current evidence / remaining gate |
|---|---|---|
| `catalogue.py`, `models.py` | Versioned site records and coordinate conventions | Schema tests pass; official source rows are not present yet |
| `kernels.py`, `spk_coverage.py`, `spice_runtime.py` | Hash-verified kernel load, SPK interval coverage, serialized CSPICE calls | Unit tests pass; SPK target coverage and manifest-declared BPC frame-class coverage are checked separately; real-kernel coverage and `MOON_PA_DE421` → `MOON_ME` frame-chain run remain outstanding |
| `geometry.py` | `azlcpo` surface-point Sun/Earth azimuth, elevation and range | Mock adapter contract tests pass; no JPL Horizons golden comparison yet |
| `terrain.py` | Rasterio sampling, CRS transforms, NoData, scale/offset and content-addressed horizon cache | Synthetic/unit tests pass; real DEM metadata, datum and site coverage review remain |
| `horizon.py` | `H(az)` using spherical surface rays, controlling range and coverage flags | Synthetic flat/ridge/far-rim/NoData/wrap tests pass |
| `visibility.py` | Sun upper-limb and Earth-centre-clear margins | Unit tests pass |
| `events.py` | Root bracketing/refinement, grazing diagnostics, event metadata and interval truncation | Synthetic tests pass; general event completeness is not certified |
| `metrics.py` | Fractions, longest outages and window statistics from intervals | Synthetic hand-checked interval tests pass |
| `finder.py` | Evaluate mission constraints over candidate start times | Synthetic grid and constraint-violation tests pass |
| `analysis_service.py` | Wire geometry → horizon → margins → events → metrics/finder, save runs and export provenance | Code is wired; currently blocked at startup by absent real kernel/site/DEM inputs |
| `api.py`, `api_models.py` | Typed API, request caps, fail-closed errors, static UI, run loader | API and static bundle contract tests pass |
| `frontend/` | Four views: Compare, Finder, Assumptions & sources, Export | Static JS/API contract tests pass; manual browser/usability review remains |

## Fail-closed rules

- The official catalogue is separate from literature-reference points; no coordinates are invented.
- A result requiring SPICE cannot run without hash-verified kernels and requested-epoch SPK coverage.
- Terrain-aware analysis requires hash-verified DEM assets, reviewed CRS/vertical datum contracts, and complete azimuth coverage.
- Missing terrain samples remain unknown; they are never replaced with zero or an artificial wall.
- Saved output contains software, kernel, DEM and site provenance. Readiness is not independent scientific validation.
- A flat horizon is labeled approximate; it is not styled or reported as terrain verified.
- `earth_center_clear` means a geometric line-of-sight proxy under the chosen convention; it does not mean a communications link is available.
- Synthetic preview data are UI-only and cannot be exported as scientific results.
