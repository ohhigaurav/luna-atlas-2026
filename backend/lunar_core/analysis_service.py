"""End-to-end analysis orchestration shared by API and CLI.

This layer owns orchestration, not scientific definitions: geometry comes from SPICE, terrain
from the hash-verified DEM adapter, windows from ``events``, and metrics from ``metrics``. The UI
never computes ephemerides or outage metrics.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import tempfile
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lunar_core import __version__
from lunar_core.api_models import AnalysisRequest, FinderRequest
from lunar_core.bpc_coverage import BPCoverageError, assert_required_bpc_coverage
from lunar_core.catalogue import load_default_catalogue
from lunar_core.events import VisibilityWindow, find_visibility_windows
from lunar_core.finder import (
    MissionProfile,
    SiteVisibilityWindows,
    evaluate_finder_grid,
)
from lunar_core.geometry import ObserverSite, SpiceGeometry, TargetDirection
from lunar_core.horizon import (
    TerrainHorizon,
    flat_horizon_elevation_rad,
    horizon_slope_bound_rad_per_deg,
    interpolate_horizon,
)
from lunar_core.kernels import (
    KernelLoadReport,
    load_kernel_manifest,
    load_verified_kernels,
    preflight_kernel_files,
)
from lunar_core.metrics import AnalysisMetrics, compute_metrics
from lunar_core.provenance import sha256_file
from lunar_core.spk_coverage import SPKCoverageError, assert_required_spk_coverage
from lunar_core.references import load_reference_catalogue
from lunar_core.visibility import earth_centre_clear_margin_rad, sun_upper_limb_margin_rad

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KERNEL_MANIFEST = PROJECT_ROOT / "data" / "manifests" / "kernels.json"
DEM_MANIFEST = PROJECT_ROOT / "data" / "dems" / "manifest.json"
RUNS_DIR = PROJECT_ROOT / "data" / "runs"
MOON_ME_RADIUS_M_DEFAULT = 1_737_400.0
SUN_RADIUS_M = 695_700_000.0
EARTH_RADIUS_M = 6_378_136.6
# Multiplier on the sample-derived angular-rate bound used for certified event discovery.
RATE_BOUND_SAFETY = 1.5
# Covers the Sun's semidiameter drift and floating-point noise (rad/s); |d(rho)/dt| ~ 1e-11.
RATE_BOUND_FLOOR_RAD_S = 1e-10


class AnalysisNotReady(RuntimeError):
    """A required real input or validation dependency is missing."""


class TerrainNotReady(AnalysisNotReady):
    """Terrain-aware analysis cannot be supported for the requested site/settings."""


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="auto").replace("+00:00", "Z")


def _window_payload(window: VisibilityWindow, geometry: SpiceGeometry) -> dict[str, Any]:
    return {
        "start_utc": geometry.et_to_utc(window.start_s),
        "end_utc": geometry.et_to_utc(window.end_s),
        "start_et_s": window.start_s,
        "end_et_s": window.end_s,
        "duration_s": window.duration_s,
        "start_truncated": window.start_truncated,
        "end_truncated": window.end_truncated,
        "start_residual_rad": window.start_residual,
        "end_residual_rad": window.end_residual,
        "start_method": window.start_method,
        "end_method": window.end_method,
    }


def _root_payload(root: Any, geometry: SpiceGeometry) -> dict[str, Any]:
    return {
        "utc": geometry.et_to_utc(root.time_s),
        "et_s": root.time_s,
        "residual_rad": root.residual,
        "method": root.method,
        "is_crossing": root.crossing,
        "visible_before": root.visible_before,
        "visible_after": root.visible_after,
    }


def _metrics_payload(metrics: AnalysisMetrics) -> dict[str, Any]:
    payload = asdict(metrics)
    payload["sunlit_percent"] = metrics.sunlit_fraction * 100.0
    payload["dte_clear_percent"] = metrics.dte_clear_fraction * 100.0
    payload["both_percent"] = metrics.both_fraction * 100.0
    payload["joint_outage_percent"] = metrics.joint_outage_fraction * 100.0
    for name in ("longest_darkness", "longest_dte_gap", "longest_joint_outage"):
        item = payload[name]
        item["display_prefix"] = ">=" if item["truncated_start"] or item["truncated_end"] else ""
    return payload


def _load_sites() -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    official = load_default_catalogue()
    for site in official.sites:
        records[site.site_id] = {**site.model_dump(mode="json"), "catalogue_kind": "official_challenge"}
    reference_catalogue = load_reference_catalogue()
    for site in reference_catalogue.sites:
        records[site.site_id] = {
            **site.model_dump(mode="json"),
            "origin": "reference",
            "catalogue_kind": "literature_reference_points",
            "source_status": "public_reference_not_official_challenge_site",
        }
    return records


# One analysis/finder run at a time. CSPICE calls are already serialised by SPICE_LOCK, so
# parallel runs would gain nothing; serialising whole runs guarantees the kernel pool cannot be
# reloaded underneath a run that is still evaluating geometry.
_RUN_LOCK = threading.Lock()
# (manifest sha256, ((kernel_id, sha256), ...)) of the pool currently furnished, plus its report.
_LOADED_KERNELS: tuple[tuple[str, tuple[tuple[str, str], ...]], KernelLoadReport] | None = None


def _ensure_kernels_loaded(spiceypy: Any) -> KernelLoadReport:
    """Furnish the verified kernel set once per process; reload only if its bytes changed.

    Preflight re-hashes every file on each call (cheap next to an analysis), so a modified or
    replaced kernel is still detected. Only an unchanged, already-furnished set is reused.
    """
    global _LOADED_KERNELS
    preflight = preflight_kernel_files(KERNEL_MANIFEST, PROJECT_ROOT)
    if not preflight.ready_to_load:
        detail = "; ".join(preflight.issues) or "kernel manifest is not configured"
        raise AnalysisNotReady(f"SPICE kernel preflight failed: {detail}")
    key = (
        preflight.manifest_sha256,
        tuple((item.asset.kernel_id, item.actual_sha256) for item in preflight.verified_kernels),
    )
    if _LOADED_KERNELS is not None and _LOADED_KERNELS[0] == key:
        return _LOADED_KERNELS[1]
    _LOADED_KERNELS = None
    report = load_verified_kernels(KERNEL_MANIFEST, PROJECT_ROOT, spiceypy)
    _LOADED_KERNELS = (key, report)
    return report


def _spice_runtime() -> tuple[Any, SpiceGeometry, str, list[dict[str, Any]]]:
    try:
        import spiceypy
    except ImportError as exc:
        raise AnalysisNotReady(
            "SpiceyPy is not installed. Install the locked project environment before running real analysis."
        ) from exc
    try:
        load_report = _ensure_kernels_loaded(spiceypy)
        geometry = SpiceGeometry.from_spiceypy(
            frame="MOON_ME",
            observer_center="MOON",
            aberration_correction="LT+S",
        )
    except AnalysisNotReady:
        raise
    except Exception as exc:
        raise AnalysisNotReady(f"SPICE kernel/geometry initialisation failed: {type(exc).__name__}: {exc}") from exc
    manifest = load_kernel_manifest(KERNEL_MANIFEST)
    asset_by_id = {asset.kernel_id: asset for asset in manifest.kernels}
    hashes = [
        {
            "kernel_id": kernel_id, "path": path, "sha256": digest,
            "kernel_type": asset_by_id[kernel_id].kernel_type,
            "coverage_frame": asset_by_id[kernel_id].coverage_frame,
            "size_bytes": asset_by_id[kernel_id].size_bytes,
        }
        for kernel_id, path, digest in zip(
            load_report.loaded_kernel_ids, load_report.loaded_paths,
            [digest for _kernel_id, digest in load_report.kernel_hashes], strict=True,
        )
    ]
    return spiceypy, geometry, load_report.manifest_sha256, hashes


def _build_site_horizon(
    site: dict[str, Any],
    geometry: SpiceGeometry,
    request: AnalysisRequest | FinderRequest,
) -> tuple[float, TerrainHorizon | None, TerrainHorizon | None, dict[str, Any], str]:
    mode = request.horizon_mode
    if mode == "flat":
        # The representative points currently lack verified site ground elevation. The flat
        # model therefore uses the declared reference sphere and height above that sphere.
        metadata = {
            "mode": "flat", "terrain_status": "flat",
            "reference_radius_m": geometry.reference_radius_m,
            "site_ground_elevation_m": 0.0,
            "sun_observer_height_m": request.sun_observer_height_m,
            "antenna_height_m": request.antenna_height_m,
            "note": "Flat spherical horizon; terrain occlusion is not represented.",
        }
        return 0.0, None, None, metadata, "flat"

    from lunar_core.terrain import DEMManifestError, build_cached_horizon_from_dem_assets
    try:
        sun_horizon, ground_elevation, metadata = build_cached_horizon_from_dem_assets(
            site_id=site["site_id"],
            latitude_deg=float(site["latitude_deg"]),
            longitude_deg=float(site["longitude_deg"]),
            observer_height_m=request.sun_observer_height_m,
            reference_radius_m=geometry.reference_radius_m,
            max_range_m=request.terrain_max_range_m,
            azimuth_step_deg=request.terrain_azimuth_step_deg,
            near_range_m=request.terrain_near_range_m,
            near_step_m=request.terrain_near_step_m,
            far_step_m=request.terrain_far_step_m,
            manifest_path=DEM_MANIFEST, project_root=PROJECT_ROOT,
        )
        if math.isclose(request.sun_observer_height_m, request.antenna_height_m, abs_tol=1e-12):
            earth_horizon = sun_horizon
        else:
            earth_horizon, earth_ground_elevation, earth_metadata = build_cached_horizon_from_dem_assets(
                site_id=site["site_id"],
                latitude_deg=float(site["latitude_deg"]),
                longitude_deg=float(site["longitude_deg"]),
                observer_height_m=request.antenna_height_m,
                reference_radius_m=geometry.reference_radius_m,
                max_range_m=request.terrain_max_range_m,
                azimuth_step_deg=request.terrain_azimuth_step_deg,
                near_range_m=request.terrain_near_range_m,
                near_step_m=request.terrain_near_step_m,
                far_step_m=request.terrain_far_step_m,
                manifest_path=DEM_MANIFEST, project_root=PROJECT_ROOT,
            )
            if not math.isclose(ground_elevation, earth_ground_elevation, abs_tol=1e-6):
                raise DEMManifestError("Sun and antenna DEM ground elevations disagree")
            metadata["antenna_horizon_manifest_sha256"] = earth_metadata["manifest_sha256"]
            metadata["antenna_horizon_observer_height_m"] = request.antenna_height_m
    except (DEMManifestError, ValueError) as exc:
        raise TerrainNotReady(f"Terrain horizon unavailable for {site['site_id']}: {exc}") from exc
    for label, horizon in (("Sun", sun_horizon), ("antenna", earth_horizon)):
        incomplete = [bin_.azimuth_deg for bin_ in horizon.bins if bin_.coverage_status != "complete"]
        if incomplete:
            raise TerrainNotReady(
                f"Terrain horizon for {site['site_id']} ({label}) has {len(incomplete)}/{len(horizon.bins)} "
                "incomplete azimuth bins; metrics are suppressed until coverage is complete."
            )
    metadata.update({"mode": "terrain", "terrain_status": "verified"})
    return ground_elevation, sun_horizon, earth_horizon, metadata, "terrain-verified"


def _horizon_at(
    mode: str,
    flat_horizon_rad: float,
    terrain_horizon: TerrainHorizon | None,
    azimuth_deg: float,
) -> tuple[float, bool]:
    if mode == "flat":
        return flat_horizon_rad, True
    if terrain_horizon is None:
        raise TerrainNotReady("terrain mode selected without a horizon model")
    result = interpolate_horizon(terrain_horizon, azimuth_deg)
    if result.elevation_rad is None or not result.coverage_complete:
        raise TerrainNotReady(f"Terrain horizon incomplete at azimuth {azimuth_deg:.3f} deg")
    return result.elevation_rad, True


def _make_rate_bound(
    direction: Any,
    target: str,
    height_m: float,
    mode: str,
    terrain_horizon: TerrainHorizon | None,
) -> Any:
    """Build L(a, b) >= max |d(margin)/dt| on [a, b] from SPICE angular rates.

    margin = e(t) + const(t) - H(az(t)), so |dg/dt| <= |de/dt| + |dH/daz| |daz/dt| (+ the Sun
    semidiameter drift, covered by the floor). The angular rates inside [a, b] are bounded by the
    larger endpoint rate plus the endpoint change, times ``RATE_BOUND_SAFETY``. That assumes the
    rates do not swing more inside one step than between its endpoints; for the Sun and Earth
    seen from the Moon the rates change on a days-long scale, far slower than the coarse step.
    Returns ``None`` if the geometry did not supply rates (then discovery is not certified).
    """
    def rates(et: float) -> tuple[float, float, float] | None:
        item = direction(et, target, height_m)
        if item.azimuth_rate_rad_s is None or item.elevation_rate_rad_s is None:
            return None
        return item.azimuth_deg, math.degrees(item.azimuth_rate_rad_s), item.elevation_rate_rad_s

    def bound(a: float, b: float) -> float:
        ra, rb = rates(a), rates(b)
        if ra is None or rb is None:
            raise ValueError("geometry stopped supplying angular rates during certified search")
        az_a, az_rate_a, el_rate_a = ra
        az_b, az_rate_b, el_rate_b = rb
        el_bound = max(abs(el_rate_a), abs(el_rate_b)) + abs(el_rate_b - el_rate_a)
        az_bound_deg = max(abs(az_rate_a), abs(az_rate_b)) + abs(az_rate_b - az_rate_a)
        if mode == "flat" or terrain_horizon is None:
            slope = 0.0
        else:
            slope = horizon_slope_bound_rad_per_deg(terrain_horizon, az_a, az_b)
        return RATE_BOUND_SAFETY * (el_bound + slope * az_bound_deg) + RATE_BOUND_FLOOR_RAD_S

    return bound


def _sample_et_times(start_et: float, end_et: float, step_s: float) -> list[float]:
    count = int(math.floor((end_et - start_et) / step_s))
    times = [start_et + index * step_s for index in range(count + 1)]
    if end_et - times[-1] > 1e-6:
        times.append(end_et)
    else:
        times[-1] = end_et
    if len(times) < 2:
        raise ValueError("analysis interval must contain at least two distinct sample epochs")
    return times


def _run_one_site(
    site: dict[str, Any],
    request: AnalysisRequest | FinderRequest,
    geometry: SpiceGeometry,
    *,
    start_et: float,
    end_et: float,
    run_step_s: float,
) -> tuple[dict[str, Any], SiteVisibilityWindows]:
    if site.get("latitude_deg") is None or site.get("longitude_deg") is None:
        raise AnalysisNotReady(f"Site {site['site_id']} has no verified coordinates")
    ground_elevation, sun_terrain_horizon, earth_terrain_horizon, terrain_metadata, terrain_status = _build_site_horizon(site, geometry, request)
    site_observer = ObserverSite(
        site_id=site["site_id"],
        latitude_deg=float(site["latitude_deg"]),
        longitude_deg=float(site["longitude_deg"]),
        latitude_type=site["latitude_type"],
        longitude_direction="east_positive",
        site_ground_elevation_m=ground_elevation,
    )
    flat_sun_horizon = flat_horizon_elevation_rad(
        geometry.reference_radius_m + ground_elevation,
        request.sun_observer_height_m,
    )
    flat_earth_horizon = flat_horizon_elevation_rad(
        geometry.reference_radius_m + ground_elevation,
        request.antenna_height_m,
    )
    # Every evaluated ET is memoized; root finding frequently revisits identical epochs.
    direction_cache: dict[tuple[float, str, float], TargetDirection] = {}

    def direction(et: float, target: str, height_m: float) -> TargetDirection:
        key = (float(et), target, float(height_m))
        if key not in direction_cache:
            direction_cache[key] = geometry.direction_at_et(
                site_observer, float(et), target=target, observer_height_m=height_m  # type: ignore[arg-type]
            )
        return direction_cache[key]

    clearance_rad = math.radians(request.earth_min_clearance_deg)

    def sun_margin(et: float) -> float:
        target = direction(et, "SUN", request.sun_observer_height_m)
        horizon, _ = _horizon_at(request.horizon_mode, flat_sun_horizon, sun_terrain_horizon, target.azimuth_deg)
        return sun_upper_limb_margin_rad(
            sun_elevation_rad=target.elevation_rad, sun_range_m=target.range_m,
            sun_radius_m=SUN_RADIUS_M, horizon_elevation_rad=horizon,
        )

    def earth_margin(et: float) -> float:
        target = direction(et, "EARTH", request.antenna_height_m)
        horizon, _ = _horizon_at(request.horizon_mode, flat_earth_horizon, earth_terrain_horizon, target.azimuth_deg)
        return earth_centre_clear_margin_rad(
            earth_elevation_rad=target.elevation_rad,
            horizon_elevation_rad=horizon,
            min_clearance_rad=clearance_rad,
        )

    sample_times = _sample_et_times(start_et, end_et, run_step_s)
    sun_margins = [sun_margin(epoch) for epoch in sample_times]
    earth_margins = [earth_margin(epoch) for epoch in sample_times]
    first = sample_times[0]
    has_rates = all(
        direction(first, target, height).azimuth_rate_rad_s is not None
        and direction(first, target, height).elevation_rate_rad_s is not None
        for target, height in (("SUN", request.sun_observer_height_m), ("EARTH", request.antenna_height_m))
    )
    sun_bound = _make_rate_bound(
        direction, "SUN", request.sun_observer_height_m, request.horizon_mode, sun_terrain_horizon,
    ) if has_rates else None
    earth_bound = _make_rate_bound(
        direction, "EARTH", request.antenna_height_m, request.horizon_mode, earth_terrain_horizon,
    ) if has_rates else None
    sun_solution = find_visibility_windows(
        sample_times, sun_margins, sun_margin, tolerance_s=request.event_tolerance_s,
        rate_bound=sun_bound,
    )
    earth_solution = find_visibility_windows(
        sample_times, earth_margins, earth_margin, tolerance_s=request.event_tolerance_s,
        rate_bound=earth_bound,
    )
    metrics = compute_metrics(
        sun_solution.windows, earth_solution.windows,
        interval_start_s=start_et, interval_end_s=end_et,
    )

    timeline: list[dict[str, Any]] = []
    for epoch, sun_margin_value, earth_margin_value in zip(sample_times, sun_margins, earth_margins, strict=True):
        sun = direction(epoch, "SUN", request.sun_observer_height_m)
        earth = direction(epoch, "EARTH", request.antenna_height_m)
        sun_horizon, _ = _horizon_at(request.horizon_mode, flat_sun_horizon, sun_terrain_horizon, sun.azimuth_deg)
        earth_horizon, _ = _horizon_at(request.horizon_mode, flat_earth_horizon, earth_terrain_horizon, earth.azimuth_deg)
        timeline.append({
            "utc": geometry.et_to_utc(epoch),
            "et_s": epoch,
            "sun_azimuth_deg": sun.azimuth_deg,
            "sun_elevation_deg": math.degrees(sun.elevation_rad),
            "sun_range_m": sun.range_m,
            "sun_horizon_deg": math.degrees(sun_horizon),
            "sun_margin_deg": math.degrees(sun_margin_value),
            "sun_visible_upper_limb": sun_margin_value > 0,
            "earth_azimuth_deg": earth.azimuth_deg,
            "earth_elevation_deg": math.degrees(earth.elevation_rad),
            "earth_range_m": earth.range_m,
            "earth_horizon_deg": math.degrees(earth_horizon),
            "earth_margin_deg": math.degrees(earth_margin_value),
            "earth_center_clear": earth_margin_value > 0,
        })

    if request.horizon_mode == "terrain":
        assert sun_terrain_horizon is not None and earth_terrain_horizon is not None
        sun_horizon_profile = [
            {"azimuth_deg": item.azimuth_deg, "elevation_deg": math.degrees(item.elevation_rad) if item.elevation_rad is not None else None,
             "controlling_distance_m": item.controlling_distance_m, "coverage_status": item.coverage_status}
            for item in sun_terrain_horizon.bins
        ]
        earth_horizon_profile = [
            {"azimuth_deg": item.azimuth_deg, "elevation_deg": math.degrees(item.elevation_rad) if item.elevation_rad is not None else None,
             "controlling_distance_m": item.controlling_distance_m, "coverage_status": item.coverage_status}
            for item in earth_terrain_horizon.bins
        ]
    else:
        sun_horizon_profile = [
            {"azimuth_deg": azimuth, "elevation_deg": math.degrees(flat_sun_horizon),
             "controlling_distance_m": None, "coverage_status": "flat-model"}
            for azimuth in range(0, 361, 5)
        ]
        earth_horizon_profile = [
            {"azimuth_deg": azimuth, "elevation_deg": math.degrees(flat_earth_horizon),
             "controlling_distance_m": None, "coverage_status": "flat-model"}
            for azimuth in range(0, 361, 5)
        ]

    result = {
        "site": {
            "site_id": site["site_id"], "name": site["name"],
            "origin": site.get("origin", "official"),
            "catalogue_kind": site.get("catalogue_kind", "official_challenge"),
            "latitude_deg": site["latitude_deg"], "longitude_deg": site["longitude_deg"],
            "latitude_type": site["latitude_type"], "longitude_direction": "east_positive",
            "source_url": site["source_url"], "source_record": site["source_record"],
        },
        "terrain_status": terrain_status,
        "terrain": terrain_metadata,
        "horizon_profile": sun_horizon_profile,
        "earth_horizon_profile": earth_horizon_profile,
        "metrics": _metrics_payload(metrics),
        "series": timeline,
        "sun_windows": [_window_payload(window, geometry) for window in sun_solution.windows],
        "earth_windows": [_window_payload(window, geometry) for window in earth_solution.windows],
        "sun_roots": [_root_payload(root, geometry) for root in sun_solution.roots],
        "earth_roots": [_root_payload(root, geometry) for root in earth_solution.roots],
        "event_precision": _event_precision_payload(
            request.event_tolerance_s, run_step_s, sun_solution, earth_solution, geometry,
        ),
    }
    site_windows = SiteVisibilityWindows(
        site_id=site["site_id"],
        sun_windows=sun_solution.windows,
        earth_windows=earth_solution.windows,
    )
    return result, site_windows


def _event_precision_payload(
    tolerance_s: float, step_s: float, sun: Any, earth: Any, geometry: SpiceGeometry,
) -> dict[str, Any]:
    certified = bool(sun.certified and earth.certified)
    if certified:
        claim = (
            f"Certified discovery: no Sun or Earth visible/non-visible interval longer than "
            f"{tolerance_s:g} s is missed, provided the target angular rates stay within the "
            f"per-step bound (endpoint maximum plus endpoint change, x{RATE_BOUND_SAFETY:g}). "
            "Possible grazes shorter than the tolerance are listed, not hidden."
        )
        method = "rate-bounded bisection + SciPy brentq"
    else:
        claim = (
            "Not certified: angular rates were unavailable, so discovery used sign-change brackets "
            "and local-extremum diagnostics. A short window between two coarse samples can be missed."
        )
        method = "SciPy brentq with local extremum diagnostics"

    def grazes(solution: Any) -> list[dict[str, Any]]:
        return [
            {"start_utc": geometry.et_to_utc(a), "end_utc": geometry.et_to_utc(b),
             "start_et_s": a, "end_et_s": b}
            for a, b in solution.possible_grazing_intervals
        ]

    return {
        "root_time_tolerance_s": tolerance_s,
        "coarse_step_s": step_s,
        "root_method": method,
        "discovery_certified": certified,
        "rate_bound_safety_factor": RATE_BOUND_SAFETY if certified else None,
        "sun_possible_grazing": grazes(sun),
        "earth_possible_grazing": grazes(earth),
        "subdivision_evaluations": {
            "sun": sun.subdivision_evaluations, "earth": earth.subdivision_evaluations,
        },
        "claim": claim,
    }


def _save_run(payload: dict[str, Any]) -> dict[str, Any]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = payload["run_id"]
    target = RUNS_DIR / f"{run_id}.json"
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tmp", dir=RUNS_DIR)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return payload


def run_analysis(request: AnalysisRequest) -> dict[str, Any]:
    """Run a real SPICE-backed analysis and persist a provenance-complete result."""
    with _RUN_LOCK:
        return _run_analysis_locked(request)


def _run_analysis_locked(request: AnalysisRequest) -> dict[str, Any]:
    sites = _load_sites()
    missing = [site_id for site_id in request.site_ids if site_id not in sites]
    if missing:
        raise AnalysisNotReady("Unknown site IDs: " + ", ".join(missing))
    spice, geometry, kernel_manifest_hash, loaded_kernels = _spice_runtime()
    start_utc = _iso_utc(request.start_utc)
    end_utc = _iso_utc(request.end_utc)
    start_et = geometry.utc_to_et(start_utc)
    end_et = geometry.utc_to_et(end_utc)
    if end_et <= start_et:
        raise AnalysisNotReady("SPICE converted end epoch is not after start epoch")
    try:
        spk_coverage = assert_required_spk_coverage(spice, loaded_kernels, start_et, end_et)
        bpc_coverage = assert_required_bpc_coverage(
            spice, loaded_kernels, start_et, end_et, frame=geometry.frame,
        )
    except (SPKCoverageError, BPCoverageError, ValueError) as exc:
        raise AnalysisNotReady(f"Ephemeris/orientation coverage preflight failed: {exc}") from exc
    step_s = float(request.coarse_step_min * 60)
    sample_count = int(math.floor((end_et - start_et) / step_s)) + 2
    if sample_count > 18_000:
        raise AnalysisNotReady("requested analysis exceeds the 18,000-sample guardrail")
    site_results = []
    for site_id in request.site_ids:
        result, _windows = _run_one_site(
            sites[site_id], request, geometry, start_et=start_et, end_et=end_et, run_step_s=step_s,
        )
        site_results.append(result)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "application": {"name": "Lunar South Pole Mission Planner", "version": __version__},
        "analysis_kind": "spice_backed_analysis",
        "validation_status": "computed_not_independently_validated",
        "warning": (
            "Geometric visibility is not a power model, RF link budget, DSN schedule, landing-safety certification, "
            "or a guarantee of communications availability. Reference points are not challenge site ellipses."
        ),
        "settings": {
            "start_utc": start_utc, "end_utc": end_utc,
            "start_et_s": start_et, "end_et_s": end_et,
            "coarse_step_min": request.coarse_step_min,
            "event_tolerance_s": request.event_tolerance_s,
            "sun_observer_height_m": request.sun_observer_height_m,
            "antenna_height_m": request.antenna_height_m,
            "earth_min_clearance_deg": request.earth_min_clearance_deg,
            "horizon_mode": request.horizon_mode,
            "terrain_azimuth_step_deg": request.terrain_azimuth_step_deg,
            "terrain_max_range_m": request.terrain_max_range_m,
        },
        "provenance": {
            "software_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "git_commit": _git_commit(),
            "kernel_manifest_path": "data/manifests/kernels.json",
            "kernel_manifest_sha256": kernel_manifest_hash,
            "loaded_kernels": loaded_kernels,
            "spk_coverage_preflight": spk_coverage,
            "bpc_coverage_preflight": bpc_coverage,
            "dem_manifest_sha256": sha256_file(DEM_MANIFEST),
            "spice_frame": geometry.frame,
            "observer_center": "MOON",
            "aberration_correction": geometry.aberration_correction,
            "moon_reference_radius_m": geometry.reference_radius_m,
            "time_contract": "UTC input -> SPICE ET/TDB for geometry/root solving -> UTC display via loaded LSK",
        },
        "sites": site_results,
    }
    return _save_run(payload)


def _git_commit() -> str | None:
    """Return a revision only when it identifies the exact clean source tree used by the run."""
    import subprocess
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=PROJECT_ROOT, text=True, check=True, capture_output=True, timeout=2,
        )
        if status.stdout.strip():
            return None
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True,
            check=True, capture_output=True, timeout=2,
        ).stdout.strip() or None
    except Exception:
        # A source ZIP without .git metadata, or a missing Git executable, must not report the
        # revision of an unrelated parent checkout as the algorithm version.
        return None


def run_finder(request: FinderRequest) -> dict[str, Any]:
    """Compute a single continuous window set, then evaluate each candidate landing start."""
    with _RUN_LOCK:
        return _run_finder_locked(request)


def _run_finder_locked(request: FinderRequest) -> dict[str, Any]:
    sites = _load_sites()
    missing = [site_id for site_id in request.site_ids if site_id not in sites]
    if missing:
        raise AnalysisNotReady("Unknown site IDs: " + ", ".join(missing))
    spice, geometry, kernel_manifest_hash, loaded_kernels = _spice_runtime()
    start_utc = _iso_utc(request.search_start_utc)
    end_utc = _iso_utc(request.search_end_utc)
    search_start_et = geometry.utc_to_et(start_utc)
    search_end_et = geometry.utc_to_et(end_utc)
    mission_duration_s = float(request.mission_duration_days * 86400)
    analysis_end_et = search_end_et + mission_duration_s
    try:
        spk_coverage = assert_required_spk_coverage(
            spice, loaded_kernels, search_start_et, analysis_end_et
        )
        bpc_coverage = assert_required_bpc_coverage(
            spice, loaded_kernels, search_start_et, analysis_end_et, frame=geometry.frame,
        )
    except (SPKCoverageError, BPCoverageError, ValueError) as exc:
        raise AnalysisNotReady(f"Ephemeris/orientation coverage preflight failed: {exc}") from exc
    step_s = float(request.coarse_step_min * 60)
    sample_count = int(math.floor((analysis_end_et - search_start_et) / step_s)) + 2
    if sample_count * len(request.site_ids) > 50_000:
        raise AnalysisNotReady("finder exceeds the 50,000 site-sample guardrail; increase coarse_step_min or reduce range")

    # Candidate boundaries are actual UTC calendar instants converted to ET individually.
    candidate_utc: list[datetime] = []
    cursor = request.search_start_utc
    while cursor <= request.search_end_utc:
        candidate_utc.append(cursor)
        cursor = cursor + timedelta(days=request.candidate_step_days)
    candidate_ets = [geometry.utc_to_et(_iso_utc(candidate)) for candidate in candidate_utc]
    if not candidate_ets:
        raise AnalysisNotReady("finder produced no candidate starts")

    site_results: list[dict[str, Any]] = []
    finder_site_windows: list[SiteVisibilityWindows] = []
    # Finder outputs are generated by the same engine, extended to cover every possible mission end.
    for site_id in request.site_ids:
        result, windows = _run_one_site(
            sites[site_id], request, geometry,
            start_et=search_start_et, end_et=analysis_end_et, run_step_s=step_s,
        )
        site_results.append(result)
        finder_site_windows.append(windows)
    profile = MissionProfile(
        mission_duration_s=mission_duration_s,
        max_darkness_s=None if request.constraints.max_darkness_h is None else request.constraints.max_darkness_h * 3600,
        max_dte_gap_s=None if request.constraints.max_dte_gap_h is None else request.constraints.max_dte_gap_h * 3600,
        max_joint_outage_s=None if request.constraints.max_joint_outage_h is None else request.constraints.max_joint_outage_h * 3600,
        min_sunlit_fraction=request.constraints.min_sunlit_fraction,
    )
    cells = evaluate_finder_grid(finder_site_windows, candidate_ets, profile)
    grid: list[dict[str, Any]] = []
    for cell in cells:
        grid.append({
            "site_id": cell.site_id,
            "start_utc": geometry.et_to_utc(cell.start_s),
            "end_utc": geometry.et_to_utc(cell.end_s),
            "start_et_s": cell.start_s,
            "end_et_s": cell.end_s,
            "feasible": cell.feasible,
            "first_failed_constraint": cell.first_failed_constraint,
            "failures": [asdict(failure) for failure in cell.failures],
            "metrics": _metrics_payload(cell.metrics),
        })
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "run_id": str(uuid.uuid4()),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "application": {"name": "Lunar South Pole Mission Planner", "version": __version__},
        "analysis_kind": "landing_window_finder",
        "validation_status": "computed_not_independently_validated",
        "warning": "Feasibility means the configured geometric metrics satisfy the user-entered constraints; it is not a landing-safety or comms guarantee.",
        "settings": {
            "search_start_utc": start_utc, "search_end_utc": end_utc,
            "mission_duration_days": request.mission_duration_days,
            "candidate_step_days": request.candidate_step_days,
            "candidate_count": len(candidate_ets),
            "constraints": request.constraints.model_dump(),
            "coarse_step_min": request.coarse_step_min,
            "event_tolerance_s": request.event_tolerance_s,
            "horizon_mode": request.horizon_mode,
        },
        "provenance": {
            "software_version": __version__, "python_version": platform.python_version(),
            "git_commit": _git_commit(), "kernel_manifest_sha256": kernel_manifest_hash,
            "loaded_kernels": loaded_kernels, "spk_coverage_preflight": spk_coverage,
            "bpc_coverage_preflight": bpc_coverage,
            "dem_manifest_sha256": sha256_file(DEM_MANIFEST),
            "spice_frame": geometry.frame, "aberration_correction": geometry.aberration_correction,
            "time_contract": "UTC candidate inputs converted individually to SPICE ET; interval arithmetic in ET seconds",
        },
        "site_results": site_results,
        "grid": grid,
    }
    return _save_run(payload)


def load_saved_run(run_id: str) -> dict[str, Any]:
    if not run_id or any(character not in "0123456789abcdef-" for character in run_id.lower()):
        raise ValueError("invalid run_id")
    path = (RUNS_DIR / f"{run_id}.json").resolve()
    if not path.is_relative_to(RUNS_DIR.resolve()) or not path.is_file():
        raise FileNotFoundError(f"run {run_id} not found")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("run_id") != run_id:
        raise ValueError(f"saved run {run_id} has an invalid or mismatched manifest")
    return payload


def list_saved_runs(limit: int = 25) -> dict[str, Any]:
    """List valid, persisted run manifests without exposing arbitrary files or full series.

    Only canonical UUID filenames created by this service are listed. Malformed or inconsistent
    files are counted and ignored; callers can surface that count rather than presenting them as
    loadable runs. The result body stays small even when analysis JSON files contain long series.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    summaries: list[dict[str, Any]] = []
    invalid_files = 0
    for path in RUNS_DIR.glob("*.json"):
        try:
            canonical_id = str(uuid.UUID(path.stem))
            if canonical_id != path.stem.lower():
                invalid_files += 1
                continue
            payload = load_saved_run(canonical_id)
            site_records = payload.get("sites", payload.get("site_results", []))
            site_names = [
                str(item.get("site", {}).get("name", item.get("site_id", "unknown site")))
                for item in site_records if isinstance(item, dict)
            ]
            settings = payload.get("settings", {})
            summaries.append({
                "run_id": canonical_id,
                "analysis_kind": payload.get("analysis_kind", "unknown"),
                "created_utc": payload.get("created_utc", ""),
                "validation_status": payload.get("validation_status", "unknown"),
                "site_count": len(site_records),
                "site_names": site_names,
                "start_utc": settings.get("start_utc", settings.get("search_start_utc")),
                "end_utc": settings.get("end_utc", settings.get("search_end_utc")),
                "warning": payload.get("warning", ""),
            })
        except (OSError, ValueError, TypeError, KeyError):
            invalid_files += 1
    summaries.sort(key=lambda item: str(item.get("created_utc", "")), reverse=True)
    total = len(summaries)
    return {
        "runs": summaries[:limit],
        "total": total,
        "limit": limit,
        "invalid_run_files_ignored": invalid_files,
    }


