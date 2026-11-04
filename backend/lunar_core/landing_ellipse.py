"""Landing-ellipse risk: what does the ground inside the landing ellipse actually get?

Landers come down somewhere inside an ellipse, not on the target. IM-2 (March 2025) stopped about
250 m from its target inside a crater and its batteries could not recharge. Near the pole the
published Site 004 point is 0 % sunlit while ground 100 m away is 96-100 %. So this module runs
the unchanged production analysis (``location_scan.run_location_scan``: own DEM height, own terrain
horizon, own SPICE directions, certified events) at a grid of points filling the ellipse, and
reports the spread: best, typical, worst, and how much of the ellipse is a dark trap.

It is a spread over evenly spaced points, not a landing probability: real dispersion is denser
near the target. The response says so.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import timedelta
from typing import Any

from lunar_core import __version__, analysis_service, location_scan
from lunar_core.api_models import AnalysisRequest, EllipseRequest
from lunar_core.location_scan import GridOffset

POLAR_LIMIT_DEG = -60.0
TARGET_POINTS = 45
MIN_SPACING_M = 25.0
DARK_TRAP_PCT = 10.0
CACHE_SCHEMA = "ellipse-cache-1"


def ellipse_offsets(semi_major_m: float, semi_minor_m: float, orientation_deg: float,
                    spacing_m: float) -> list[GridOffset]:
    """Square-grid points (local east/north) inside an ellipse, centre first.

    ``orientation_deg`` is the bearing of the major axis, clockwise from local north.
    """
    if not (semi_major_m > 0 and semi_minor_m > 0 and spacing_m > 0):
        raise ValueError("axes and spacing must be positive")
    if semi_minor_m > semi_major_m:
        raise ValueError("semi_minor_m must not exceed semi_major_m")
    theta = math.radians(orientation_deg)
    ux, uy = math.sin(theta), math.cos(theta)  # major-axis unit vector (east, north)
    n = int(math.floor(semi_major_m / spacing_m + 1e-9))
    out = []
    for j in range(n, -n - 1, -1):
        for i in range(-n, n + 1):
            e, nn = i * spacing_m, j * spacing_m
            along = e * ux + nn * uy
            across = -e * uy + nn * ux
            if (along / semi_major_m) ** 2 + (across / semi_minor_m) ** 2 <= 1.0 + 1e-9:
                out.append(GridOffset(e, nn))
    out.sort(key=lambda o: (o.distance_m != 0.0,))
    return out


def auto_spacing(semi_major_m: float, semi_minor_m: float, target_points: int = TARGET_POINTS) -> float:
    """Spacing giving roughly ``target_points`` points in the ellipse, never below MIN_SPACING_M."""
    area = math.pi * semi_major_m * semi_minor_m
    return max(MIN_SPACING_M, math.sqrt(area / target_points))


def risk_summary(points: list[dict[str, Any]], centre_first: bool = True) -> dict[str, Any]:
    """Best / typical / worst and dark-trap share from location-scan point records."""
    ok = [p for p in points if p.get("status") == "ok"]
    if not ok:
        return {"points_ok": 0}
    sun = sorted(p["sunlit_percent"] for p in ok)
    n = len(sun)

    def pct(q: float) -> float:
        return sun[min(n - 1, max(0, round(q * (n - 1))))]

    best = max(ok, key=lambda p: (p["sunlit_percent"], p["dte_clear_percent"]))
    worst = min(ok, key=lambda p: (p["sunlit_percent"], p["dte_clear_percent"]))
    target = ok[0] if centre_first and ok[0]["distance_m"] == 0.0 else None

    def where(p: dict[str, Any]) -> dict[str, Any]:
        return {k: p[k] for k in ("east_m", "north_m", "latitude_deg", "longitude_deg", "sunlit_percent",
                                  "dte_clear_percent", "both_percent")}

    trap = sum(1 for p in ok if p["sunlit_percent"] < DARK_TRAP_PCT) / n
    return {
        "points_ok": n,
        "sunlit_percent": {"worst": sun[0], "p10": pct(0.1), "median": pct(0.5), "p90": pct(0.9), "best": sun[-1]},
        "earth_percent": {"worst": min(p["dte_clear_percent"] for p in ok),
                          "best": max(p["dte_clear_percent"] for p in ok)},
        "dark_trap_share": trap,
        "target": where(target) if target else None,
        "best_point": where(best),
        "worst_point": where(worst),
        "chips": [
            f"best {sun[-1]:.0f}% ☀",
            f"typical {pct(0.5):.0f}% ☀",
            f"worst {sun[0]:.0f}% ☀",
            f"{trap:.0%} of ellipse < {DARK_TRAP_PCT:.0f}% ☀",
        ],
    }


def _cache_path(request: EllipseRequest) -> Any:
    from lunar_core.terrain import HORIZON_ALGORITHM_VERSION

    material = {"schema": CACHE_SCHEMA, "version": __version__, "horizon": HORIZON_ALGORITHM_VERSION,
                "request": request.model_dump(mode="json")}
    for path in (analysis_service.KERNEL_MANIFEST, analysis_service.DEM_MANIFEST):
        try:
            material[path.name] = path.stat().st_mtime_ns
        except OSError:
            material[path.name] = None
    key = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:32]
    return analysis_service.RUNS_DIR.parent / "cache" / "ellipses" / f"{key}.json"


def run_landing_ellipse(request: EllipseRequest) -> dict[str, Any]:
    sites = analysis_service._load_sites()
    if request.site_id not in sites:
        raise ValueError(f"unknown site ID: {request.site_id}")
    if float(sites[request.site_id]["latitude_deg"]) > POLAR_LIMIT_DEG:
        raise ValueError("the landing ellipse needs terrain, which we have only at or south of 60 S (D-22)")
    cache = _cache_path(request)
    if cache.is_file():
        try:
            return {**json.loads(cache.read_text(encoding="utf-8")), "cache_hit": True}
        except (OSError, json.JSONDecodeError):
            cache.unlink(missing_ok=True)
    started = time.monotonic()
    b = request.semi_minor_m or request.semi_major_m
    spacing = request.spacing_m or auto_spacing(request.semi_major_m, b)
    offsets = ellipse_offsets(request.semi_major_m, b, request.orientation_deg, spacing)
    analysis = AnalysisRequest(
        site_ids=[request.site_id], start_utc=request.start_utc,
        end_utc=request.start_utc + timedelta(days=request.days), coarse_step_min=30, event_tolerance_s=10.0,
        horizon_mode="terrain", sun_observer_height_m=request.panel_height_m, antenna_height_m=2.0,
    )
    grid = {"shape": "ellipse", "semi_major_m": request.semi_major_m, "semi_minor_m": b,
            "orientation_deg": request.orientation_deg, "spacing_m": spacing, "point_count": len(offsets),
            "layout": "square grid in local east/north clipped to the ellipse; spherical geodesic offsets"}
    scan = location_scan.run_location_scan(request.site_id, analysis, offsets=offsets, grid_description=grid,
                                           save=False)
    payload = {
        "schema_version": "1.0",
        "kind": "landing_ellipse",
        "site": scan["site"],
        "ellipse": grid,
        "settings": scan["settings"],
        "risk": risk_summary(scan["points"]),
        "points": [{k: p.get(k) for k in ("east_m", "north_m", "latitude_deg", "longitude_deg", "status",
                                          "sunlit_percent", "dte_clear_percent", "both_percent",
                                          "longest_darkness_h", "ground_elevation_m")} for p in scan["points"]],
        "points_unavailable": scan["points_unavailable"],
        "interpretation": ("Evenly spaced points filling the ellipse, each a full production analysis. "
                           "A spread of outcomes, not a landing probability: real dispersion is denser near the target."),
        "provenance": scan["provenance"],
        "compute_seconds": round(time.monotonic() - started, 1),
        "cache_hit": False,
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(payload, allow_nan=False), encoding="utf-8")
    return payload
