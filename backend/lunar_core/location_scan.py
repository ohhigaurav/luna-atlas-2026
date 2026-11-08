"""Location sensitivity: how much do a site's results change within a few hundred metres?

A literature coordinate rounded to 0.01 deg is uncertain by ~150-300 m, and landers come down
in an ellipse, not on a point. The first real-terrain runs showed that a single coordinate can
sit in a ~200 m depression (0 % sunlit) while the surrounding rim is well lit. This module
re-runs the unchanged production pipeline (terrain horizon -> SPICE geometry -> certified events
-> metrics) at every point of a regular grid around a site and reports the distribution.

Nothing here alters the science: each grid point is analysed exactly as a catalogue site would
be, with its own DEM ground height, its own horizon and its own Sun/Earth directions (near the
pole, moving 300 m rotates the local azimuth frame by up to ~1 deg, so directions are not
shared between points).
"""
from __future__ import annotations

import json
import math
import os
import platform
import statistics
import tempfile
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lunar_core import __version__
from lunar_core.api_models import AnalysisRequest
from lunar_core.provenance import sha256_file

SCAN_SCHEMA_VERSION = "1.0"
MAX_SCAN_POINTS = 400
SUMMARY_METRICS = ("sunlit_percent", "dte_clear_percent", "both_percent")


@dataclass(frozen=True, slots=True)
class GridOffset:
    east_m: float
    north_m: float

    @property
    def distance_m(self) -> float:
        return math.hypot(self.east_m, self.north_m)

    @property
    def azimuth_deg(self) -> float:
        """Bearing clockwise from local north (0 for the centre point)."""
        if self.distance_m == 0.0:
            return 0.0
        return math.degrees(math.atan2(self.east_m, self.north_m)) % 360.0


def scan_offsets(radius_m: float, spacing_m: float) -> list[GridOffset]:
    """Square grid of local east/north offsets inside a disc, centre first.

    The grid is aligned with the site's local north/east and includes (0, 0). Points with
    distance <= radius (plus 1 mm for floating-point slack) are kept.
    """
    if not (math.isfinite(radius_m) and math.isfinite(spacing_m)):
        raise ValueError("radius and spacing must be finite")
    if radius_m < 0 or spacing_m <= 0:
        raise ValueError("radius must be >= 0 and spacing > 0")
    n = int(math.floor(radius_m / spacing_m + 1e-9))
    offsets = [
        GridOffset(i * spacing_m, j * spacing_m)
        for j in range(n, -n - 1, -1)
        for i in range(-n, n + 1)
        if math.hypot(i * spacing_m, j * spacing_m) <= radius_m + 1e-3
    ]
    if len(offsets) > MAX_SCAN_POINTS:
        raise ValueError(f"scan would evaluate {len(offsets)} points (cap {MAX_SCAN_POINTS}); increase spacing")
    offsets.sort(key=lambda o: (o.distance_m != 0.0,))
    return offsets


def offset_point(
    latitude_deg: float, longitude_deg: float, offset: GridOffset, body_radius_m: float,
) -> tuple[float, float]:
    """Latitude/longitude reached by a spherical geodesic of the offset's length and bearing."""
    from lunar_core.terrain import _ray_latlon_grid

    if offset.distance_m == 0.0:
        return latitude_deg, longitude_deg
    lat, lon = _ray_latlon_grid(
        latitude_deg, longitude_deg, [offset.azimuth_deg], [offset.distance_m], body_radius_m,
    )
    return float(lat[0]), float(lon[0])


