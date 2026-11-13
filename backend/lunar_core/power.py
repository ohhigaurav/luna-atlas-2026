"""Sunlight available for solar power, and how slowly the Sun rises at the poles.

What this is: the sunlight power per square metre that reaches a solar panel, before the panel's
own efficiency, computed from the same per-step Sun geometry as every other answer. It is not a
power-system design: no cell efficiency, temperature, dust, battery, light reflected by nearby
terrain, or panel shadowing by the lander.

Model (per coarse step of the run, 30 min for a site check):

    E = S0 * (1 AU / r)^2 * f * g

    S0  total solar irradiance at 1 AU, 1361 W/m^2 (Kopp & Lean 2011, GRL 38, L01706: 1360.8 +/- 0.5
        at solar minimum; the ~0.1 % solar-cycle change is ignored)
    r   Sun-site distance from SPICE (the step's ``sun_range_m``)
    f   visible fraction of the Sun's disc above the local horizon, straight-edge circular segment
        (``check.disc_visible_fraction``; its time average is what Gate E compared with NASA
        Goddard's maps). Limb darkening is ignored: a thin sliver of the disc is dimmer than its
        area share, so the first minutes of a sunrise are slightly overstated.
    g   panel geometry. Two panels are reported:
        vertical, turned to face the Sun's azimuth (how polar landers mount panels): g = cos(el);
        horizontal (flat on the ground): g = max(0, sin(el)),
        with el the Sun centre's elevation above the local horizontal plane.

At the poles the Sun stays within about 1.5 degrees (plus the local horizon) of the horizontal, so a
flat panel gets a few percent of what a vertical one gets: this is why the challenge calls solar
elevation a key metric for power.

Sunrise: from a refined sunrise event (upper limb clears the horizon, event tolerance 10 s) to the
first step where at least 99% of the disc is visible. Resolution is one coarse step; when the window
or the period ends first, the time is a lower bound; when the Sun sets again first, the full disc
never cleared during that sunrise.
"""

from __future__ import annotations

import math
from typing import Any

from lunar_core.check import disc_visible_fraction
from lunar_core.sky_geometry import SUN_RADIUS_KM

SOLAR_CONSTANT_W_M2 = 1361.0
AU_M = 149_597_870_700.0  # IAU 2012 Resolution B2
FULL_DISC = 0.99
SECONDS_PER_HOUR = 3600.0


def sample_power(row: dict[str, Any]) -> dict[str, float]:
    """Disc fraction and irradiance on a vertical Sun-facing and a horizontal panel for one step."""
    r = float(row["sun_range_m"])
    el = math.radians(float(row["sun_elevation_deg"]))
    semi = math.degrees(math.asin(min(1.0, SUN_RADIUS_KM * 1000.0 / r)))
    f = disc_visible_fraction(float(row["sun_elevation_deg"]) - float(row["sun_horizon_deg"]), semi)
    flux = SOLAR_CONSTANT_W_M2 * (AU_M / r) ** 2 * f
    return {"disc_fraction": f, "vertical_w_m2": flux * math.cos(el),
            "horizontal_w_m2": flux * max(0.0, math.sin(el))}


def _first_sunrise(series: list[dict[str, Any]], samples: list[dict[str, float]],
                   sun_windows: list[dict[str, Any]], t0: float, t_end: float, step_s: float) -> dict[str, Any] | None:
    for w in sorted(sun_windows, key=lambda w: float(w["start_et_s"])):
        rise = float(w["start_et_s"])
        if w.get("start_truncated") or rise <= t0:
            continue  # the Sun was already up at the start: not a sunrise inside the period
        end = float(w["end_et_s"])
        peak = 0.0
        for row, s in zip(series, samples, strict=True):
            et = float(row["et_s"])
            if et < rise or et > end:
                continue
            peak = max(peak, s["disc_fraction"])
            if s["disc_fraction"] >= FULL_DISC:
                return {"sunrise_utc": w["start_utc"], "full_disc_utc": row["utc"],
                        "to_full_disc_h": (et - rise) / SECONDS_PER_HOUR, "lower_bound": False,
                        "full_disc_reached": True, "peak_disc_percent": 100.0 * peak,
                        "resolution_h": step_s / SECONDS_PER_HOUR}
        set_inside = not w.get("end_truncated") and end < t_end
        return {"sunrise_utc": w["start_utc"], "full_disc_utc": None,
                "to_full_disc_h": None if set_inside else (min(end, t_end) - rise) / SECONDS_PER_HOUR,
                "lower_bound": not set_inside, "full_disc_reached": False,
                "set_before_full_disc": set_inside, "peak_disc_percent": 100.0 * peak,
                "resolution_h": step_s / SECONDS_PER_HOUR}
    return None


def summarise(series: list[dict[str, Any]], sun_windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Period summary of sunlight power; None when the run has no Sun distance per step."""
    if len(series) < 2 or any(r.get("sun_range_m") is None or r.get("sun_horizon_deg") is None for r in series):
        return None
    samples = [sample_power(r) for r in series]
    t0, t_end = float(series[0]["et_s"]), float(series[-1]["et_s"])
    step_s = float(series[1]["et_s"]) - t0
    n = len(samples)
    mean_v = sum(s["vertical_w_m2"] for s in samples) / n
    mean_h = sum(s["horizontal_w_m2"] for s in samples) / n
    hours = (t_end - t0) / SECONDS_PER_HOUR
    partial = sum(1 for s in samples if 0.0 < s["disc_fraction"] < FULL_DISC)
    return {
        "mean_vertical_w_m2": mean_v,
        "mean_horizontal_w_m2": mean_h,
        "peak_vertical_w_m2": max(s["vertical_w_m2"] for s in samples),
        "energy_vertical_kwh_m2": mean_v * hours / 1000.0,
        "partial_sun_percent": 100.0 * partial / n,
        "first_sunrise": _first_sunrise(series, samples, sun_windows, t0, t_end, step_s),
        "solar_constant_w_m2": SOLAR_CONSTANT_W_M2,
        "step_h": step_s / SECONDS_PER_HOUR,
        "definition": ("sunlight reaching a panel 'panel_height_m' above the ground, before panel efficiency: "
                       "1361 W/m2 at 1 AU scaled by the Sun's distance, times the visible share of the disc, "
                       "times cos(elevation) for a vertical panel facing the Sun or sin(elevation) for a flat one; "
                       "sampled every coarse step"),
        "not_included": "cell efficiency, temperature, dust, batteries, light reflected by terrain, limb darkening",
    }


__all__ = ["AU_M", "FULL_DISC", "SOLAR_CONSTANT_W_M2", "sample_power", "summarise"]
