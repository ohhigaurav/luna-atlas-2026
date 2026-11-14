"""Landing opportunities: when can a lander touch down at this site, and if never, why not?

Answers the planner's question directly instead of failing every date against fixed limits:
"from this date on, when are the next touchdown windows where the Sun is up, Earth is in
view, the Sun is low enough to see hazards, and enough daylight remains for the mission?"

Everything comes from the production analysis (``run_analysis``: SPICE geometry, terrain or
flat horizon, certified event windows). This module only applies the rules below to its
samples and windows. Rules and their defaults are returned with every answer.

Rules for a touchdown instant t:
  R1 sun_up        the Sun's upper limb is above the local horizon at t;
  R2 daylight      the sunlit window containing t lasts at least ``mission_days`` after t
                   (the mission ends before sunset; a lunar day is ~14.8 Earth days near the
                   equator, so more than ~14 days is never possible there);
  R3 earth_up      Earth's centre is above the local horizon at t (direct-to-Earth contact
                   during landing), if ``require_earth_at_landing``;
  R4 low_sun       the Sun's centre is at most ``max_sun_elevation_deg`` above the flat
                   horizontal at t (long shadows for hazard detection; Apollo landed at
                   5-15 deg), if set.
  R5 sun_high      the Sun's centre stands at least ``min_sun_elevation_deg`` above the LOCAL
                   horizon at t (terrain, or the level horizon where flat), so the ground is lit
                   well enough to see hazards instead of at the first sliver of sunrise. "auto"
                   (default) = min(5 deg, half the highest Sun the latitude allows,
                   0.5 * (90 - |lat| + 1.54 deg lunar obliquity)): 5 deg is Apollo's lower bound
                   (5-14 deg; NASA SP-4214 ch. 6) and applies wherever the Sun climbs past 10 deg
                   (|lat| <= ~81.5 deg); nearer the pole the threshold shrinks with the Sun's reach
                   (84.8 S: 3.4 deg, 89.5 S: 1.0 deg), where the Sun never exceeds ~7 deg and is
                   usually 1-2 deg (NASA NESC, IAASS 2023). Measured above the local horizon, so a
                   ridge-top Sun at -2.9 deg from the level horizontal still counts if it clears the
                   dipped horizon. ``None`` turns R5 off. A threshold at or above
                   ``max_sun_elevation_deg`` is refused (no time could pass both).
Touchdown candidates are the analysis samples (30 min apart), so window edges are good to
30 min. Sunset times inside the analysis are event-refined (10 s).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from lunar_core import __version__, analysis_service, cache_keys, custom_point, verify
from lunar_core.api_models import AnalysisRequest, LandingRequest

CACHE_SCHEMA = "landing-cache-9"  # 4: R5; 5: clearance; 6: R5 v2 (local horizon, latitude-scaled); 8: soonest/best; 9: best_earth
POLAR_LIMIT_DEG = -60.0
CHUNK_DAYS = 59
STEP_MIN = 30
EVENT_TOLERANCE_S = 10.0
MAX_OPPORTUNITIES = 24
BEST_RULE = ("Two picks, because they trade off: 'best' = the most sunlight after touchdown (power margin), ties to "
             "more Earth; 'best_earth' = the most Earth in view during the mission (direct-to-Earth contact), ties to "
             "more sunlight. Equal picks go to the earlier date. Every window passes R1-R5, so all have enough daylight.")
RULE_TEXT = {
    "sun_up": "Sun above the horizon at touchdown",
    "daylight": "enough daylight left for the mission",
    "earth_up": "Earth above the horizon at touchdown (direct contact while landing)",
    "low_sun": "Sun low enough for long shadows (hazard detection while landing)",
    "sun_high": "Sun high enough to light the ground (not the first sliver of sunrise)",
}
AUTO_MIN_SUN_DEG = 5.0
AUTO_MIN_SUN_FRACTION = 0.5
LUNAR_OBLIQUITY_DEG = 1.54


def resolve_min_sun(setting: float | str | None, latitude_deg: float) -> float | None:
    """R5's threshold (deg above the local horizon): a number as given, "auto" by latitude, None = off."""
    if setting is None:
        return None
    if setting == "auto":
        reach = max(0.0, 90.0 - abs(latitude_deg) + LUNAR_OBLIQUITY_DEG)
        return min(AUTO_MIN_SUN_DEG, AUTO_MIN_SUN_FRACTION * reach)
    return float(setting)


