#!/usr/bin/env python3
"""Compare modelled sunlight with LROC's *observed* south-pole illumination map.

Reference: LROC RDR WAC_POLE_ILL_PCT_SOUTH_100M (Speyerer & Robinson 2013): for each 100 m pixel
from 88 to 90 S, the percentage of 3807 WAC images, acquired 2010-02-15 to 2011-02-05, in which
the pixel was illuminated. This is an observation, not a model, so it is independent of LOLA,
SPICE and our horizon code.

For every reference site inside the map this tool:
  1. reads the map value at the site's pixel and the min/max over the 3x3 neighbourhood
     (300 m; shows how much illumination varies at pixel scale);
  2. runs the production analysis over the same period (split into <= 60-day chunks, the API
     limit) and combines the chunks weighted by duration;
  3. reports two modelled fractions from the uniform sample series: any part of the Sun above
     the local horizon (upper limb) and Sun centre above the local horizon.

Acceptance criterion, fixed before the first run (2026-11-01):
  * a site is SCORED only if its 3x3 neighbourhood spread (max - min) is <= 10 percentage
    points; otherwise it is reported as UNSCORED (pixel-scale ambiguity dominates);
  * a scored site PASSES if |modelled upper-limb % - WAC centre-pixel %| <= 10 percentage points.
Known differences that make exact agreement impossible: point vs 100 m pixel; the WAC
"illuminated" threshold is not a Sun-limb geometry; WAC sampling is irregular in time; a 2 m
observer height; terrain resolution (5 m tiles where registered, else 240 m).

    .venv/bin/python tools/compare_wac_illumination.py [--map PATH] [--mode terrain|flat]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

DEFAULT_MAP = ROOT / "data/reference/illumination/WAC_POLE_ILL_PCT_SOUTH_100M.IMG"
WAC_START = datetime(2010, 2, 15, tzinfo=UTC)
WAC_END = datetime(2011, 2, 5, tzinfo=UTC)
MOON_RADIUS_M = 1_737_400.0
MAX_CHUNK_DAYS = 59
SPREAD_LIMIT_PP = 10.0
PASS_LIMIT_PP = 10.0
SITES = [
    "reference-lola-site-001", "reference-lola-site-004", "reference-shackleton-crater",
    "reference-de-gerlache-crater", "reference-sverdrup-crater", "reference-henson-crater",
]


def stereographic_south(lat_deg: float, lon_deg: float, radius_m: float = MOON_RADIUS_M) -> tuple[float, float]:
    """Spherical south-polar stereographic, true scale at the pole (same as tools/review_dem.py)."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    rho = 2.0 * radius_m * math.tan(math.pi / 4.0 + lat / 2.0)
    return rho * math.sin(lon), rho * math.cos(lon)


def check_crs(wkt: str) -> None:
    """Fail closed unless the map uses the projection the pixel lookup assumes."""
    def param(name: str) -> float | None:
        m = re.search(rf'PARAMETER\["{name}",\s*([-0-9.eE+]+)\]', wkt)
        return float(m.group(1)) if m else None
    radius = re.search(r'SPHEROID\["[^"]*",\s*([0-9.eE+]+)', wkt)
    problems = []
    if "Polar_Stereographic" not in wkt and "Polar Stereographic" not in wkt:
        problems.append("not polar stereographic")
    if radius is None or abs(float(radius.group(1)) - MOON_RADIUS_M) > 0.5:
        problems.append(f"sphere radius {radius.group(1) if radius else '?'} != {MOON_RADIUS_M}")
    if param("latitude_of_origin") != -90.0:
        problems.append(f"latitude_of_origin {param('latitude_of_origin')} != -90")
    if param("central_meridian") not in (0.0, None):
        problems.append(f"central_meridian {param('central_meridian')} != 0")
    for name in ("false_easting", "false_northing"):
        if param(name) not in (0.0, None):
            problems.append(f"{name} {param(name)} != 0")
    if problems:
        raise ValueError("WAC map projection differs from the assumed one: " + "; ".join(problems))


def pixel_stats(array: Any, mask: Any, inverse_transform: Callable[[float, float], tuple[float, float]],
                lat: float, lon: float) -> dict[str, Any]:
    """Centre pixel value and 3x3 min/max at a site. ``inverse_transform`` maps x, y -> col, row."""
    x, y = stereographic_south(lat, lon)
    col_f, row_f = inverse_transform(x, y)
    col, row = int(math.floor(col_f)), int(math.floor(row_f))
    height, width = array.shape
    if not (1 <= row < height - 1 and 1 <= col < width - 1):
        return {"inside": False, "x_m": x, "y_m": y}
    window = [(r, c) for r in range(row - 1, row + 2) for c in range(col - 1, col + 2)]
    values = [float(array[r][c]) for r, c in window if not mask[r][c]]
    centre_ok = not mask[row][col]
    return {
        "inside": True, "x_m": x, "y_m": y, "row": row, "col": col,
        "wac_centre_pct": max(0.0, float(array[row][col])) if centre_ok else None,
        "wac_3x3_min_pct": max(0.0, min(values)) if values else None,
        "wac_3x3_max_pct": max(0.0, max(values)) if values else None,
        "wac_3x3_valid": len(values),
    }


def chunks(start: datetime, end: datetime, max_days: int = MAX_CHUNK_DAYS) -> list[tuple[datetime, datetime]]:
    out, cursor = [], start
    while cursor < end:
        stop = min(end, cursor + timedelta(days=max_days))
        out.append((cursor, stop))
        cursor = stop
    return out


