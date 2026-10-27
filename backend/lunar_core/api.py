"""FastAPI entry point for the local-first Lunar South Pole Mission Planner."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from lunar_core import __version__, analysis_service
from lunar_core.analysis_service import (
    AnalysisNotReady,
    TerrainNotReady,
    list_saved_runs,
    load_saved_run,
    run_analysis,
    run_as_csv,
    run_finder,
)
from lunar_core.api_models import AnalysisRequest, FinderRequest
from lunar_core.catalogue import load_default_catalogue
from lunar_core.kernels import preflight_kernel_files
from lunar_core.provenance import sha256_file
from lunar_core.references import load_reference_catalogue
from lunar_core.terrain import dem_coverage_inventory, load_dem_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KERNEL_MANIFEST_PATH = PROJECT_ROOT / "data" / "manifests" / "kernels.json"
DEM_MANIFEST_PATH = PROJECT_ROOT / "data" / "dems" / "manifest.json"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(
    title="Lunar South Pole Mission Planner API",
    version=__version__,
    description=(
        "Auditable lunar south-pole illumination and geometric Earth-visibility analysis. "
        "Results require hash-verified SPICE kernels; terrain-aware results additionally require "
        "complete, verified DEM coverage. Geometric visibility is not a communication link budget."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Any, call_next: Any) -> Any:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # This interface is self-hosted and intentionally uses no third-party JS or remote fonts.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    return response


def _kernel_health() -> dict[str, Any]:
    try:
        report = preflight_kernel_files(KERNEL_MANIFEST_PATH, PROJECT_ROOT)
        return {
            "kernel_manifest_state": report.manifest_state,
            "kernel_manifest_sha256": report.manifest_sha256,
            "kernel_preflight_ready": report.ready_to_load,
            "kernel_count_verified": len(report.verified_kernels),
            "kernel_preflight_issues": list(report.issues),
        }
    except Exception as exc:
        try:
            manifest_hash = sha256_file(KERNEL_MANIFEST_PATH)
        except OSError:
            manifest_hash = None
        return {
            "kernel_manifest_state": "invalid",
            "kernel_manifest_sha256": manifest_hash,
            "kernel_preflight_ready": False,
            "kernel_count_verified": 0,
            "kernel_preflight_issues": [f"{type(exc).__name__}: {exc}"],
        }


def _dem_health() -> dict[str, Any]:
    """Report integrity and datum/CRS preflight, not just whether a DEM manifest exists."""
    try:
        manifest = load_dem_manifest(DEM_MANIFEST_PATH)
        issues: list[str] = []
        if manifest.manifest_state != "configured" or not manifest.assets:
            issues.append("DEM manifest is not configured")
        for asset in manifest.assets:
            if not asset.crs_contract_verified:
                issues.append(f"{asset.asset_id}: CRS contract has not been reviewed")
            if not asset.vertical_datum_verified:
                issues.append(f"{asset.asset_id}: vertical datum has not been reviewed")
            candidate = (PROJECT_ROOT / asset.relative_path)
            try:
                resolved = candidate.resolve(strict=True)
                if not resolved.is_relative_to(PROJECT_ROOT.resolve()) or not resolved.is_file():
                    issues.append(f"{asset.asset_id}: path is outside the project or not a file")
                    continue
                digest = sha256_file(resolved)
                if digest != asset.sha256:
                    issues.append(f"{asset.asset_id}: SHA-256 mismatch")
            except OSError:
                issues.append(f"{asset.asset_id}: file is missing or unreadable")
        return {
            "dem_manifest_state": manifest.manifest_state,
            "dem_manifest_sha256": sha256_file(DEM_MANIFEST_PATH),
            "dem_asset_count": len(manifest.assets),
            "dem_assets_preflight_ready": not issues,
            "dem_preflight_issues": issues,
        }
    except Exception as exc:
        return {"dem_manifest_state": "invalid", "dem_manifest_sha256": None,
                "dem_asset_count": 0, "dem_assets_preflight_ready": False,
                "dem_preflight_issues": [f"{type(exc).__name__}: {exc}"]}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, Any]:
    catalogue = load_default_catalogue()
    refs = load_reference_catalogue()
    spicey_py = importlib.util.find_spec("spiceypy") is not None
    kernel_state = _kernel_health()
    dem_state = _dem_health()
    geometry_ready = spicey_py and bool(kernel_state.get("kernel_preflight_ready"))
    terrain_ready = bool(dem_state.get("dem_assets_preflight_ready"))
    return {
        "status": "ready_for_geometry" if geometry_ready else "configuration_required",
        "api_version": __version__,
        "spiceypy_installed": spicey_py,
        "science_core_ready": geometry_ready,
        "geometry_prerequisites_ready": geometry_ready,
        "science_validation_status": "not_independently_validated",
        "flat_horizon_analysis_ready": geometry_ready,
        "terrain_analysis_ready": geometry_ready and terrain_ready,
        "official_catalogue_state": catalogue.catalogue_state,
        "official_site_count": len(catalogue.sites),
        "reference_site_count": len(refs.sites),
        **kernel_state,
        **dem_state,
        "message": (
            "Geometry requires a working SPICEyPy installation and hash-verified kernels. These prerequisites do not establish scientific validation. "
            "Terrain-aware output additionally requires hash-verified assets, recorded CRS/vertical-datum review, per-site coverage and horizon tests."
        ),
    }


@app.get("/api/sites", tags=["sites"])
def list_sites() -> dict[str, object]:
    """Return official challenge sites only; never contaminate with reference/test points."""
    catalogue = load_default_catalogue()
    return {
        "schema_version": catalogue.schema_version,
        "catalogue_state": catalogue.catalogue_state,
        "site_count": len(catalogue.sites),
        "sites": [site.model_dump(mode="json") for site in catalogue.sites],
        "note": (
            "No official challenge site records have been imported. Use the reference catalogue for exploratory geometry only."
            if catalogue.catalogue_state == "awaiting_official_source" else None
        ),
    }


@app.get("/api/reference-sites", tags=["sites"])
def list_reference_sites() -> dict[str, object]:
    catalogue = load_reference_catalogue()
    return {
        "schema_version": catalogue.schema_version,
        "catalogue_kind": catalogue.catalogue_kind,
        "note": catalogue.note,
        "site_count": len(catalogue.sites),
        "sites": [site.model_dump(mode="json") for site in catalogue.sites],
    }


@app.get("/api/terrain-coverage", tags=["terrain"])
def terrain_coverage() -> dict[str, Any]:
    """Return raster footprints for UI context, explicitly separated from terrain acceptance."""
    return dem_coverage_inventory(DEM_MANIFEST_PATH, PROJECT_ROOT)


@app.get("/api/assumptions", tags=["science"])
def assumptions() -> dict[str, Any]:
    return {
        "time": "Inputs are UTC ISO-8601; geometry and root solving use SPICE ET/TDB; result display converts ET back to UTC through the pinned LSK.",
        "frame": "MOON_ME with DE421-associated orientation as the current PRD contract; frame chain must be documented and validated against the selected kernels.",
        "sun_visibility": "Sun upper limb is visible when elevation + asin(R_sun/r_sun) - local terrain horizon > 0.",
        "earth_visibility": "Earth centre clear is visible when Earth centre elevation - local terrain horizon - user clearance > 0. This is not communication availability.",
        "terrain": "Terrain horizon is the maximum apparent elevation along azimuth rays on a spherical Moon. Any missing/uncovered radial sample makes that azimuth incomplete; no missing value is filled with zero.",
        "events": "Coarse margin sampling, then bisection of every same-sign step whose rate bound (from SPICE azimuth/elevation rates and the local horizon slope) cannot exclude a hidden transition, then SciPy Brent refinement. When rates are available no interval longer than the event tolerance is missed, provided the per-step rate bound holds; sub-tolerance grazes are listed. Each run states whether its discovery was certified.",
        "metrics": "All fractions use the requested interval as denominator and are computed from refined visibility windows. An outage touching an interval edge is a lower bound and marked truncated.",
        "finder": "Windows are computed across the search span extended by the mission duration; candidate windows are clipped to each landing-to-landing+duration interval.",
        "non_claims": [
            "No landing-safety certification, slope/hazard map, thermal model, power/battery sizing, RF link budget, DSN schedule or comms-uptime guarantee.",
            "A flat horizon is an explicitly approximate model and is never presented as terrain-verified.",
            "Published research reference points are not official challenge coordinates or landing ellipses.",
            "Numerical convergence does not quantify physical/model uncertainty."
        ],
    }


@app.get("/api/sources", tags=["provenance"])
def sources() -> dict[str, Any]:
    return {
        "sources": [
            {"name": "NASA Space Apps 2026 — Lunar Landing Site Navigator", "url": "https://www.spaceappschallenge.org/2026/challenges/lunar-landing-site-navigator/", "role": "challenge statement; source-of-truth for official candidate sites and requirements"},
            {"name": "NASA PGDA Product 78", "url": "https://pgda.gsfc.nasa.gov/products/78", "role": "5 m/pixel LOLA site DEMs, uncertainty maps, and 100 terrain clones; MOON_ME / DE421"},
            {"name": "NASA PGDA Product 90", "url": "https://pgda.gsfc.nasa.gov/products/90", "role": "regional multi-resolution LOLA COG terrain data"},
            {"name": "NASA PGDA Product 104", "url": "https://pgda.gsfc.nasa.gov/products/104", "role": "supplemental 5 m/pixel shape-from-shading DEMs for 13 earlier Artemis III candidate regions; footprint and datum validation required, not the official 2026 challenge catalogue"},
            {"name": "Zhong et al. (2026), DEM-resolution illumination bias", "url": "https://doi.org/10.3847/1538-3881/ae6918", "role": "method caution: a Chang’e-7 region study reports cumulative relative illumination bias of 27.5% at 5 m and 65.1% at 20 m versus a 1 m baseline; site- and method-specific result, not a universal correction factor"},
            {"name": "NASA PGDA Product 69", "url": "https://pgda.gsfc.nasa.gov/products/69", "role": "long-term illumination sanity-check overlays only"},
            {"name": "NAIF SPICE azlcpo_c documentation", "url": "https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/azlcpo_c.html", "role": "topocentric azimuth/elevation and light-time calculation interface"},
            {"name": "NAIF SPICE pckcov_c documentation", "url": "https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/pckcov_c.html", "role": "binary-PCK frame orientation coverage preflight"},
            {"name": "JPL Horizons API documentation", "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html", "role": "independent ephemeris reference; golden comparison still must be run"},
            {"name": "NASA Science — Malapert region", "url": "https://science.nasa.gov/image-detail/20100618/", "role": "published Malapert reference coordinate; not official challenge site record"},
            {"name": "Sverdrup-Henson lunar south-pole settlement study", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10518707/", "role": "published crater reference coordinates; not landing ellipses"},
            {"name": "Distribution and Accessibility of Geologic Targets near the Lunar South Pole", "url": "https://doi.org/10.3847/psj/aca590", "role": "LOLA Site 001/004 coordinate references"},
        ]
    }


@app.post("/api/analysis", tags=["analysis"])
def analysis(request: AnalysisRequest) -> dict[str, Any]:
    try:
        return run_analysis(request)
    except TerrainNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnalysisNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"Analysis rejected: {type(exc).__name__}: {exc}") from exc


@app.post("/api/finder", tags=["analysis"])
def finder(request: FinderRequest) -> dict[str, Any]:
    try:
        return run_finder(request)
    except TerrainNotReady as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AnalysisNotReady as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=f"Finder rejected: {type(exc).__name__}: {exc}") from exc


@app.get("/api/runs", tags=["export"])
def saved_runs(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    """List persisted analysis/finder runs for loading an offline demo scenario."""
    try:
        return list_saved_runs(limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}", tags=["export"])
def saved_run(run_id: str) -> dict[str, Any]:
    try:
        return load_saved_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/export.json", tags=["export"])
def export_json(run_id: str) -> FileResponse:
    try:
        payload = load_saved_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    path = analysis_service.RUNS_DIR / f"{payload['run_id']}.json"
    return FileResponse(path, media_type="application/json", filename=f"lunar-run-{run_id}.json")


@app.get("/api/runs/{run_id}/export.csv", tags=["export"])
def export_csv(run_id: str) -> PlainTextResponse:
    try:
        payload = load_saved_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(
        run_as_csv(payload),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="lunar-run-{run_id}.csv"'},
    )
