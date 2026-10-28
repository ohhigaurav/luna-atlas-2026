#!/usr/bin/env python3
"""Is the terrain that controls a site's horizon actually measured, or interpolated?

PGDA Product 78 ships, beside each 5 m surface DEM, a count map (LDEC: number of LOLA spots per
pixel) and a total height uncertainty map (TOTERR: RMS error in metres). Around 90 % of 5 m
pixels contain no LOLA spot, so small near-field bumps can be interpolation products.

For one site this prints (read-only):

1. Rings around the site (0-50, 50-100, 100-150, 150-300 m): how many pixels hold at least one
   LOLA spot, the total spots, and the median / max TOTERR.
2. For every production horizon bin at the table step: the controlling point's distance and
   TOTERR, LOLA spots within +-1 pixel of it, and atan(TOTERR / distance) in degrees, i.e. how
   far the horizon angle would move if that point were off by its RMS height error.

Indicator, not a bound: TOTERR is an absolute RMS error and errors at the site and at the
controlling point are correlated (the 100 PGDA error clones would capture that), so the angle
column is a scale for "how much could this be noise", not a confidence interval.

Example:
    python tools/dem_quality.py reference-lola-site-004 \
        --ldec data/dems/quality/Site04_final_adj_5mpp_ldec.tif \
        --toterr data/dems/quality/Site04_final_adj_5mpp_toterr.tif
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

RINGS_M = ((0.0, 50.0), (50.0, 100.0), (100.0, 150.0), (150.0, 300.0))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    import numpy as np
    import rasterio
    from lunar_core.analysis_service import _load_sites
    from lunar_core.terrain import (
        _ray_latlon_grid,
        _sample_dataset_bilinear,
        _source_lunar_crs,
        build_cached_horizon_from_dem_assets,
        preflight_dem_assets,
    )
    from pyproj import Transformer
    from rasterio.windows import Window

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_id")
    parser.add_argument("--ldec", type=Path, required=True, help="Product 78 *_5mpp_ldec.tif for this site")
    parser.add_argument("--toterr", type=Path, required=True, help="Product 78 *_5mpp_toterr.tif for this site")
    parser.add_argument("--height", type=float, default=2.0)
    parser.add_argument("--step", type=float, default=15.0, help="azimuth step of the table (deg)")
    args = parser.parse_args()

    site = _load_sites()[args.site_id]
    lat, lon = float(site["latitude_deg"]), float(site["longitude_deg"])
    manifest_path = ROOT / "data" / "dems" / "manifest.json"
    manifest, verified = preflight_dem_assets(manifest_path, ROOT, args.site_id)
    radius = manifest.body_radius_m
    fine = verified[0]
    print(f"site {args.site_id}: lat {lat}, lon {lon}; surface DEM {fine.asset.asset_id}")
    for label, path in (("ldec", args.ldec), ("toterr", args.toterr)):
        print(f"  {label:6s} {path}  sha256 {sha256(path)}")

    with rasterio.open(fine.path) as surf, rasterio.open(args.ldec) as ldec, rasterio.open(args.toterr) as err:
        for label, ds in (("ldec", ldec), ("toterr", err)):
            if ds.crs != surf.crs or tuple(ds.transform)[:6] != tuple(surf.transform)[:6] or ds.shape != surf.shape:
                print(f"REFUSED: {label} grid differs from the surface DEM (CRS, transform or shape); "
                      "wrong site file?")
                return 2
        transformer = Transformer.from_crs(_source_lunar_crs(radius), surf.crs, always_xy=True)
        x0, y0 = (float(v) for v in transformer.transform(lon, lat))
        inv = ~surf.transform
        col_c, row_c = inv.a * x0 + inv.b * y0 + inv.c, inv.d * x0 + inv.e * y0 + inv.f
        res = abs(surf.transform.a)
        half = int(math.ceil(RINGS_M[-1][1] / res)) + 2
        row0, col0 = int(math.floor(row_c)) - half, int(math.floor(col_c)) - half
        size = 2 * half + 1
        if row0 < 0 or col0 < 0 or row0 + size > surf.height or col0 + size > surf.width:
            print("REFUSED: the 300 m neighbourhood is not fully inside the tile")
            return 2
        window = Window(col0, row0, size, size)
        counts = ldec.read(1, window=window, masked=True).astype(float).filled(np.nan)
        errors = err.read(1, window=window, masked=True).astype(float).filled(np.nan)
        rows, cols = np.mgrid[row0:row0 + size, col0:col0 + size]
        dist = np.hypot((cols + 0.5 - col_c) * res, (rows + 0.5 - row_c) * res)

        print("\nLOLA coverage around the site (projected distance; scale error < 1e-5 near the pole):")
        print("   ring (m)  | pixels | with >=1 spot | spots | TOTERR median / max (m)")
        for lo, hi in RINGS_M:
            sel = (dist >= lo) & (dist < hi)
            c, e = counts[sel], errors[sel]
            measured = int(np.sum(np.nan_to_num(c) >= 1))
            print(f"  {lo:4.0f}-{hi:<4.0f}  | {int(sel.sum()):6d} | {measured:6d} ({100 * measured / sel.sum():4.1f}%) "
                  f"| {int(np.nansum(c)):5d} | {np.nanmedian(e):6.2f} / {np.nanmax(e):6.2f}")

        production, ground, _meta = build_cached_horizon_from_dem_assets(
            args.site_id, lat, lon, observer_height_m=args.height, reference_radius_m=radius,
            manifest_path=manifest_path, project_root=ROOT,
        )
        site_err = float(_sample_dataset_bilinear(err, np.array([x0]), np.array([y0]), "m")[0])
        print(f"\nTOTERR at the site itself: {site_err:.2f} m (ground {ground:.1f} m)")
        print("\nhorizon-controlling points (production horizon):")
        print("   az  | horizon | dist (m) | TOTERR (m) | spots +-1 px | atan(TOTERR/dist) (deg) | source")
        bins = {round(b.azimuth_deg, 6): b for b in production.bins}
        az = 0.0
        while az < 360.0 - 1e-9:
            b = bins.get(round(az, 6))
            az_print, az = az, az + args.step
            if b is None or b.elevation_rad is None or b.controlling_distance_m is None:
                continue
            d = b.controlling_distance_m
            plat, plon = _ray_latlon_grid(lat, lon, [az_print], [d], radius)
            px, py = transformer.transform(plon, plat)
            px, py = float(np.asarray(px).ravel()[0]), float(np.asarray(py).ravel()[0])
            pc, pr = inv.a * px + inv.b * py + inv.c, inv.d * px + inv.e * py + inv.f
            in_tile = 0 <= pc < surf.width and 0 <= pr < surf.height
            if not in_tile or d <= 0:
                print(f"  {az_print:5.0f} | {math.degrees(b.elevation_rad):7.2f} | {d:8.0f} | outside the 5 m tile "
                      "(regional DEM: no count/uncertainty map)")
                continue
            e = float(_sample_dataset_bilinear(err, np.array([px]), np.array([py]), "m")[0])
            ri, ci = int(math.floor(pr)), int(math.floor(pc))
            r_lo, c_lo = max(ri - 1, 0), max(ci - 1, 0)
            block = ldec.read(1, window=Window(c_lo, r_lo, min(ci + 2, surf.width) - c_lo,
                                               min(ri + 2, surf.height) - r_lo), masked=True)
            spots = int(np.nansum(block.astype(float).filled(0.0)))
            print(f"  {az_print:5.0f} | {math.degrees(b.elevation_rad):7.2f} | {d:8.0f} | {e:10.2f} | {spots:12d} | "
                  f"{math.degrees(math.atan2(e, d)):23.2f} | 5 m tile")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