def series_fractions(series: Sequence[dict[str, Any]]) -> tuple[float, float, int]:
    """Upper-limb and centre visibility fractions from a uniform sample series."""
    if not series:
        raise ValueError("empty series")
    limb = sum(1 for s in series if s["sun_visible_upper_limb"])
    centre = sum(1 for s in series if s["sun_elevation_deg"] - s["sun_horizon_deg"] > 0)
    n = len(series)
    return limb / n, centre / n, n


def modelled(site_ids: list[str], mode: str, run: Callable[..., dict[str, Any]],
             step_min: int = 30) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Run the analysis chunk by chunk and combine per site, weighting each chunk by its duration."""
    acc: dict[str, dict[str, float]] = {s: {"limb": 0.0, "centre": 0.0, "metric": 0.0, "dur": 0.0} for s in site_ids}
    run_ids: list[str] = []
    for start, stop in chunks(WAC_START, WAC_END):
        duration = (stop - start).total_seconds()
        for batch in (site_ids[i:i + 4] for i in range(0, len(site_ids), 4)):
            result = run(site_ids=batch, horizon_mode=mode,
                         start_utc=start.isoformat().replace("+00:00", "Z"),
                         end_utc=stop.isoformat().replace("+00:00", "Z"),
                         coarse_step_min=step_min, event_tolerance_s=10.0)
            run_ids.append(result["run_id"])
            for site in result["sites"]:
                sid = site["site"]["site_id"]
                limb, centre, _ = series_fractions(site["series"])
                a = acc[sid]
                a["limb"] += limb * duration
                a["centre"] += centre * duration
                a["metric"] += float(site["metrics"]["sunlit_percent"]) / 100.0 * duration
                a["dur"] += duration
            print(f"  {start.date()} -> {stop.date()}  {', '.join(batch)}  run {result['run_id']}", flush=True)
    out = {sid: {"model_limb_pct": 100 * a["limb"] / a["dur"], "model_centre_pct": 100 * a["centre"] / a["dur"],
                 "model_windows_sunlit_pct": 100 * a["metric"] / a["dur"]} for sid, a in acc.items()}
    return out, run_ids


def verdict(row: dict[str, Any]) -> str:
    if not row.get("inside") or row.get("wac_centre_pct") is None:
        return "OUTSIDE/NODATA"
    spread = row["wac_3x3_max_pct"] - row["wac_3x3_min_pct"]
    if spread > SPREAD_LIMIT_PP:
        return "UNSCORED"
    return "PASS" if abs(row["model_limb_pct"] - row["wac_centre_pct"]) <= PASS_LIMIT_PP else "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--mode", choices=["terrain", "flat"], default="terrain")
    parser.add_argument("--step-min", type=int, default=30)
    args = parser.parse_args()

    import rasterio
    from lunar_core.analysis_service import run_analysis
    from lunar_core.api_models import AnalysisRequest
    from lunar_core.provenance import sha256_file
    from lunar_core.references import load_reference_catalogue

    sites = {s.site_id: s for s in load_reference_catalogue().sites}
    with rasterio.open(args.map) as ds:
        check_crs(ds.crs.to_wkt())
        if abs(ds.transform.a - 100.0) > 1e-6 or abs(ds.transform.e + 100.0) > 1e-6:
            raise ValueError(f"expected 100 m pixels, got {ds.transform}")
        data = ds.read(1, masked=True)
        inverse = ~ds.transform
        array, mask = data.data, data.mask if data.mask.shape else (data.data != data.data)
        rows: dict[str, dict[str, Any]] = {}
        for sid in SITES:
            s = sites[sid]
            rows[sid] = {"site_id": sid, "latitude_deg": s.latitude_deg, "longitude_deg": s.longitude_deg,
                         **pixel_stats(array, mask, lambda x, y: inverse * (x, y), s.latitude_deg, s.longitude_deg)}
    inside = [sid for sid in SITES if rows[sid]["inside"]]
    print(f"WAC map {args.map.name}: {len(inside)}/{len(SITES)} sites inside; modelling {WAC_START.date()} -> {WAC_END.date()} ({args.mode})")

    def run(**kw: Any) -> dict[str, Any]:
        return run_analysis(AnalysisRequest(**kw))

    model, run_ids = modelled(inside, args.mode, run, args.step_min)
    for sid in inside:
        rows[sid].update(model[sid])

    print(f"\n{'site':30s} {'WAC%':>6s} {'3x3 range':>13s} {'model limb%':>11s} {'centre%':>8s} {'diff':>6s}  verdict")
    for sid in SITES:
        r = rows[sid]
        r["verdict"] = verdict(r)
        if r["verdict"] == "OUTSIDE/NODATA":
            print(f"{sid:30s} {'-':>6s} {'-':>13s} {'-':>11s} {'-':>8s} {'-':>6s}  {r['verdict']}")
            continue
        diff = r["model_limb_pct"] - r["wac_centre_pct"]
        print(f"{sid:30s} {r['wac_centre_pct']:6.1f} {r['wac_3x3_min_pct']:6.1f}-{r['wac_3x3_max_pct']:<6.1f} "
              f"{r['model_limb_pct']:11.1f} {r['model_centre_pct']:8.1f} {diff:+6.1f}  {r['verdict']}")

    out_dir = ROOT / "data/derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "created_utc": stamp, "mode": args.mode, "step_min": args.step_min,
        "period": [WAC_START.isoformat(), WAC_END.isoformat()],
        "map": str(args.map.relative_to(ROOT)) if args.map.is_relative_to(ROOT) else str(args.map),
        "map_sha256": sha256_file(args.map),
        "criterion": {"spread_limit_pp": SPREAD_LIMIT_PP, "pass_limit_pp": PASS_LIMIT_PP},
        "sites": [rows[s] for s in SITES], "run_ids": run_ids,
    }
    path = out_dir / f"wac_comparison_{args.mode}_{stamp}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