@dataclass(frozen=True, slots=True)
class Window:
    start_s: float
    end_s: float
    start_utc: str
    end_utc: str
    end_open: bool  # the data ended while the window was still open: its true end is later


@dataclass(frozen=True, slots=True)
class Sample:
    t_s: float
    utc: str
    sun_up: bool
    sun_el_deg: float
    earth_up: bool
    sun_horizon_deg: float | None = None  # local horizon height toward the Sun (terrain or flat)


def merge_windows(chunks: Sequence[Sequence[dict[str, Any]]]) -> list[Window]:
    """Join windows split at chunk boundaries (end of one chunk = start of the next, both cut)."""
    out: list[Window] = []
    for chunk in chunks:
        for w in chunk:
            item = Window(float(w["start_et_s"]), float(w["end_et_s"]), w["start_utc"], w["end_utc"],
                          bool(w["end_truncated"]))
            if out and out[-1].end_open and w["start_truncated"] and abs(out[-1].end_s - item.start_s) < 1.0:
                prev = out.pop()
                item = Window(prev.start_s, item.end_s, prev.start_utc, item.end_utc, item.end_open)
            out.append(item)
    # Only the last window can still be open; an interior "open" end was a chunk seam with no
    # continuation, which means the target set exactly at the seam.
    return [w if i == len(out) - 1 else Window(w.start_s, w.end_s, w.start_utc, w.end_utc, False)
            for i, w in enumerate(out)]


def _clearance(s: Sample) -> float | None:
    """How far the Sun's centre stands above the local horizon (terrain or flat) at that azimuth.

    ``sun_el_deg`` is measured from the level (astronomical) horizontal. On a high ridge the real
    horizon dips below it, so the Sun can shine at a negative elevation; this is the number that
    says how high it actually looks from the ground.
    """
    return None if s.sun_horizon_deg is None else s.sun_el_deg - s.sun_horizon_deg


def _containing(windows: Sequence[Window], t: float) -> Window | None:
    for w in windows:
        if w.start_s <= t < w.end_s:
            return w
    return None


def _overlap_fraction(windows: Sequence[Window], a: float, b: float) -> float:
    if b <= a:
        return 0.0
    covered = sum(max(0.0, min(b, w.end_s) - max(a, w.start_s)) for w in windows)
    return min(1.0, covered / (b - a))


