"""Terrain-uncertainty ensemble: rerun one site on PGDA error clones of its 5 m DEM.

PGDA Product 78 publishes 100 "clones" per site: complete 5 m surfaces equal to the nominal
surface plus a realisation of its height error. A check on Site04 clone 0001 (2026-10-28)
found clone - surface has mean 0.001 m, std 0.467 m, and (clone - surface) / TOTERR has std
0.998 over the whole tile, so the clones carry the published uncertainty with its spatial
correlation. Rerunning the unchanged pipeline on N clones gives N plausible values of each
metric, which is a sample of the result's spread under the DEM error model.

Limits, recorded in every output:
* only the overridden asset (the 5 m tile) is perturbed; the 240 m regional DEM is nominal;
* N clones estimate the spread coarsely (with N = 10 the min/max are not tail bounds);
* the observer coordinate is fixed: position uncertainty is the location scan's job.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lunar_core import __version__
from lunar_core.api_models import AnalysisRequest
from lunar_core.location_scan import (
    GridOffset,
    offset_point,
    prepare_run_context,
    save_json_atomic,
    summarise,
)

ENSEMBLE_SCHEMA_VERSION = "1.0"
MAX_MEMBERS = 100
METRICS = ("sunlit_percent", "dte_clear_percent", "both_percent")


def _member_record(label: str, path: str | None, result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    precision = result["event_precision"]
    terrain = result["terrain"]
    overrides = terrain.get("asset_overrides") or []
    return {
        "member": label,
        "clone_path": path,
        "clone_sha256": overrides[0]["override_sha256"] if overrides else None,
        "status": "ok",
        "ground_elevation_m": terrain.get("site_ground_elevation_m"),
        "sunlit_percent": metrics["sunlit_percent"],
        "dte_clear_percent": metrics["dte_clear_percent"],
        "both_percent": metrics["both_percent"],
        "longest_darkness_h": metrics["longest_darkness"]["duration_s"] / 3600.0,
        "longest_dte_gap_h": metrics["longest_dte_gap"]["duration_s"] / 3600.0,
        "discovery_certified": precision["discovery_certified"],
    }


def run_terrain_ensemble(
    site_id: str,
    request: AnalysisRequest,
    *,
    asset_id: str,
    clone_paths: Sequence[Path],
    offset: GridOffset | None = None,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
    save: bool = True,
) -> dict[str, Any]:
    """Nominal run plus one run per clone of ``asset_id`` at the site (optionally offset)."""
    from lunar_core import analysis_service as svc

    if request.horizon_mode != "terrain":
        raise ValueError("terrain ensemble requires horizon_mode='terrain'")
    clones = [Path(p) for p in clone_paths]
    if not clones:
        raise ValueError("at least one clone raster is required")
    if len(clones) > MAX_MEMBERS:
        raise ValueError(f"at most {MAX_MEMBERS} clones per ensemble")
    if len({p.resolve() for p in clones}) != len(clones):
        raise ValueError("duplicate clone paths")
    offset = offset or GridOffset(0.0, 0.0)

    with svc._RUN_LOCK:
        sites = svc._load_sites()
        if site_id not in sites:
            raise svc.AnalysisNotReady(f"Unknown site ID: {site_id}")
        base = sites[site_id]
        if base.get("latitude_deg") is None or base.get("longitude_deg") is None:
            raise svc.AnalysisNotReady(f"Site {site_id} has no verified coordinates")
        ctx = prepare_run_context(request)
        lat, lon = offset_point(
            float(base["latitude_deg"]), float(base["longitude_deg"]), offset, ctx.geometry.reference_radius_m,
        )
        site = {**base, "latitude_deg": lat, "longitude_deg": lon}

        def run(overrides: dict[str, Path] | None) -> dict[str, Any]:
            result, _windows = svc._run_one_site(
                site, request, ctx.geometry, start_et=ctx.start_et, end_et=ctx.end_et,
                run_step_s=ctx.step_s, asset_overrides=overrides,
            )
            return result

        started = time.perf_counter()
        nominal = _member_record("nominal", None, run(None))
        if progress is not None:
            progress(0, len(clones), nominal)
        members: list[dict[str, Any]] = []
        for index, clone in enumerate(clones):
            try:
                record = _member_record(f"clone-{index + 1:03d}", str(clone), run({asset_id: clone}))
            except svc.AnalysisNotReady as exc:
                record = {"member": f"clone-{index + 1:03d}", "clone_path": str(clone),
                          "status": "unavailable", "error": str(exc)}
            members.append(record)
            if progress is not None:
                progress(index + 1, len(clones), record)
        elapsed = time.perf_counter() - started

    ok = [m for m in members if m["status"] == "ok"]
    summary: dict[str, Any] = {}
    for name in (*METRICS, "longest_darkness_h", "longest_dte_gap_h", "ground_elevation_m"):
        values = [float(m[name]) for m in ok]
        entry: dict[str, Any] = summarise(values)
        entry["nominal"] = nominal[name]
        entry["fraction_of_clones_above_nominal"] = (
            sum(v > nominal[name] for v in values) / len(values) if values else None
        )
        summary[name] = entry
    for name in METRICS:
        values = [float(m[name]) for m in ok]
        summary[name]["fraction_of_clones_nonzero"] = (
            sum(v > 0.0 for v in values) / len(values) if values else None
        )
        summary[name]["max_abs_change_vs_nominal"] = (
            max(abs(v - nominal[name]) for v in values) if values else None
        )

    payload: dict[str, Any] = {
        "schema_version": ENSEMBLE_SCHEMA_VERSION,
        "ensemble_id": str(uuid.uuid4()),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "analysis_kind": "terrain_uncertainty_ensemble",
        "application": {"name": "Lunar South Pole Mission Planner", "version": __version__},
        "site": {
            "site_id": site_id, "name": base.get("name"),
            "published_latitude_deg": base["latitude_deg"], "published_longitude_deg": base["longitude_deg"],
            "offset_east_m": offset.east_m, "offset_north_m": offset.north_m,
            "latitude_deg": lat, "longitude_deg": lon,
        },
        "perturbed_asset_id": asset_id,
        "member_count": len(clones),
        "members_ok": len(ok),
        "all_certified": bool(ok) and bool(nominal["discovery_certified"]) and all(
            m["discovery_certified"] for m in ok
        ),
        "settings": {
            "start_utc": ctx.start_utc, "end_utc": ctx.end_utc,
            "coarse_step_min": request.coarse_step_min, "event_tolerance_s": request.event_tolerance_s,
            "sun_observer_height_m": request.sun_observer_height_m,
            "antenna_height_m": request.antenna_height_m,
            "earth_min_clearance_deg": request.earth_min_clearance_deg,
            "terrain_azimuth_step_deg": request.terrain_azimuth_step_deg,
            "terrain_max_range_m": request.terrain_max_range_m,
            "terrain_near_range_m": request.terrain_near_range_m,
            "terrain_near_step_m": request.terrain_near_step_m,
            "terrain_far_step_m": request.terrain_far_step_m,
        },
        "nominal": nominal,
        "summary": summary,
        "limits": [
            f"Only {asset_id} is perturbed; other DEM assets (e.g. the 240 m regional map) stay nominal.",
            f"{len(ok)} clones give a coarse sample of the spread; min/max are not tail bounds.",
            "Observer position is fixed; horizontal position uncertainty is covered by the location scan.",
            "Clones represent PGDA's published error model, which this project has not independently verified.",
        ],
        "elapsed_s": elapsed,
        "provenance": ctx.provenance(),
        "members": members,
    }
    if save:
        save_json_atomic(payload, svc.PROJECT_ROOT / "data" / "ensembles", f"{payload['ensemble_id']}.json")
    return payload
