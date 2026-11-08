"""Compare landing sites and dates side by side (the challenge's core ask).

"Compare landing sites and dates quickly ... time remaining before sunset or Earthset ... solar
elevation, duration of sunlight, Earth visibility windows" (challenge statement, 2026).

For each place (catalogue site or clicked point), the unchanged one-button check
(``lunar_core.check``, cached) runs from ``at_utc`` for ``days``. This module only restates its
windows and series as one comparable row:

* **now**, at ``at_utc``: Sun and Earth elevation and azimuth, and whether each is up (Sun upper
  limb above the terrain horizon; Earth's centre above it);
* **next Sun event** (sunset if up, sunrise if down) and **next Earth event** (Earthset or
  Earthrise), with the time to it. If the period ends first, the time is a lower bound and is
  flagged ``lower_bound``;
* **period metrics**: sunlit %, Earth %, both %, longest darkness, longest time without Earth;
* the Horizons verify links of the check.

``leaders`` names the best place per metric; ties are listed together. Nothing is weighted or
combined into a score: the user decides what matters.
"""
from __future__ import annotations

from typing import Any

from lunar_core import analysis_service, check, custom_point
from lunar_core.api_models import CheckRequest, CompareRequest, PlaceRef

SECONDS_PER_HOUR = 3600.0


def next_event(windows: list[dict[str, Any]], t0: float, period_end: float, *,
               up_name: str, down_name: str) -> dict[str, Any]:
    """Up/down at t0 and the next change, from refined visibility windows (ET seconds).

    A window that ends at the end of the analysed period is "end_truncated": the real event is
    later, so the time to it is a lower bound.
    """
    for w in sorted(windows, key=lambda w: float(w["start_et_s"])):
        start, end = float(w["start_et_s"]), float(w["end_et_s"])
        if start <= t0 < end or (start <= t0 + 1e-6 and t0 < end):
            return {"up": True, "event": up_name, "utc": w["end_utc"],
                    "in_h": (end - t0) / SECONDS_PER_HOUR, "lower_bound": bool(w.get("end_truncated"))}
        if start > t0:
            return {"up": False, "event": down_name, "utc": w["start_utc"],
                    "in_h": (start - t0) / SECONDS_PER_HOUR, "lower_bound": False}
    return {"up": False, "event": down_name, "utc": None, "in_h": (period_end - t0) / SECONDS_PER_HOUR,
            "lower_bound": True, "none_in_period": True}


terrain_summary = custom_point.terrain_summary  # moved there so check and landing share it


def _check_request(place: PlaceRef, request: CompareRequest) -> CheckRequest:
    return CheckRequest(site_id=place.site_id, latitude_deg=place.latitude_deg, longitude_deg=place.longitude_deg,
                        start_utc=request.at_utc, days=request.days, panel_height_m=request.panel_height_m)