def evaluate(samples: Sequence[Sample], sun: Sequence[Window], earth: Sequence[Window], *,
             mission_days: float, require_earth: bool, max_sun_el_deg: float | None,
             search_end_s: float, step_s: float, min_sun_el_deg: float | None = None) -> dict[str, Any]:
    """Apply R1-R5 to every candidate sample up to ``search_end_s``; group passes into windows."""
    need_s = mission_days * 86400.0
    rows: list[dict[str, Any]] = []
    for s in samples:
        if s.t_s > search_end_s:
            break
        w = _containing(sun, s.t_s) if s.sun_up else None
        left = (w.end_s - s.t_s) if w else 0.0
        checks = {
            "sun_up": w is not None,
            "daylight": w is not None and left >= need_s,
            "earth_up": s.earth_up or not require_earth,
            "low_sun": max_sun_el_deg is None or s.sun_el_deg <= max_sun_el_deg,
            "sun_high": min_sun_el_deg is None or (
                s.sun_el_deg - (s.sun_horizon_deg or 0.0) if s.sun_horizon_deg is not None else s.sun_el_deg
            ) >= min_sun_el_deg,
        }
        rows.append({"s": s, "window": w, "left_s": left, "checks": checks,
                     "lower_bound": bool(w and w.end_open)})

    opportunities: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def close() -> None:
        if not current:
            return
        best = max(current, key=lambda r: r["left_s"])
        s0, s1, sb = current[0]["s"], current[-1]["s"], best["s"]
        opportunities.append({
            "touchdown_from_utc": s0.utc, "touchdown_until_utc": s1.utc,
            "best_touchdown_utc": sb.utc,
            "daylight_after_best_h": best["left_s"] / 3600.0,
            "daylight_is_lower_bound": best["lower_bound"],
            "sunset_utc": best["window"].end_utc if not best["lower_bound"] else None,
            "sun_elevation_at_best_deg": sb.sun_el_deg,
            "sun_above_horizon_at_best_deg": _clearance(sb),
            "earth_in_view_during_mission_pct": 100.0 * _overlap_fraction(earth, sb.t_s, sb.t_s + need_s),
        })
        current.clear()

    for r in rows:
        if all(r["checks"].values()) and (not current or r["s"].t_s - current[-1]["s"].t_s <= step_s * 1.01):
            current.append(r)
        elif all(r["checks"].values()):
            close()
            current.append(r)
        else:
            close()
    close()

    fail_counts = {k: sum(1 for r in rows if not r["checks"][k]) for k in RULE_TEXT}
    closest = None
    if not opportunities and rows:
        near = max(rows, key=lambda r: (sum(r["checks"].values()), r["left_s"]))
        closest = {
            "touchdown_utc": near["s"].utc,
            "failed_rules": [k for k, ok in near["checks"].items() if not ok],
            "daylight_after_h": near["left_s"] / 3600.0,
            "daylight_needed_h": need_s / 3600.0,
            "sun_elevation_deg": near["s"].sun_el_deg,
            "sun_above_horizon_deg": _clearance(near["s"]),
            "earth_up": near["s"].earth_up,
        }
    longest = max(sun, key=lambda w: w.end_s - w.start_s, default=None)
    # Over ALL windows in the search, not only the first MAX_OPPORTUNITIES listed.
    # max keeps the first of equals, i.e. the earliest
    best = (max(opportunities, key=lambda o: (o["daylight_after_best_h"], o["earth_in_view_during_mission_pct"]))
            if opportunities else None)
    best_earth = (max(opportunities, key=lambda o: (o["earth_in_view_during_mission_pct"], o["daylight_after_best_h"]))
                  if opportunities else None)
    return {
        "soonest": dict(opportunities[0]) if opportunities else None,
        "best": None if best is None else {**best, "rank": opportunities.index(best) + 1},
        "best_earth": None if best_earth is None else {**best_earth, "rank": opportunities.index(best_earth) + 1},
        "best_rule": BEST_RULE,
        "opportunities": opportunities[:MAX_OPPORTUNITIES],
        "opportunity_count": len(opportunities),
        "candidates_checked": len(rows),
        "candidates_failing": fail_counts,
        "closest_miss": closest,
        "longest_sunlit_window": None if longest is None else {
            "start_utc": longest.start_utc, "end_utc": longest.end_utc,
            "hours": (longest.end_s - longest.start_s) / 3600.0, "is_lower_bound": longest.end_open,
        },
    }


def explain(result: dict[str, Any], *, mission_days: float, site_name: str) -> list[str]:
    """Plain sentences. Only restates ``evaluate`` output."""
    lines: list[str] = []
    opp = result["opportunities"]
    if opp:
        first = opp[0]
        days = first["daylight_after_best_h"] / 24.0
        lines.append(
            f"Next landing opportunity at {site_name}: touch down between {first['touchdown_from_utc'][:16]} and "
            f"{first['touchdown_until_utc'][:16]} UTC. Landing at {first['best_touchdown_utc'][:16]} gives "
            f"{'at least ' if first['daylight_is_lower_bound'] else ''}{days:.1f} days of sunlight; "
            f"Earth is in view {first['earth_in_view_during_mission_pct']:.0f}% of the mission.")
        if result["opportunity_count"] > 1:
            lines.append(f"{result['opportunity_count']} opportunities in the search period.")
        best = result.get("best")
        if best and best["best_touchdown_utc"] != first["best_touchdown_utc"]:
            lines.append(
                f"Best in the period: land at {best['best_touchdown_utc'][:16]} UTC for "
                f"{'at least ' if best['daylight_is_lower_bound'] else ''}{best['daylight_after_best_h'] / 24:.1f} days "
                f"of sunlight, Earth in view {best['earth_in_view_during_mission_pct']:.0f}% of the mission.")
        elif best:
            lines.append("The next opportunity is also the best one in the period (most sunlight after landing).")
        be = result.get("best_earth")
        if be and best and be["best_touchdown_utc"] != best["best_touchdown_utc"]:
            lines.append(
                f"Most Earth contact: land at {be['best_touchdown_utc'][:16]} UTC, Earth in view "
                f"{be['earth_in_view_during_mission_pct']:.0f}% of the mission, "
                f"{'at least ' if be['daylight_is_lower_bound'] else ''}{be['daylight_after_best_h'] / 24:.1f} days of sunlight.")
        return lines
    lines.append(f"No touchdown time in this period meets all the rules for a {mission_days:g}-day mission.")
    miss = result["closest_miss"]
    if miss:
        failed = ", ".join(RULE_TEXT[k] for k in miss["failed_rules"])
        lines.append(f"Closest: {miss['touchdown_utc'][:16]} UTC, which misses: {failed}.")
        if "daylight" in miss["failed_rules"] and miss["daylight_after_h"] > 0:
            lines.append(f"It would give {miss['daylight_after_h'] / 24:.1f} days of sunlight; you asked for "
                         f"{mission_days:g}. Try a shorter mission or another site.")
    longest = result["longest_sunlit_window"]
    if longest:
        lines.append(f"The longest stretch of sunlight here is {longest['hours'] / 24:.1f} days "
                     f"({longest['start_utc'][:10]} to {longest['end_utc'][:10]}).")
    else:
        lines.append("The Sun never rises above the local horizon here in this period.")
    return lines