def summarise(values: Sequence[float]) -> dict[str, float | int | None]:
    """Min / quartiles / median / max of finite values (inclusive quartile method)."""
    finite = sorted(v for v in values if math.isfinite(v))
    if not finite:
        return {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    if len(finite) == 1:
        q1 = q3 = finite[0]
    else:
        q1, _q2, q3 = statistics.quantiles(finite, n=4, method="inclusive")
    return {
        "n": len(finite), "min": finite[0], "p25": q1, "median": statistics.median(finite),
        "p75": q3, "max": finite[-1],
    }


def centre_rank(values: Sequence[float], centre: float) -> float | None:
    """Fraction of grid points whose value is strictly below the centre point's value."""
    finite = [v for v in values if math.isfinite(v)]
    if not finite or not math.isfinite(centre):
        return None
    return sum(v < centre for v in finite) / len(finite)


def _point_record(offset: GridOffset, lat: float, lon: float, result: dict[str, Any]) -> dict[str, Any]:
    metrics = result["metrics"]
    precision = result["event_precision"]
    profile = [b["elevation_deg"] for b in result["horizon_profile"] if b["elevation_deg"] is not None]
    return {
        "east_m": offset.east_m, "north_m": offset.north_m, "distance_m": offset.distance_m,
        "latitude_deg": lat, "longitude_deg": lon,
        "status": "ok",
        "ground_elevation_m": result["terrain"].get("site_ground_elevation_m"),
        "sunlit_percent": metrics["sunlit_percent"],
        "dte_clear_percent": metrics["dte_clear_percent"],
        "both_percent": metrics["both_percent"],
        "longest_darkness_h": metrics["longest_darkness"]["duration_s"] / 3600.0,
        "longest_darkness_truncated": bool(metrics["longest_darkness"]["display_prefix"]),
        "longest_dte_gap_h": metrics["longest_dte_gap"]["duration_s"] / 3600.0,
        "longest_dte_gap_truncated": bool(metrics["longest_dte_gap"]["display_prefix"]),
        "horizon_max_deg": max(profile) if profile else None,
        "discovery_certified": precision["discovery_certified"],
        "possible_grazes": len(precision["sun_possible_grazing"]) + len(precision["earth_possible_grazing"]),
        "horizon_cache_hit": result["terrain"].get("cache_hit"),
    }


@dataclass(frozen=True)
class RunContext:
    """SPICE runtime, interval and provenance shared by every point of a scan or ensemble."""

    geometry: Any
    start_utc: str
    end_utc: str
    start_et: float
    end_et: float
    step_s: float
    kernel_manifest_sha256: str
    loaded_kernels: list[dict[str, Any]]
    spk_coverage: Any
    bpc_coverage: Any

    def provenance(self) -> dict[str, Any]:
        from lunar_core import analysis_service as svc

        return {
            "software_version": __version__,
            "python_version": platform.python_version(),
            "git_commit": svc._git_commit(),
            "kernel_manifest_sha256": self.kernel_manifest_sha256,
            "loaded_kernels": self.loaded_kernels,
            "spk_coverage_preflight": self.spk_coverage,
            "bpc_coverage_preflight": self.bpc_coverage,
            "dem_manifest_sha256": sha256_file(svc.DEM_MANIFEST),
            "spice_frame": self.geometry.frame,
            "aberration_correction": self.geometry.aberration_correction,
            "moon_reference_radius_m": self.geometry.reference_radius_m,
        }


def prepare_run_context(request: AnalysisRequest) -> RunContext:
    """Kernels, UTC->ET and coverage preflight exactly as a normal analysis run does them.

    Call with ``analysis_service._RUN_LOCK`` held.
    """
    from lunar_core import analysis_service as svc

    spice, geometry, kernel_manifest_hash, loaded_kernels = svc._spice_runtime()
    start_utc, end_utc = svc._iso_utc(request.start_utc), svc._iso_utc(request.end_utc)
    start_et, end_et = geometry.utc_to_et(start_utc), geometry.utc_to_et(end_utc)
    if end_et <= start_et:
        raise svc.AnalysisNotReady("SPICE converted end epoch is not after start epoch")
    spk_coverage, bpc_coverage = svc.coverage_preflight(spice, loaded_kernels, start_et, end_et, geometry.frame)
    return RunContext(
        geometry=geometry, start_utc=start_utc, end_utc=end_utc, start_et=start_et, end_et=end_et,
        step_s=float(request.coarse_step_min * 60), kernel_manifest_sha256=kernel_manifest_hash,
        loaded_kernels=loaded_kernels, spk_coverage=spk_coverage, bpc_coverage=bpc_coverage,
    )


def save_json_atomic(payload: dict[str, Any], directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    fd, temp_name = tempfile.mkstemp(prefix=".tmp.", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return target


SCAN_YIELD_S = 0.05  # pause between points so other requests can take _RUN_LOCK (see run_location_scan)


def _pool_key(svc: Any) -> Any:
    """Identity of the furnished kernel pool (manifest hash + kernel hashes), or None."""
    loaded = svc._LOADED_KERNELS
    return None if loaded is None else loaded[0]


def run_location_scan(
    site_id: str,
    request: AnalysisRequest,
    *,
    radius_m: float = 300.0,
    spacing_m: float = 100.0,
    progress: Callable[[int, int, dict[str, Any]], None] | None = None,
    save: bool = True,
    offsets: Sequence[GridOffset] | None = None,
    grid_description: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyse every grid point around ``site_id`` with the production pipeline.

    ``request.site_ids`` is ignored; all other settings (interval, step, heights, clearance,
    terrain sampling) apply to every point. ``request.horizon_mode`` must be "terrain": on a
    flat sphere the scan is meaningless. A point whose terrain is unavailable is recorded with
    its error and excluded from the summary; it never aborts the scan.
    """
    from lunar_core import analysis_service as svc

    if request.horizon_mode != "terrain":
        raise ValueError("location scan requires horizon_mode='terrain'")
    if offsets is None:
        offsets = scan_offsets(radius_m, spacing_m)
    elif not offsets or len(offsets) > MAX_SCAN_POINTS:
        raise ValueError(f"offsets must hold 1 to {MAX_SCAN_POINTS} points")
    # The lock is taken per point, not for the whole scan: a 45-point ellipse takes 4-5 minutes, and
    # holding _RUN_LOCK that long froze every other user's new question on a shared server. Each point
    # is an independent production analysis, so only the kernel pool must stay the same throughout;
    # the scan stops if it changes. threading.Lock is not fair, so the scan pauses briefly between
    # points to let a waiting request take the lock.
    with svc._RUN_LOCK:
        sites = svc._load_sites()
        if site_id not in sites:
            raise svc.AnalysisNotReady(f"Unknown site ID: {site_id}")
        base = sites[site_id]
        if base.get("latitude_deg") is None or base.get("longitude_deg") is None:
            raise svc.AnalysisNotReady(f"Site {site_id} has no verified coordinates")
        ctx = prepare_run_context(request)
        pool = _pool_key(svc)
    geometry, start_et, end_et, step_s = ctx.geometry, ctx.start_et, ctx.end_et, ctx.step_s
    start_utc, end_utc = ctx.start_utc, ctx.end_utc
    base_lat, base_lon = float(base["latitude_deg"]), float(base["longitude_deg"])

    points: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, offset in enumerate(offsets):
        if index:
            time.sleep(SCAN_YIELD_S)
        lat, lon = offset_point(base_lat, base_lon, offset, geometry.reference_radius_m)
        # Same site_id: DEM asset selection is per site, and every point lies inside the
        # site's tiles. Only the coordinate changes.
        point_site = {**base, "latitude_deg": lat, "longitude_deg": lon}
        with svc._RUN_LOCK:
            if _pool_key(svc) != pool:
                raise svc.AnalysisNotReady("the SPICE kernel pool changed during the scan; ask again")
            try:
                result, _windows = svc._run_one_site(
                    point_site, request, geometry, start_et=start_et, end_et=end_et, run_step_s=step_s,
                )
                record = _point_record(offset, lat, lon, result)
            except svc.AnalysisNotReady as exc:
                record = {
                    "east_m": offset.east_m, "north_m": offset.north_m, "distance_m": offset.distance_m,
                    "latitude_deg": lat, "longitude_deg": lon, "status": "unavailable", "error": str(exc),
                }
        points.append(record)
        if progress is not None:
            progress(index + 1, len(offsets), record)
    elapsed = time.perf_counter() - started

    ok = [p for p in points if p["status"] == "ok"]
    centre = points[0] if points and points[0]["distance_m"] == 0.0 else None
    summary: dict[str, Any] = {}
    for name in (*SUMMARY_METRICS, "longest_darkness_h", "longest_dte_gap_h", "ground_elevation_m"):
        values = [float(p[name]) for p in ok]
        entry: dict[str, Any] = summarise(values)
        if centre is not None and centre["status"] == "ok":
            entry["centre"] = centre[name]
            entry["fraction_of_points_below_centre"] = centre_rank(values, float(centre[name]))
        summary[name] = entry

    payload: dict[str, Any] = {
        "schema_version": SCAN_SCHEMA_VERSION,
        "scan_id": str(uuid.uuid4()),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "analysis_kind": "location_sensitivity_scan",
        "application": {"name": "Lunar South Pole Mission Planner", "version": __version__},
        "site": {
            "site_id": site_id, "name": base.get("name"),
            "latitude_deg": base_lat, "longitude_deg": base_lon,
            "catalogue_kind": base.get("catalogue_kind"), "source_url": base.get("source_url"),
        },
        "grid": grid_description or {
            "radius_m": radius_m, "spacing_m": spacing_m, "point_count": len(offsets),
            "layout": "square grid in local east/north, clipped to a disc; spherical geodesic offsets",
        },
        "settings": {
            "start_utc": start_utc, "end_utc": end_utc,
            "coarse_step_min": request.coarse_step_min,
            "event_tolerance_s": request.event_tolerance_s,
            "sun_observer_height_m": request.sun_observer_height_m,
            "antenna_height_m": request.antenna_height_m,
            "earth_min_clearance_deg": request.earth_min_clearance_deg,
            "horizon_mode": request.horizon_mode,
            "terrain_azimuth_step_deg": request.terrain_azimuth_step_deg,
            "terrain_max_range_m": request.terrain_max_range_m,
            "terrain_near_range_m": request.terrain_near_range_m,
            "terrain_near_step_m": request.terrain_near_step_m,
            "terrain_far_step_m": request.terrain_far_step_m,
        },
        "summary": summary,
        "points_ok": len(ok),
        "points_unavailable": len(points) - len(ok),
        "all_certified": all(p["discovery_certified"] for p in ok) if ok else False,
        "elapsed_s": elapsed,
        "interpretation": (
            "Each point is a full production analysis at that coordinate. The spread shows how much "
            "the result depends on exact placement; it is not a probability distribution over a "
            "landing ellipse unless the grid covers that ellipse."
        ),
        "provenance": ctx.provenance(),
        "points": points,
    }
    if save:
        _save_scan(payload, svc.PROJECT_ROOT / "data" / "scans")
    return payload


def _save_scan(payload: dict[str, Any], directory: Path) -> Path:
    return save_json_atomic(payload, directory, f"{payload['scan_id']}.json")