def _row(result: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    site = run["sites"][0]
    first = site["series"][0]
    t0 = float(first["et_s"])
    period_end = float(site["series"][-1]["et_s"])
    m = site["metrics"]
    sun_next = next_event(site["sun_windows"], t0, period_end, up_name="sunset", down_name="sunrise")
    earth_next = next_event(site["earth_windows"], t0, period_end, up_name="earthset", down_name="earthrise")
    return {
        "site": result["site"],
        "horizon_mode": result["chosen_settings"]["horizon_mode"],
        "terrain": terrain_summary(site),
        "now": {
            "utc": first["utc"],
            "sun": {"up": bool(first["sun_visible_upper_limb"]), "elevation_deg": float(first["sun_elevation_deg"]),
                    "azimuth_deg": float(first["sun_azimuth_deg"]), "horizon_deg": float(first["sun_horizon_deg"])},
            "earth": {"up": bool(first["earth_center_clear"]), "elevation_deg": float(first["earth_elevation_deg"]),
                      "azimuth_deg": float(first["earth_azimuth_deg"]), "horizon_deg": float(first["earth_horizon_deg"])},
        },
        "sun_next": sun_next,
        "earth_next": earth_next,
        "period": {
            "sunlit_percent": float(m["sunlit_percent"]),
            "sun_disc_percent": check.sun_disc_percent(site.get("series") or []),
            "earth_percent": float(m["dte_clear_percent"]),
            "both_percent": float(m["both_percent"]),
            "longest_darkness_h": float(m["longest_darkness"]["duration_s"]) / SECONDS_PER_HOUR,
            "longest_darkness_lower_bound": bool(m["longest_darkness"].get("truncated_start")
                                                 or m["longest_darkness"].get("truncated_end")),
            "longest_earth_gap_h": float(m["longest_dte_gap"]["duration_s"]) / SECONDS_PER_HOUR,
            "longest_earth_gap_lower_bound": bool(m["longest_dte_gap"].get("truncated_start")
                                                  or m["longest_dte_gap"].get("truncated_end")),
        },
        "limits_all_pass": bool(result["summary"]["limits"]["all_pass"]),
        # Which limit fails, not just whether one does (default mission profile, same as /api/check).
        "limits": result["summary"]["limits"]["checks"],
        "caveats": result["summary"]["caveats"],
        "verify": result.get("verify"),
        "run_id": result["run_id"],
        "cache_hit": bool(result.get("cache_hit")),
    }


def _key(row: dict[str, Any]) -> str:
    s = row["site"]
    return str(s["site_id"]) if s.get("origin") != "custom" else f"{s['latitude_deg']},{s['longitude_deg']}"


def leaders(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Best place(s) per metric, by row key; ties listed together. Up-now metrics only among places that are up."""
    def best(values: dict[str, float], higher: bool = True) -> list[str]:
        if not values:
            return []
        target = max(values.values()) if higher else min(values.values())
        return [k for k, v in values.items() if abs(v - target) < 1e-9]

    keyed = {_key(r): r for r in rows}
    return {
        # Disc-averaged sunlight (what a panel gets) when present; "any part of the Sun" otherwise.
        "most_sunlight": best({k: (r["period"]["sun_disc_percent"] if r["period"].get("sun_disc_percent") is not None
                                   else r["period"]["sunlit_percent"]) for k, r in keyed.items()}),
        "most_earth": best({k: r["period"]["earth_percent"] for k, r in keyed.items()}),
        "most_both": best({k: r["period"]["both_percent"] for k, r in keyed.items()}),
        "shortest_darkness": best({k: r["period"]["longest_darkness_h"] for k, r in keyed.items()}, higher=False),
        "longest_until_sunset": best({k: r["sun_next"]["in_h"] for k, r in keyed.items() if r["sun_next"]["up"]}),
        "longest_until_earthset": best({k: r["earth_next"]["in_h"] for k, r in keyed.items() if r["earth_next"]["up"]}),
        # Height above the local (terrain) horizon at the Sun's azimuth, the number the table shows.
        "highest_sun_now": best({k: r["now"]["sun"]["elevation_deg"] - r["now"]["sun"].get("horizon_deg", 0.0)
                                 for k, r in keyed.items() if r["now"]["sun"]["up"]}),
    }


def run_compare(request: CompareRequest) -> dict[str, Any]:
    rows = []
    for place in request.places:
        result = check.run_check(_check_request(place, request))
        run = analysis_service.load_saved_run(result["run_id"])
        rows.append({"key": None, **_row(result, run)})
    for r in rows:
        r["key"] = _key(r)
    if len({r["key"] for r in rows}) != len(rows):
        raise ValueError("the same place is listed twice")
    return {
        "schema_version": "1.0",
        "kind": "site_comparison",
        "at_utc": rows[0]["now"]["utc"],
        "days": request.days,
        "panel_height_m": request.panel_height_m,
        "antenna_height_m": check.ANTENNA_HEIGHT_M,
        "rows": rows,
        "leaders": leaders(rows),
        "rules": {
            "sun_up": "Sun's upper limb above the local horizon (terrain where available) from the panel height",
            "earth_up": "Earth's centre above the local horizon from the antenna height; line of sight, not a radio link",
            "lower_bound": "the event lies beyond the analysed period, so the time to it is at least this long",
            "leaders": "best value per metric; no weighting or combined score",
        },
    }


__all__ = ["leaders", "next_event", "run_compare"]
