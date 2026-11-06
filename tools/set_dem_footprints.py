#!/usr/bin/env python3
"""Record each fine DEM tile's footprint in the manifest and let any point inside it use the tile.

Independent review finding 1 (6 Nov): DEMs were chosen by site ID, so an official site or a
clicked point on the Connecting Ridge got the 240 m map while the reference site at the same
coordinates got the 5 m tile (69% vs 100% sunlight). After this tool, a 5 m tile is used for any
site or point whose coordinate lies inside the tile. It is still used only out to its max_range_m
(8 km), with the regional map beyond that and wherever the tile has no data, exactly as for the
reference sites.

For every asset finer than --max-resolution-m (default 100 m) it:
  * opens the raster and checks that its CRS maps a test point exactly like the south-polar
    stereographic formula used everywhere (x = rho sin lon, y = rho cos lon on the manifest sphere),
    and refuses otherwise;
  * writes footprint_stereo_m = raster bounds [xmin, ymin, xmax, ymax] and select_by_footprint = true.
Nothing else in the manifest changes. --dry-run prints without writing. Changing the manifest
changes its hash, so every cached answer is recomputed (cache keys use its content).

    .venv/bin/python tools/set_dem_footprints.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/dems/manifest.json")
    parser.add_argument("--max-resolution-m", type=float, default=100.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import rasterio
    from lunar_core.cache_keys import write_atomic
    from lunar_core.terrain import _source_lunar_crs, load_dem_manifest, south_polar_stereo_m
    from pyproj import Transformer

    manifest = load_dem_manifest(args.manifest)  # validates
    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    radius = manifest.body_radius_m
    changed = 0
    for entry in raw["assets"]:
        if float(entry["native_resolution_m"]) >= args.max_resolution_m:
            continue
        with rasterio.open(ROOT / entry["relative_path"]) as ds:
            tx = Transformer.from_crs(_source_lunar_crs(radius), ds.crs, always_xy=True)
            b = ds.bounds
            cx, cy = (b.left + b.right) / 2, (b.bottom + b.top) / 2
            # Inverse of the formula at the raster centre, then forward through the raster's own CRS.
            rho = math.hypot(cx, cy)
            lat = math.degrees(2 * math.atan(rho / (2 * radius))) - 90.0
            lon = math.degrees(math.atan2(cx, cy))
            px, py = tx.transform(lon, lat)
            fx, fy = south_polar_stereo_m(lat, lon, radius)
            if math.hypot(px - fx, py - fy) > 1.0 or math.hypot(px - cx, py - cy) > 1.0:
                print(f"REFUSED {entry['asset_id']}: its CRS does not match the south-polar stereographic formula "
                      f"(off by {math.hypot(px - fx, py - fy):.1f} m)")
                return 1
            footprint = [float(b.left), float(b.bottom), float(b.right), float(b.top)]
        print(f"{entry['asset_id']}: {entry['native_resolution_m']} m, footprint x {footprint[0]:.0f}..{footprint[2]:.0f}, "
              f"y {footprint[1]:.0f}..{footprint[3]:.0f} m ({(footprint[2] - footprint[0]) / 1000:.1f} x "
              f"{(footprint[3] - footprint[1]) / 1000:.1f} km), centre {lat:.4f}, {lon % 360:.4f} E")
        if entry.get("footprint_stereo_m") != footprint or not entry.get("select_by_footprint"):
            entry["footprint_stereo_m"], entry["select_by_footprint"] = footprint, True
            changed += 1
    if args.dry_run or not changed:
        print("dry run: nothing written" if args.dry_run else "already up to date")
        return 0
    text = json.dumps(raw, indent=2) + "\n"
    from lunar_core.terrain import DEMManifest
    DEMManifest.model_validate(json.loads(text))  # never write a manifest that would not load
    write_atomic(args.manifest, text)
    print(f"wrote {args.manifest.relative_to(ROOT)} ({changed} assets now selected by location)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