def run_as_csv(payload: dict[str, Any]) -> str:
    """Export a rectangular, machine-readable CSV with samples, events, metrics and finder cells.

    Every row has the same header. ``payload_json`` carries the full typed record for that row;
    ``settings_json`` and ``provenance_json`` are populated on the run-manifest row so the CSV
    can be audited without relying on information outside the download.
    """
    import io

    columns = [
        "record_type", "run_id", "analysis_kind", "validation_status", "created_utc",
        "site_id", "site_name", "terrain_status", "utc", "et_s", "target",
        "azimuth_deg", "elevation_deg", "range_m", "horizon_deg", "margin_deg", "visible",
        "window_type", "window_start_utc", "window_end_utc", "start_et_s", "end_et_s",
        "duration_s", "truncated_start", "truncated_end", "root_method", "root_residual_rad",
        "metric_name", "metric_value", "candidate_start_utc", "mission_end_utc", "feasible",
        "first_failed_constraint", "failures_json", "settings_json", "provenance_json", "payload_json",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    run_id = payload.get("run_id", "")
    base = {
        "run_id": run_id,
        "analysis_kind": payload.get("analysis_kind", ""),
        "validation_status": payload.get("validation_status", ""),
        "created_utc": payload.get("created_utc", ""),
    }
    writer.writerow({
        **base, "record_type": "run_manifest",
        "settings_json": json.dumps(payload.get("settings", {}), sort_keys=True, allow_nan=False),
        "provenance_json": json.dumps(payload.get("provenance", {}), sort_keys=True, allow_nan=False),
        "payload_json": json.dumps({
            "warning": payload.get("warning"),
            "schema_version": payload.get("schema_version"),
            "application": payload.get("application"),
        }, sort_keys=True, allow_nan=False),
    })

    for site in payload.get("sites", payload.get("site_results", [])):
        site_obj = site.get("site", {})
        site_base = {
            **base,
            "site_id": site_obj.get("site_id", ""),
            "site_name": site_obj.get("name", ""),
            "terrain_status": site.get("terrain_status", ""),
        }
        for row in site.get("series", []):
            # Sun/Earth pairs share one timestamp row, with the same values as the JSON time series.
            writer.writerow({
                **site_base, "record_type": "sample", "utc": row.get("utc", ""),
                "et_s": row.get("et_s", ""), "azimuth_deg": row.get("sun_azimuth_deg", ""),
                "elevation_deg": row.get("sun_elevation_deg", ""), "range_m": row.get("sun_range_m", ""),
                "horizon_deg": row.get("sun_horizon_deg", ""), "margin_deg": row.get("sun_margin_deg", ""),
                "visible": row.get("sun_visible_upper_limb", ""), "target": "SUN",
                "payload_json": json.dumps({"sun": row}, sort_keys=True, allow_nan=False),
            })
            writer.writerow({
                **site_base, "record_type": "sample", "utc": row.get("utc", ""),
                "et_s": row.get("et_s", ""), "azimuth_deg": row.get("earth_azimuth_deg", ""),
                "elevation_deg": row.get("earth_elevation_deg", ""), "range_m": row.get("earth_range_m", ""),
                "horizon_deg": row.get("earth_horizon_deg", ""), "margin_deg": row.get("earth_margin_deg", ""),
                "visible": row.get("earth_center_clear", ""), "target": "EARTH",
                "payload_json": json.dumps({"earth": row}, sort_keys=True, allow_nan=False),
            })

        for window_type, key in (("SUN", "sun_windows"), ("EARTH", "earth_windows")):
            for window in site.get(key, []):
                writer.writerow({
                    **site_base, "record_type": "window", "window_type": window_type,
                    "window_start_utc": window.get("start_utc", ""),
                    "window_end_utc": window.get("end_utc", ""),
                    "start_et_s": window.get("start_et_s", ""), "end_et_s": window.get("end_et_s", ""),
                    "duration_s": window.get("duration_s", ""),
                    "truncated_start": window.get("start_truncated", ""),
                    "truncated_end": window.get("end_truncated", ""),
                    "payload_json": json.dumps(window, sort_keys=True, allow_nan=False),
                })

        for target, key in (("SUN", "sun_roots"), ("EARTH", "earth_roots")):
            for root in site.get(key, []):
                writer.writerow({
                    **site_base, "record_type": "root", "target": target,
                    "utc": root.get("utc", ""), "et_s": root.get("et_s", ""),
                    "root_method": root.get("method", ""), "root_residual_rad": root.get("residual_rad", ""),
                    "payload_json": json.dumps(root, sort_keys=True, allow_nan=False),
                })

        metrics = site.get("metrics", {})
        for name, value in metrics.items():
            scalar = value if isinstance(value, (int, float, str, bool)) or value is None else None
            if isinstance(value, dict):
                scalar = value.get("duration_s", value.get("value", ""))
            writer.writerow({
                **site_base, "record_type": "metric", "metric_name": name,
                "metric_value": "" if scalar is None else scalar,
                "payload_json": json.dumps(value, sort_keys=True, allow_nan=False),
            })

    for cell in payload.get("grid", []):
        writer.writerow({
            **base, "record_type": "finder_cell", "site_id": cell.get("site_id", ""),
            "utc": cell.get("start_utc", ""), "candidate_start_utc": cell.get("start_utc", ""),
            "mission_end_utc": cell.get("end_utc", ""), "start_et_s": cell.get("start_et_s", ""),
            "end_et_s": cell.get("end_et_s", ""), "feasible": cell.get("feasible", ""),
            "first_failed_constraint": cell.get("first_failed_constraint", ""),
            "failures_json": json.dumps(cell.get("failures", []), sort_keys=True, allow_nan=False),
            "payload_json": json.dumps(cell, sort_keys=True, allow_nan=False),
        })
    return output.getvalue()
