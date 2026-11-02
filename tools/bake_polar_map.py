#!/usr/bin/env python3
"""Bake the south-pole "light and link" map: daily sunlight and Earth-in-view for a whole year.

For every point of a square grid around the south pole, the tool builds that point's own terrain
horizon (production ``build_horizon_from_dem_assets``, production defaults, regional 240 m DEM)
and tests one Moon-centred Sun and Earth track (``/api/sky-geometry``, 60 min) against it:

  * sun:   Sun upper limb above the local horizon (the analysis definition);
  * earth: Earth's centre above the local horizon.

It stores, per point and per day, the percentage of hours with each, as two uint8 rasters the
3D app can upload as textures (day d is plane d, row-major, row 0 = north edge = +y).

    .venv/bin/python tools/bake_polar_map.py [--year 2027] [--half-width-km 100] [--spacing-km 4]
                                             [--height 2] [--out frontend/app/public/data/polar_map]

Cost: one horizon per grid point, about 4 s each on a development laptop (2601 points at the defaults,
about 3 h). Resumable: finished points go to a checkpoint, so Ctrl+C and rerun is safe.

What the map is and is not: daily percentages at grid points 4 km apart, from the 240 m DEM, with
the observer 2 m above the ground. It is not a pixel average, not landing-safety information, and
the many-point WAC test (validation/evidence/wac_illumination_2026-11-01.md) found the model's
sunlight biased low at ground level. Values change with observer height. The app must say so.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.wac_manypoint import inverse_stereographic_south  # noqa: E402

SUN_RADIUS_M = 695_700_000.0
SITE_ID = "polar-map-grid"  # matches only the regional ("*") DEM: one resolution across the map


def grid(half_width_km: float, spacing_km: float) -> tuple[int, list[tuple[float, float]]]:
    """Square grid centred on the pole in south-polar stereographic x/y (m), row 0 = +y (north edge)."""
    n = int(round(2 * half_width_km / spacing_km)) + 1
    step = spacing_km * 1000.0
    half = (n - 1) / 2.0
    points = [((c - half) * step, (half - r) * step) for r in range(n) for c in range(n)]
    return n, points


def margins(unit: Any, distance_km: Any, lat_deg: float, lon_deg: float, observer_radius_m: float,
            horizon_az_deg: Any, horizon_el_rad: Any, *, add_semidiameter: bool, body_radius_m: float = 0.0) -> Any:
    """Elevation (+ semidiameter if asked) minus local horizon, rad, for a Moon-centred track."""
    import numpy as np

    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)])
    rel = unit * (distance_km[:, None] * 1000.0) - up * observer_radius_m
    rng = np.linalg.norm(rel, axis=1)
    elevation = np.arcsin(np.clip(rel @ up / rng, -1.0, 1.0))
    azimuth = np.degrees(np.arctan2(rel @ east, rel @ north)) % 360.0
    horizon = np.interp(azimuth, horizon_az_deg, horizon_el_rad, period=360.0)
    extra = np.arcsin(body_radius_m / rng) if add_semidiameter else 0.0
    return elevation + extra - horizon


def daily_percent(flags: Any, samples_per_day: int, days: int) -> list[int]:
    """Percentage (0-100, rounded) of True per day; the series must hold days * samples_per_day + 1 samples."""
    import numpy as np

    body = np.asarray(flags[: days * samples_per_day], dtype=float).reshape(days, samples_per_day)
    return [int(v) for v in np.rint(body.mean(axis=1) * 100.0)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--year", type=int, default=2027)
    parser.add_argument("--half-width-km", type=float, default=100.0)
    parser.add_argument("--spacing-km", type=float, default=4.0)
    parser.add_argument("--height", type=float, default=2.0)
    parser.add_argument("--out", type=Path, default=ROOT / "frontend/app/public/data/polar_map")
    args = parser.parse_args()

    import numpy as np
    from lunar_core import __version__
    from lunar_core.analysis_service import DEM_MANIFEST, PROJECT_ROOT, run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest
    from lunar_core.terrain import HORIZON_ALGORITHM_VERSION, build_horizon_from_dem_assets

    start = datetime(args.year, 1, 1, tzinfo=UTC)
    end = datetime(args.year + 1, 1, 1, tzinfo=UTC)
    days = (end - start).days
    print(f"Sun/Earth track {start.date()} -> {end.date()}, 60 min ...", flush=True)
    sky = run_sky_geometry(SkyGeometryRequest(start_utc=start, end_utc=end, step_min=60))
    s = sky["series"]
    sun_u, sun_d = np.asarray(s["sun"]["unit"], float), np.asarray(s["sun"]["distance_km"], float)
    earth_u, earth_d = np.asarray(s["earth"]["unit"], float), np.asarray(s["earth"]["distance_km"], float)
    radius_m = float(sky["moon_reference_radius_m"])
    if len(s["utc"]) != days * 24 + 1:
        raise SystemExit(f"expected {days * 24 + 1} hourly samples, got {len(s['utc'])}")

    n, points = grid(args.half_width_km, args.spacing_km)
    settings = {"year": args.year, "half_width_km": args.half_width_km, "spacing_km": args.spacing_km,
                "height_m": args.height, "horizon_algorithm": HORIZON_ALGORITHM_VERSION,
                "kernel_manifest_sha256": sky["provenance"]["kernel_manifest_sha256"]}
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    args.out.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out / f".checkpoint_{key}.jsonl"
    done: dict[int, dict[str, Any]] = {}
    if checkpoint.is_file():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[rec["i"]] = rec
    todo = [i for i in range(len(points)) if i not in done]
    print(f"{n} x {n} grid, {args.spacing_km:g} km spacing: {len(points)} points, {len(todo)} to compute", flush=True)

    started, computed = time.monotonic(), 0
    with checkpoint.open("a", encoding="utf-8") as sink:
        for i in todo:
            x, y = points[i]
            lat, lon = inverse_stereographic_south(x, y)
            reason = None
            try:
                horizon, ground, _meta = build_horizon_from_dem_assets(
                    SITE_ID, lat, lon, observer_height_m=args.height, reference_radius_m=radius_m,
                    manifest_path=DEM_MANIFEST, project_root=PROJECT_ROOT)
                if not all(b.coverage_status == "complete" and b.elevation_rad is not None for b in horizon.bins):
                    reason = "incomplete horizon (DEM coverage)"
            except ValueError as exc:  # DEMManifestError subclasses ValueError
                reason = str(exc)
            if reason is not None:
                rec = {"i": i, "lat": lat, "lon": lon, "ok": False, "reason": reason}
            else:
                az = np.array([b.azimuth_deg for b in horizon.bins])
                el = np.array([b.elevation_rad for b in horizon.bins])
                r_obs = radius_m + ground + args.height
                sun = margins(sun_u, sun_d, lat, lon, r_obs, az, el, add_semidiameter=True, body_radius_m=SUN_RADIUS_M) > 0
                earth = margins(earth_u, earth_d, lat, lon, r_obs, az, el, add_semidiameter=False) > 0
                rec = {"i": i, "lat": lat, "lon": lon, "ok": True, "ground_m": ground,
                       "sun": daily_percent(sun, 24, days), "earth": daily_percent(earth, 24, days)}
            sink.write(json.dumps(rec) + "\n")
            sink.flush()
            done[i] = rec
            computed += 1
            if computed % 25 == 0 or computed == len(todo):
                rate = (time.monotonic() - started) / computed
                print(f"  {computed}/{len(todo)} points, ~{(len(todo) - computed) * rate / 60:.0f} min left", flush=True)

    sun_cube = np.full((days, n, n), 255, dtype=np.uint8)  # 255 = no data
    earth_cube = np.full((days, n, n), 255, dtype=np.uint8)
    ground = np.full((n, n), np.nan, dtype=np.float32)
    for i, rec in done.items():
        r, c = divmod(i, n)
        if rec["ok"]:
            sun_cube[:, r, c] = rec["sun"]
            earth_cube[:, r, c] = rec["earth"]
            ground[r, c] = rec["ground_m"]
    (args.out / "sun_daily_pct.u8").write_bytes(sun_cube.tobytes())
    (args.out / "earth_daily_pct.u8").write_bytes(earth_cube.tobytes())
    header = {
        "schema_version": "1.0", "kind": "polar_light_link_map",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "software_version": __version__, "settings": settings,
        "grid": {"size": n, "spacing_m": args.spacing_km * 1000.0, "projection": ("south polar stereographic, sphere R=1737400 m, true scale at the pole; "
                                "x = rho*sin(lon), y = rho*cos(lon): +y toward 0 E, +x toward 90 E"),
                 "x_min_m": points[0][0], "y_max_m": points[0][1], "row_0": "north edge (+y)"},
        "days": days, "first_day_utc": start.date().isoformat(),
        "files": {"sun": "sun_daily_pct.u8", "earth": "earth_daily_pct.u8"},
        "encoding": "uint8 percent of hourly samples per UTC day; 255 = no data; layout [day][row][col]",
        "definitions": {"sun": "Sun upper limb above the local terrain horizon",
                        "earth": "Earth centre above the local terrain horizon"},
        "points_without_data": sum(1 for rec in done.values() if not rec["ok"]),
        "ground_m_range": [float(np.nanmin(ground)), float(np.nanmax(ground))] if np.isfinite(ground).any() else None,
        "limits": ("Grid points, not area averages; 240 m regional DEM; observer above ground as set; ground-level "
                   "sunlight was biased low against LROC WAC (many-point test). Not landing-safety information."),
    }
    (args.out / "map.json").write_text(json.dumps(header, indent=2), encoding="utf-8")
    print(f"wrote {args.out}: {n}x{n} x {days} days, "
          f"{(sun_cube.nbytes + earth_cube.nbytes) / 1e6:.1f} MB raw, {header['points_without_data']} points without data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