_KEY_LOCKS: dict[str, threading.Lock] = {}
_KEY_LOCKS_GUARD = threading.Lock()


def _cache_path(request: LandingRequest, site: dict[str, Any]) -> Any:
    """Result cache: same request, resolved site record, backend code, horizon algorithm and manifests."""
    from lunar_core.terrain import HORIZON_ALGORITHM_VERSION

    material: dict[str, Any] = {"schema": CACHE_SCHEMA, "version": __version__, "horizon": HORIZON_ALGORITHM_VERSION,
                                "request": request.model_dump(mode="json"), "step": STEP_MIN, "chunk": CHUNK_DAYS,
                                **cache_keys.key_material(site=site, manifests=(analysis_service.KERNEL_MANIFEST,
                                                                                analysis_service.DEM_MANIFEST))}
    key = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()[:32]
    return analysis_service.RUNS_DIR.parent / "cache" / "landing" / f"{key}.json"


def check_sun_band(request: LandingRequest, site: dict[str, Any]) -> float | None:
    """R5's threshold for this site; refuse a band no touchdown time could satisfy."""
    min_sun = resolve_min_sun(request.min_sun_elevation_deg, float(site["latitude_deg"]))
    if min_sun is not None and request.max_sun_elevation_deg is not None and min_sun >= request.max_sun_elevation_deg:
        raise ValueError(f"minimum Sun height {min_sun:.2f} deg is not below the maximum "
                         f"{request.max_sun_elevation_deg:.2f} deg: no touchdown time could pass both")
    return min_sun


def run_landing(request: LandingRequest) -> dict[str, Any]:
    """Cached: the app asks the same question for every site on opening (pin status, PRD F24)."""
    site = custom_point.resolve(request.site_id, request.latitude_deg, request.longitude_deg,
                                analysis_service._load_sites())
    check_sun_band(request, site)  # fail fast, before any computation
    cache = _cache_path(request, site)
    # The background warmer and the browser can ask the same question at once: the second waits
    # for the first and reads its answer instead of computing it again.
    with _KEY_LOCKS_GUARD:
        key_lock = _KEY_LOCKS.setdefault(cache.name, threading.Lock())
    with key_lock:
        if cache.is_file():
            try:
                return {**json.loads(cache.read_text(encoding="utf-8")), "cache_hit": True}
            except (OSError, json.JSONDecodeError):
                cache.unlink(missing_ok=True)
        result = _compute_landing(request, site)
        cache_keys.write_atomic(cache, json.dumps(result))
        return {**result, "cache_hit": False}


