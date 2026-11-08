"""One-button site check: sensible defaults, a run cache and a plain-language summary.

The analysis API exposes every scientific setting. A visitor needs none of them, so
``POST /api/check`` takes a site, a start date, a number of days and a panel height, picks
the settings itself and answers in sentences. It runs the same ``run_analysis`` as the
expert API. Nothing here changes a computed number; the summary only restates the metrics
and windows the analysis produced, against stated thresholds.

Defaults (all echoed in ``chosen_settings``):
  * terrain horizon at or south of 60 S (where the DEMs are), else flat; if terrain is not
    available for the point, a flat run is made and the summary says so;
  * 30 min coarse step, 10 s event tolerance (event times good to 10 s, enough for planning);
  * Sun observer height = the requested panel height; antenna height 2 m.

Run cache: an identical request (same inputs, kernel and DEM manifests, software and horizon
algorithm versions) returns the saved run instead of recomputing.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from lunar_core import __version__, analysis_service, cache_keys, custom_point, verify
from lunar_core.api_models import AnalysisRequest, CheckRequest, MissionConstraints
from lunar_core.provenance import sha256_file
from lunar_core.sky_geometry import SUN_RADIUS_KM

POLAR_LIMIT_DEG = -60.0
COARSE_STEP_MIN = 30
EVENT_TOLERANCE_S = 10.0
ANTENNA_HEIGHT_M = 2.0
CACHE_SCHEMA = "check-cache-1"


# --- plain-language formatting ---------------------------------------------------------------

def human_duration(seconds: float) -> str:
    """'3 d 4 h', '5 h 20 min', '12 min'. Rounded down to the minute."""
    minutes = int(max(0.0, seconds) // 60)
    days, rem = divmod(minutes, 1440)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {mins} min"
    return f"{mins} min"


def _pct(value: float) -> str:
    return f"{value:.0f}%" if value >= 1.0 or value == 0.0 else f"{value:.1f}%"


def _outage_text(metric: dict[str, Any]) -> str:
    text = human_duration(float(metric["duration_s"]))
    if metric.get("truncated_start") or metric.get("truncated_end"):
        return f"at least {text}"  # the check window cut this outage, so it may be longer
    return text


def disc_visible_fraction(centre_clearance_deg: float, semidiameter_deg: float) -> float:
    """Visible fraction of the Sun's disc whose centre stands ``centre_clearance_deg`` above a straight
    horizon edge: circular segment, f = 1 - (acos h - h sqrt(1 - h^2)) / pi with h = clearance / radius."""
    if semidiameter_deg <= 0:
        return 1.0 if centre_clearance_deg > 0 else 0.0
    h = centre_clearance_deg / semidiameter_deg
    if h >= 1.0:
        return 1.0
    if h <= -1.0:
        return 0.0
    return 1.0 - (math.acos(h) - h * math.sqrt(1.0 - h * h)) / math.pi


def sun_disc_percent(series: list[dict[str, Any]]) -> float | None:
    """Mean visible fraction of the Sun's disc over the samples, in percent (independent review finding 4).

    "Sunlit %" counts a sample as lit if any sliver of the Sun clears the horizon, which overstates
    power when the Sun grazes the horizon for hours, as it does at the poles. This is the quantity
    Gate E compared with NASA Goddard's maps (mean disc visibility). Samples are the run's coarse
    steps, equally weighted.
    """
    values = []
    for row in series:
        rng = row.get("sun_range_m")
        if rng is None or row.get("sun_horizon_deg") is None:
            return None
        semi = math.degrees(math.asin(min(1.0, SUN_RADIUS_KM * 1000.0 / float(rng))))
        values.append(disc_visible_fraction(float(row["sun_elevation_deg"]) - float(row["sun_horizon_deg"]), semi))
    return 100.0 * sum(values) / len(values) if values else None


def _limit_status(value_h: float, limit_h: float | None, truncated: bool) -> str:
    """pass / fail / unknown. A truncated outage is a lower bound: within the limit is not proof."""
    if limit_h is None:
        return "no_limit"
    if value_h > limit_h:
        return "fail"
    return "unknown" if truncated else "pass"


def summarise(run: dict[str, Any], *, height_m: float, horizon_note: str | None,
              constraints: MissionConstraints) -> dict[str, Any]:
    """Plain summary of a one-site analysis run. Only restates computed results."""
    site = run["sites"][0]
    m = site["metrics"]
    terrain = site["terrain_status"]
    sun_pct, earth_pct, both_pct = m["sunlit_percent"], m["dte_clear_percent"], m["both_percent"]
    dark, gap, joint = m["longest_darkness"], m["longest_dte_gap"], m["longest_joint_outage"]

    disc_pct = sun_disc_percent(site.get("series") or [])
    lines: list[str] = [
        f"Some of the Sun is visible from a panel {height_m:g} m above the ground {_pct(sun_pct)} of the time"
        + (f"; averaged over the whole disc, {_pct(disc_pct)}." if disc_pct is not None else "."),
        f"Earth is above the horizon {_pct(earth_pct)} of the time; both together {_pct(both_pct)}.",
    ]
    if sun_pct == 0.0:
        lines.append("The Sun never clears the horizon at this exact point in this period. "
                     "At the poles a point a few hundred metres away, or a taller mast, can differ a lot.")
    elif sun_pct >= 100.0:
        lines.append("The Sun never sets here in this period.")
    else:
        lines.append(f"Longest stretch of darkness: {_outage_text(dark)}.")
    if earth_pct == 0.0:
        lines.append("Earth never rises here in this period, so there is no direct-to-Earth line of sight "
                     "(typical of the far side and some polar slopes); a relay would be needed.")
    elif earth_pct < 100.0:
        lines.append(f"Longest time without Earth in view: {_outage_text(gap)}.")
    else:
        lines.append("Earth stays in view the whole period.")

    checks = []
    for key, label, metric, limit in (
        ("darkness", "Longest darkness", dark, constraints.max_darkness_h),
        ("earth_gap", "Longest time without Earth", gap, constraints.max_dte_gap_h),
        ("joint_outage", "Longest time with neither", joint, constraints.max_joint_outage_h),
    ):
        hours = float(metric["duration_s"]) / 3600.0
        truncated = bool(metric.get("truncated_start") or metric.get("truncated_end"))
        checks.append({"key": key, "label": label, "value_h": hours, "limit_h": limit,
                       "text": _outage_text(metric), "lower_bound": truncated,
                       "status": _limit_status(hours, limit, truncated)})
    if constraints.min_sunlit_fraction is not None:
        ok = sun_pct / 100.0 >= constraints.min_sunlit_fraction
        checks.append({"key": "sunlit", "label": "Time in sunlight", "value_pct": sun_pct,
                       "limit_pct": constraints.min_sunlit_fraction * 100.0, "text": _pct(sun_pct),
                       "status": "pass" if ok else "fail"})

    caveats = ["Reference site from published sources, not an official challenge coordinate."
               if site["site"].get("origin") == "reference" else None,
               "A point you picked, not a catalogue site." if site["site"].get("origin") == "custom" else None,
               custom_point.resolution_caveat(site) if terrain != "flat" else None,
               "Flat horizon: hills and crater walls are not modelled, so polar results can be badly off."
               if terrain == "flat" else None,
               horizon_note,
               "Line of sight to Earth is geometry only, not a guaranteed radio link."]

    return {
        "headline": lines[0] + " " + lines[1],
        "lines": lines,
        "numbers": {"sunlit_percent": sun_pct, "sun_disc_percent": disc_pct, "earth_percent": earth_pct,
                    "both_percent": both_pct},
        "definitions": {"sunlit_percent": "time with any part of the Sun above the horizon (event-refined)",
                        "sun_disc_percent": "mean visible fraction of the Sun's disc (sampled every coarse step)"},
        "limits": {
            "source": "default mission profile (same as the date finder); change it there",
            "checks": checks,
            "all_pass": all(c["status"] in ("pass", "no_limit") for c in checks),
        },
        "bands": {
            "sun": [{"start_utc": w["start_utc"], "end_utc": w["end_utc"]} for w in site["sun_windows"]],
            "earth": [{"start_utc": w["start_utc"], "end_utc": w["end_utc"]} for w in site["earth_windows"]],
        },
        "terrain_status": terrain,
        "caveats": [c for c in caveats if c],
    }


# --- request handling and cache ---------------------------------------------------------------

def _cache_key(request: CheckRequest, mode: str, dem_sha: str | None, kernel_sha: str | None,
               site: dict[str, Any] | None = None) -> str:
    from lunar_core.terrain import HORIZON_ALGORITHM_VERSION

    material = {
        "schema": CACHE_SCHEMA, "version": __version__, "horizon_algorithm": HORIZON_ALGORITHM_VERSION,
        "kernel_manifest": kernel_sha, "dem_manifest": dem_sha if mode == "terrain" else None,
        "request": request.model_dump(mode="json"), "mode": mode,
        "step": COARSE_STEP_MIN, "tolerance": EVENT_TOLERANCE_S, "antenna": ANTENNA_HEIGHT_M,
        "code": cache_keys.code_fingerprint(), "site": cache_keys.site_fingerprint(site or {}),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:32]


def _cache_dir() -> Path:
    return analysis_service.RUNS_DIR.parent / "cache" / "checks"


def _file_sha(path: Path) -> str | None:
    try:
        return sha256_file(path)
    except OSError:
        return None


def _analysis_request(request: CheckRequest, mode: str, site_id: str) -> AnalysisRequest:
    end = request.start_utc + timedelta(days=request.days)
    return AnalysisRequest(
        site_ids=[site_id], start_utc=request.start_utc, end_utc=end,
        coarse_step_min=COARSE_STEP_MIN, event_tolerance_s=EVENT_TOLERANCE_S,
        sun_observer_height_m=request.panel_height_m, antenna_height_m=ANTENNA_HEIGHT_M, horizon_mode=mode,
    )


def run_check(request: CheckRequest) -> dict[str, Any]:
    site = custom_point.resolve(request.site_id, request.latitude_deg, request.longitude_deg,
                                analysis_service._load_sites())
    extra = {site["site_id"]: site} if site.get("origin") == "custom" else None
    latitude = float(site["latitude_deg"])
    preferred = "terrain" if latitude <= POLAR_LIMIT_DEG else "flat"
    kernel_sha = _file_sha(analysis_service.KERNEL_MANIFEST)
    dem_sha = _file_sha(analysis_service.DEM_MANIFEST)
    started = time.monotonic()

    note: str | None = None
    failed_indexes: list[Path] = []  # terrain keys that fell back; they will point at the flat run
    for mode in ([preferred, "flat"] if preferred == "terrain" else ["flat"]):
        key = _cache_key(request, mode, dem_sha, kernel_sha, site)
        index = _cache_dir() / f"{key}.json"
        if index.is_file():
            try:
                cached = json.loads(index.read_text(encoding="utf-8"))
                run = analysis_service.load_saved_run(cached["run_id"])
                return _response(run, request, cached.get("horizon_note"), cache_hit=True,
                                 seconds=time.monotonic() - started)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                index.unlink(missing_ok=True)  # stale index entry: recompute, never trust it
        try:
            run = analysis_service.run_analysis(_analysis_request(request, mode, site["site_id"]),
                                                extra_sites=extra)
        except analysis_service.TerrainNotReady as exc:
            note = f"Terrain was not available for this point ({exc}); this result uses a flat horizon."
            failed_indexes.append(index)
            continue
        index.parent.mkdir(parents=True, exist_ok=True)
        entry = json.dumps({"run_id": run["run_id"], "horizon_note": note})
        for path in (index, *failed_indexes):  # so a repeat request does not retry terrain
            cache_keys.write_atomic(path, entry)
        return _response(run, request, note, cache_hit=False, seconds=time.monotonic() - started)
    raise analysis_service.AnalysisNotReady("no horizon model could be built for this site")


def _response(run: dict[str, Any], request: CheckRequest, note: str | None, *, cache_hit: bool,
              seconds: float) -> dict[str, Any]:
    settings = run["settings"]
    return {
        "schema_version": "1.0",
        "kind": "site_check",
        "site": run["sites"][0]["site"],
        "terrain": custom_point.terrain_summary(run["sites"][0]) if settings["horizon_mode"] == "terrain" else None,
        "request": request.model_dump(mode="json"),
        "chosen_settings": {
            "horizon_mode": settings["horizon_mode"], "coarse_step_min": settings["coarse_step_min"],
            "event_tolerance_s": settings["event_tolerance_s"],
            "sun_observer_height_m": settings["sun_observer_height_m"],
            "antenna_height_m": settings["antenna_height_m"],
            "why": ("terrain is tried at or south of 60 S; it needs the regional map under 200 km of rays in "
                    "every direction, which holds south of about 66.6 S, so between 60 and ~66.6 S answers usually "
                    "fall back to a flat horizon (with a note); 10 s event precision"),
        },
        "summary": summarise(run, height_m=request.panel_height_m, horizon_note=note,
                             constraints=MissionConstraints()),
        "verify": verify.verify_block(run["sites"][0], run["sites"][0]["series"][0],
                                      sun_height_m=settings["sun_observer_height_m"],
                                      antenna_height_m=settings["antenna_height_m"]),
        "run_id": run["run_id"],
        "run_url": f"/api/runs/{run['run_id']}",
        "cache_hit": cache_hit,
        "compute_seconds": round(seconds, 2) if math.isfinite(seconds) else None,
    }
