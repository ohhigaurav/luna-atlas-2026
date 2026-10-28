#!/usr/bin/env python3
"""Explain a terrain horizon: where is the sky blocked, by what, and how far away.

For one site this tool independently re-samples the registered DEMs along rays (it does not
reuse the horizon builder's loop) and prints, every few degrees of azimuth:

* the terrain height relative to the observer's ground at 5, 10, 20, 50, 100, 250, 500 m and
  1, 2, 5 km (is the observer in a pit, on a slope, or on a crest?);
* the horizon elevation using all terrain, and using only terrain beyond 100 m and beyond 1 km
  (how much of the blocking comes from the observer's immediate surroundings?);
* the horizon stored by the production builder at the same azimuth (cross-check);
* which DEM supplied the controlling sample.

If a recent saved run includes this site, the Sun's elevation range and the fraction of samples
blocked only by terrain within 100 m are printed too. Read-only: changes nothing.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

PROBE_DISTANCES_M = (5, 10, 20, 50, 100, 250, 500, 1_000, 2_000, 5_000)


def apparent_deg(radius: float, observer_radius: float, heights: Any, distances: Any) -> Any:
    import numpy as np

    r = radius + heights
    theta = distances / radius
    return np.degrees(np.arctan2(r * np.cos(theta) - observer_radius, r * np.sin(theta)))


def main() -> int:
    import numpy as np
    import rasterio
    from lunar_core.analysis_service import _load_sites
    from lunar_core.horizon import interpolate_horizon
    from lunar_core.terrain import (
        _ray_latlon_grid,
        _sample_dataset_bilinear,
        _source_lunar_crs,
        build_cached_horizon_from_dem_assets,
        preflight_dem_assets,
    )
    from pyproj import Transformer

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_id")
    parser.add_argument("--height", type=float, default=2.0, help="observer height above ground (m)")
    parser.add_argument("--step", type=float, default=15.0, help="azimuth step for the printed table (deg)")
    parser.add_argument("--max-range", type=float, default=200_000.0)
    args = parser.parse_args()

    site = _load_sites()[args.site_id]
    lat, lon = float(site["latitude_deg"]), float(site["longitude_deg"])
    manifest_path = ROOT / "data" / "dems" / "manifest.json"
    manifest, verified = preflight_dem_assets(manifest_path, ROOT, args.site_id)
    radius = manifest.body_radius_m
    source = _source_lunar_crs(radius)

    # Independent ray sampling: 5 m steps to 8 km, then 240 m to max range.
    distances = np.unique(np.concatenate([
        np.arange(5.0, 8_000.0, 5.0), np.arange(8_000.0, args.max_range, 240.0), [args.max_range],
    ]))
    azimuths = np.arange(0.0, 360.0, args.step)

    datasets = []
    for item in verified:  # finest first
        ds = rasterio.open(item.path)
        datasets.append((item.asset, ds, Transformer.from_crs(source, ds.crs, always_xy=True)))

    def sample(az_deg: Any, dist_m: Any) -> tuple[Any, Any]:
        heights = np.full(np.shape(dist_m), np.nan)
        which = np.full(np.shape(dist_m), "", dtype=object)
        for asset, ds, tr in datasets:
            need = ~np.isfinite(heights) & (dist_m >= asset.min_range_m) & (dist_m <= asset.max_range_m)
            if not np.any(need):
                continue
            la, lo = _ray_latlon_grid(lat, lon, np.broadcast_to(az_deg, dist_m.shape)[need], dist_m[need], radius)
            x, y = tr.transform(lo, la)
            got = _sample_dataset_bilinear(ds, np.asarray(x), np.asarray(y), asset.elevation_units)
            idx = np.flatnonzero(need)
            ok = np.isfinite(got)
            heights.flat[idx[ok]] = got[ok]
            which.flat[idx[ok]] = asset.asset_id
        return heights, which

    origin, origin_asset = sample(np.array(0.0), np.array([0.0]))
    ground = float(origin[0])
    observer_radius = radius + ground + args.height
    print(f"site {args.site_id}: lat {lat}, lon {lon}, ground {ground:.2f} m ({origin_asset[0]}), "
          f"observer height {args.height} m")

    production, _g, _meta = build_cached_horizon_from_dem_assets(
        args.site_id, lat, lon, observer_height_m=args.height, reference_radius_m=radius,
        max_range_m=args.max_range, manifest_path=manifest_path, project_root=ROOT,
    )

    def production_deg(az: float) -> float:
        value = interpolate_horizon(production, az).elevation_rad
        return float("nan") if value is None else math.degrees(value)

    header = "  az | " + " ".join(f"{d if d < 1000 else str(d // 1000) + 'k':>6}" for d in PROBE_DISTANCES_M)
    print("\nterrain height relative to observer ground (m) at distance:")
    print(header)
    rows = []
    for az in azimuths:
        h, which = sample(np.array(az), distances)
        ang = apparent_deg(radius, observer_radius, h, distances)
        valid = np.isfinite(ang)
        probes = []
        for d in PROBE_DISTANCES_M:
            i = int(np.argmin(np.abs(distances - d)))
            probes.append(h[i] - ground)
        print(f" {az:4.0f} | " + " ".join(f"{p:6.1f}" for p in probes))

        def horizon_beyond(min_d: float, ang: Any = ang, valid: Any = valid) -> tuple[float, float]:
            sel = valid & (distances >= min_d)
            k = int(np.argmax(np.where(sel, ang, -np.inf)))
            return float(ang[k]), float(distances[k])

        all_el, all_d = horizon_beyond(0.0)
        k_all = int(np.argmax(np.where(valid, ang, -np.inf)))
        rows.append((az, all_el, all_d, which[k_all], *horizon_beyond(100.0), *horizon_beyond(1_000.0),
                     production_deg(az)))

    print("\nhorizon elevation (deg) and controlling distance:")
    print("  az |   all terrain (dist, DEM)                  | beyond 100 m      | beyond 1 km       | production")
    for az, el, d, asset, el100, d100, el1k, d1k, prod in rows:
        print(f" {az:4.0f} | {el:6.2f} at {d:8.0f} m ({asset:28s}) | {el100:6.2f} at {d100:7.0f} | "
              f"{el1k:6.2f} at {d1k:7.0f} | {prod:6.2f}")

    runs = sorted(glob.glob(str(ROOT / "data" / "runs" / "*.json")), key=os.path.getmtime, reverse=True)
    for path in runs[:20]:
        run = json.loads(Path(path).read_text(encoding="utf-8"))
        match = [s for s in run.get("sites", []) if s.get("site", {}).get("site_id") == args.site_id
                 and run.get("settings", {}).get("horizon_mode") == "terrain"]
        if not match:
            continue
        series = match[0]["series"]
        sun_el = [x["sun_elevation_deg"] for x in series]
        az_list = [x["sun_azimuth_deg"] for x in series]
        near_only = 0
        blocked = 0
        for x in series:
            if x["sun_margin_deg"] > 0:
                continue
            blocked += 1
            az = x["sun_azimuth_deg"]
            nearest = min(rows, key=lambda r: abs(((r[0] - az + 180) % 360) - 180))
            if x["sun_elevation_deg"] + 0.266 > nearest[4]:  # would be lit if terrain within 100 m were ignored
                near_only += 1
        print(f"\nlatest terrain run {run['run_id']}: Sun elevation {min(sun_el):.2f} .. {max(sun_el):.2f} deg, "
              f"Sun azimuth {min(az_list):.0f} .. {max(az_list):.0f} deg")
        print(f"  samples in darkness: {blocked}/{len(series)}; of those, dark only because of terrain "
              f"within 100 m (approx., table azimuth step): {near_only}")
        break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