def _compute_landing(request: LandingRequest, site: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    mode: Literal["flat", "terrain"] = "terrain" if float(site["latitude_deg"]) <= POLAR_LIMIT_DEG else "flat"
    note = None
    end = request.search_start_utc + timedelta(days=request.search_days + math.ceil(request.mission_days) + 1)

    extra = {site["site_id"]: site} if site.get("origin") == "custom" else None

    def chunks(m: Literal["flat", "terrain"]) -> list[dict[str, Any]]:
        out, cursor = [], request.search_start_utc
        while cursor < end:
            stop = min(end, cursor + timedelta(days=CHUNK_DAYS))
            out.append(analysis_service.run_analysis(AnalysisRequest(
                site_ids=[site["site_id"]], start_utc=cursor, end_utc=stop, coarse_step_min=STEP_MIN,
                event_tolerance_s=EVENT_TOLERANCE_S, horizon_mode=m,
                sun_observer_height_m=request.panel_height_m, antenna_height_m=2.0), extra_sites=extra))
            cursor = stop
        return out

    try:
        runs = chunks(mode)
    except analysis_service.TerrainNotReady as exc:
        mode, note = "flat", f"Terrain was not available ({exc}); flat horizon used."
        runs = chunks(mode)

    results = [r["sites"][0] for r in runs]
    samples: list[Sample] = []
    for res in results:
        for row in res["series"]:
            if samples and float(row["et_s"]) <= samples[-1].t_s + 1e-3:
                continue  # chunk seam: the first sample repeats the previous chunk's last
            samples.append(Sample(float(row["et_s"]), row["utc"], bool(row["sun_visible_upper_limb"]),
                                  float(row["sun_elevation_deg"]), bool(row["earth_center_clear"]),
                                  None if row.get("sun_horizon_deg") is None else float(row["sun_horizon_deg"])))
    sun = merge_windows([r["sun_windows"] for r in results])
    earth = merge_windows([r["earth_windows"] for r in results])
    search_end_s = samples[0].t_s + request.search_days * 86400.0
    min_sun = check_sun_band(request, site)
    result = evaluate(samples, sun, earth, mission_days=request.mission_days,
                      require_earth=request.require_earth_at_landing,
                      max_sun_el_deg=request.max_sun_elevation_deg, search_end_s=search_end_s,
                      step_s=STEP_MIN * 60.0, min_sun_el_deg=min_sun)
    # "Verify with NASA JPL" for each best touchdown time (and the closest miss): our sky position
    # from the same run next to Horizons' answer for the same point and second.
    rows_by_utc = {row["utc"]: (res, row) for res in results for row in res["series"]}

    def _verify(utc: str | None) -> dict[str, Any] | None:
        hit = rows_by_utc.get(utc) if utc else None
        return None if hit is None else verify.verify_block(hit[0], hit[1], sun_height_m=request.panel_height_m,
                                                            antenna_height_m=2.0)

    for o in result["opportunities"]:
        o["verify"] = _verify(o["best_touchdown_utc"])
    for k in ("soonest", "best", "best_earth"):
        if result[k] is not None:
            result[k]["verify"] = _verify(result[k]["best_touchdown_utc"])
    if result["closest_miss"] is not None:
        result["closest_miss"]["verify"] = _verify(result["closest_miss"]["touchdown_utc"])
    caveats = ["Reference site: coordinates from a published source (the challenge published no site list)."
               if site.get("origin") == "reference" else None,
               "A point you picked, not a catalogue site." if site.get("origin") == "custom" else None,
               custom_point.resolution_caveat(results[0]) if mode == "terrain" else None,
               "Flat horizon: hills are not modelled; real sunrise/sunset can differ by hours "
               "(Blue Ghost 1: modelled sunset 2.4 h late)." if mode == "flat" else None,
               note,
               "Geometry only: no thermal, power, slope or hazard model; Earth in view is not a guaranteed radio link."]
    return {
        "schema_version": "1.0",
        "kind": "landing_opportunities",
        "site": {k: site.get(k) for k in ("site_id", "name", "latitude_deg", "longitude_deg", "origin")},
        "rules": {
            "mission_days": request.mission_days,
            "require_earth_at_landing": request.require_earth_at_landing,
            "max_sun_elevation_deg": request.max_sun_elevation_deg,
            "min_sun_elevation_deg": min_sun,
            "min_sun_setting": request.min_sun_elevation_deg,
            "min_sun_measured_from": "local horizon (terrain where modelled)",
            "min_sun_reference": ("auto: min(5 deg, half the highest Sun the latitude allows). 5 deg is Apollo's "
                                  "lower bound (5-14 deg; NASA SP-4214); near the pole the Sun stays below ~7 deg "
                                  "(NASA NESC, IAASS 2023), so the threshold shrinks with it"),
            "panel_height_m": request.panel_height_m,
            "text": RULE_TEXT,
            "low_sun_reference": "Apollo landings were made with the Sun 5-15 deg up "
                                 "(Apollo Lunar Surface Journal); Blue Ghost 1 landed at ~3 deg.",
            "touchdown_resolution_min": STEP_MIN,
        },
        "horizon_mode": mode,
        "terrain": custom_point.terrain_summary(results[0]) if mode == "terrain" else None,
        "search": {"start_utc": samples[0].utc, "days": request.search_days},
        **result,
        "summary": explain(result, mission_days=request.mission_days, site_name=site.get("name") or site["site_id"]),
        "caveats": [c for c in caveats if c],
        "run_ids": [r["run_id"] for r in runs],
        "compute_seconds": round(time.monotonic() - started, 2),
    }


__all__ = ["Sample", "Window", "evaluate", "explain", "merge_windows", "run_landing"]
