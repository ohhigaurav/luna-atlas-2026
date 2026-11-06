#!/usr/bin/env python3
"""How much does the terrain map's resolution change the answer? 5 m site tiles vs the 240 m regional map.

Found on 2026-11-06: at exactly Site 001's coordinates, January 2027, the 5 m tile gives 69%
sunlight with up to 8 d 21 h of darkness, and the 240 m map gives 100% (`compare2.log`).
Clicked points, the forecast and the light map all use the 240 m map, so this is measured
here, not guessed.

Method: around Site 001 and Site 004, a grid of points (radius 1 km, spacing 250 m, all inside
the 5 m tiles). Each point is analysed twice with the unchanged production pipeline, identical
except for the terrain:
  * "tile": the catalogue site's ID, so the 5 m tile plus the regional map beyond it;
  * "regional": the custom-point ID, so the 240 m regional map only.
Window 2027-01-01 to 01-31 (the forecast month), 60 min step, Sun panel and antenna at 2 m.

Fixed before the first run (2026-11-06). This is a measurement with no pass/fail. Reported per
site: the median and 90th percentile of |regional - tile| sunlit points and Earth points, the
signed median (is 240 m optimistic?), and the share of points whose sunlit % differs by more
than 10 points. Use: the custom-point caveat and the forecast label quote these numbers, and
nothing else from this run.

    .venv/bin/python tools/resolution_check.py
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

SITES = ("reference-lola-site-001", "reference-lola-site-004")
RADIUS_M, SPACING_M = 1000.0, 250.0
WINDOW = ("2027-01-01T00:00:00Z", "2027-01-31T00:00:00Z")
STEP_MIN = 60
HEIGHT_M = 2.0


def quantile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarise_pairs(pairs: list[dict[str, float]]) -> dict[str, float | int]:
    """pairs: {"sun_tile","sun_regional","earth_tile","earth_regional"} in percent."""
    ds = [p["sun_regional"] - p["sun_tile"] for p in pairs]
    de = [p["earth_regional"] - p["earth_tile"] for p in pairs]
    return {
        "n": len(pairs),
        "sun_signed_median": statistics.median(ds) if ds else float("nan"),
        "sun_abs_median": statistics.median([abs(d) for d in ds]) if ds else float("nan"),
        "sun_abs_p90": quantile([abs(d) for d in ds], 0.9),
        "sun_share_over_10": sum(abs(d) > 10.0 for d in ds) / len(ds) if ds else float("nan"),
        "sun_regional_higher": sum(d > 0.5 for d in ds),
        "sun_regional_lower": sum(d < -0.5 for d in ds),
        "earth_signed_median": statistics.median(de) if de else float("nan"),
        "earth_abs_median": statistics.median([abs(d) for d in de]) if de else float("nan"),
        "earth_abs_p90": quantile([abs(d) for d in de], 0.9),
    }


def main() -> int:
    from lunar_core import analysis_service as svc
    from lunar_core import custom_point
    from lunar_core.api_models import AnalysisRequest
    from lunar_core.location_scan import offset_point, prepare_run_context, scan_offsets

    request = AnalysisRequest(site_ids=[SITES[0]], start_utc=WINDOW[0], end_utc=WINDOW[1], coarse_step_min=STEP_MIN,
                              horizon_mode="terrain", sun_observer_height_m=HEIGHT_M, antenna_height_m=HEIGHT_M)
    offsets = scan_offsets(RADIUS_M, SPACING_M)
    report: dict[str, Any] = {"window": WINDOW, "step_min": STEP_MIN, "height_m": HEIGHT_M,
                              "radius_m": RADIUS_M, "spacing_m": SPACING_M, "sites": {}}
    started = time.monotonic()
    with svc._RUN_LOCK:
        ctx = prepare_run_context(request)
        sites = svc._load_sites()
        for site_id in SITES:
            base = sites[site_id]
            pairs: list[dict[str, Any]] = []
            for i, off in enumerate(offsets):
                lat, lon = offset_point(float(base["latitude_deg"]), float(base["longitude_deg"]), off,
                                        ctx.geometry.reference_radius_m)
                row: dict[str, Any] = {"east_m": off.east_m, "north_m": off.north_m, "lat": lat, "lon": lon}
                try:
                    for label, site in (("tile", {**base, "latitude_deg": lat, "longitude_deg": lon}),
                                        ("regional", custom_point.custom_site(lat, lon))):
                        result, _ = svc._run_one_site(site, request, ctx.geometry, start_et=ctx.start_et,
                                                      end_et=ctx.end_et, run_step_s=ctx.step_s)
                        m = result["metrics"]
                        row[f"sun_{label}"] = float(m["sunlit_percent"])
                        row[f"earth_{label}"] = float(m["dte_clear_percent"])
                        row[f"ground_{label}"] = result["terrain"].get("site_ground_elevation_m")
                except svc.AnalysisNotReady as exc:
                    row["error"] = str(exc)
                pairs.append(row)
                ok = "error" not in row
                print(f"  {site_id[-3:]} {i + 1:2d}/{len(offsets)} E{off.east_m:+6.0f} N{off.north_m:+6.0f}  "
                      + (f"sun tile {row['sun_tile']:5.1f} regional {row['sun_regional']:5.1f} | "
                         f"earth tile {row['earth_tile']:5.1f} regional {row['earth_regional']:5.1f}"
                         if ok else f"unavailable: {row['error'][:80]}"), flush=True)
            good = [p for p in pairs if "error" not in p]
            report["sites"][site_id] = {"summary": summarise_pairs(good), "points": pairs}

    print(f"\n{'site':8s} {'n':>3s} {'sun signed med':>14s} {'|d| med':>8s} {'|d| p90':>8s} {'>10 pts':>8s} "
          f"{'240m higher/lower':>18s} {'earth |d| med':>13s} {'p90':>6s}")
    for site_id, entry in report["sites"].items():
        s = entry["summary"]
        print(f"{site_id[-3:]:8s} {s['n']:3d} {s['sun_signed_median']:+14.1f} {s['sun_abs_median']:8.1f} "
              f"{s['sun_abs_p90']:8.1f} {s['sun_share_over_10']:8.0%} {s['sun_regional_higher']:>9d}/{s['sun_regional_lower']:<8d} "
              f"{s['earth_abs_median']:13.1f} {s['earth_abs_p90']:6.1f}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data" / "derived" / f"resolution_check_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport: {out.relative_to(ROOT)} ({time.monotonic() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
