#!/usr/bin/env python3
"""Gate C evidence for registered DEMs: CRS contract and vertical datum.

Runs objective checks on every DEM in ``data/dems/manifest.json`` and writes an evidence report.
It never changes the manifest unless ``--attest`` is given *and* every check passes; then it sets
``crs_contract_verified`` / ``vertical_datum_verified`` with notes that cite the report hash.

Checks per asset
  1. File SHA-256 matches the manifest.
  2. Projection, functionally: lunar lon/lat -> raster CRS with pyproj must equal an independent
     hand implementation of the south-polar stereographic projection on the manifest sphere
     (rho = 2 R tan(pi/4 + lat/2), x = rho sin lon, y = rho cos lon) to < 1 cm. This single test
     catches a wrong radius, projection, true-scale latitude, axis order or longitude direction.
  3. Round trip lon/lat -> x/y -> lon/lat < 1e-9 deg.
  4. Pixel size equals the manifest's native resolution.
  5. Heights plausible for the Moon relative to a 1737.4 km sphere: all valid samples within
     [-10 km, +11 km] (the global LOLA range is about -9.1 to +10.8 km).
  6. Product consistency: each finer asset is compared with the coarsest (regional) asset on a
     grid inside the finer tile. Heights relative to different datums would show a large
     constant offset; the median difference must be within 5 m.

Publisher statement (PGDA product 78): grids are south-polar stereographic X/Y in metres,
surface height Z in metres, MOON_ME frame of DE421. The page does not name the height reference;
"metres above the 1737.4 km sphere" is inferred from checks 2, 5 and 6 and is recorded as such.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from lunar_core.provenance import sha256_file  # noqa: E402

HEIGHT_RANGE_M = (-10_000.0, 11_000.0)
MAX_PROJECTION_ERROR_M = 0.01
MAX_ROUNDTRIP_ERROR_DEG = 1e-9
MAX_MEDIAN_PRODUCT_DIFF_M = 5.0


def stereographic_south(lat_deg: Any, lon_deg: Any, radius_m: float) -> tuple[Any, Any]:
    """Independent spherical south-polar stereographic forward projection (true scale at pole)."""
    import numpy as np

    lat = np.radians(np.asarray(lat_deg, dtype=np.float64))
    lon = np.radians(np.asarray(lon_deg, dtype=np.float64))
    rho = 2.0 * radius_m * np.tan(np.pi / 4.0 + lat / 2.0)
    return rho * np.sin(lon), rho * np.cos(lon)


def stereographic_south_inverse(x: Any, y: Any, radius_m: float) -> tuple[Any, Any]:
    import numpy as np

    rho = np.hypot(x, y)
    lat = 2.0 * np.arctan(rho / (2.0 * radius_m)) - np.pi / 2.0
    lon = np.arctan2(x, y)
    return np.degrees(lat), np.degrees(lon)


def interior_grid(bounds: tuple[float, float, float, float], n: int, margin_frac: float = 0.05) -> tuple[Any, Any]:
    import numpy as np

    left, bottom, right, top = bounds
    mx, my = (right - left) * margin_frac, (top - bottom) * margin_frac
    xs = np.linspace(left + mx, right - mx, n)
    ys = np.linspace(bottom + my, top - my, n)
    gx, gy = np.meshgrid(xs, ys)
    return gx.ravel(), gy.ravel()


def summarise(values: Any) -> dict[str, float | int]:
    import numpy as np

    v = np.asarray(values, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"count": 0}
    return {
        "count": int(v.size), "min": float(v.min()), "max": float(v.max()),
        "median": float(np.median(v)), "p05": float(np.percentile(v, 5)), "p95": float(np.percentile(v, 95)),
        "mean": float(v.mean()),
    }


def review(manifest_path: Path, root: Path, grid_n: int = 40) -> dict[str, Any]:
    import numpy as np
    import rasterio
    from lunar_core.terrain import _sample_dataset_bilinear, load_dem_manifest
    from pyproj import CRS, Transformer

    manifest = load_dem_manifest(manifest_path)
    radius = manifest.body_radius_m
    lunar = CRS.from_proj4(f"+proj=longlat +R={radius:.3f} +no_defs +type=crs")
    assets: list[dict[str, Any]] = []
    regional = max(manifest.assets, key=lambda a: a.native_resolution_m)
    for asset in sorted(manifest.assets, key=lambda a: a.native_resolution_m):
        path = (root / asset.relative_path).resolve(strict=True)
        entry: dict[str, Any] = {"asset_id": asset.asset_id, "product_id": asset.product_id, "checks": {}}
        checks = entry["checks"]
        checks["sha256_matches_manifest"] = sha256_file(path) == asset.sha256
        with rasterio.open(path) as ds:
            raster_crs = CRS.from_wkt(ds.crs.to_wkt())
            ellipsoid = raster_crs.ellipsoid
            entry["raster_crs"] = raster_crs.to_wkt()
            entry["ellipsoid"] = {
                "semi_major_m": ellipsoid.semi_major_metre if ellipsoid else None,
                "semi_minor_m": ellipsoid.semi_minor_metre if ellipsoid else None,
            }
            entry["pixel_size_m"] = [abs(ds.transform.a), abs(ds.transform.e)]
            entry["bounds"] = list(ds.bounds)
            entry["nodata"] = None if ds.nodata is None or math.isnan(ds.nodata) else ds.nodata

            gx, gy = interior_grid(tuple(ds.bounds), grid_n)
            lat, lon = stereographic_south_inverse(gx, gy, radius)
            fwd = Transformer.from_crs(lunar, raster_crs, always_xy=True)
            inv = Transformer.from_crs(raster_crs, lunar, always_xy=True)
            px, py = fwd.transform(lon, lat)
            projection_error = float(np.max(np.hypot(np.asarray(px) - gx, np.asarray(py) - gy)))
            rlon, rlat = inv.transform(px, py)
            dlon = (np.asarray(rlon) - lon + 180.0) % 360.0 - 180.0
            roundtrip_error = float(max(np.max(np.abs(dlon)), np.max(np.abs(np.asarray(rlat) - lat))))
            entry["max_projection_error_vs_hand_formula_m"] = projection_error
            entry["max_roundtrip_error_deg"] = roundtrip_error
            checks["projection_matches_hand_formula"] = projection_error < MAX_PROJECTION_ERROR_M
            checks["roundtrip"] = roundtrip_error < MAX_ROUNDTRIP_ERROR_DEG
            checks["pixel_size_matches_manifest"] = all(
                math.isclose(p, asset.native_resolution_m, rel_tol=1e-6) for p in entry["pixel_size_m"]
            )

            heights = _sample_dataset_bilinear(ds, gx, gy, asset.elevation_units)
            stats = summarise(heights)
            entry["height_stats_m"] = stats
            entry["valid_fraction_on_grid"] = float(np.isfinite(heights).mean())
            checks["heights_plausible_vs_1737_4_km_sphere"] = bool(
                stats.get("count", 0) > 0
                and HEIGHT_RANGE_M[0] <= float(stats["min"]) and float(stats["max"]) <= HEIGHT_RANGE_M[1]
            )

            if asset.asset_id != regional.asset_id:
                with rasterio.open((root / regional.relative_path).resolve(strict=True)) as rds:
                    regional_heights = _sample_dataset_bilinear(rds, gx, gy, regional.elevation_units)
                diff = heights - regional_heights
                diff_stats = summarise(diff)
                entry["difference_vs_regional_m"] = {"regional_asset": regional.asset_id, **diff_stats}
                checks["consistent_with_regional_product"] = bool(
                    diff_stats.get("count", 0) > 0 and abs(float(diff_stats["median"])) <= MAX_MEDIAN_PRODUCT_DIFF_M
                )
        entry["passed"] = all(checks.values())
        assets.append(entry)
    return {
        "schema_version": "1.0",
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "manifest_sha256": sha256_file(manifest_path),
        "body_radius_m": radius,
        "thresholds": {
            "projection_error_m": MAX_PROJECTION_ERROR_M, "roundtrip_error_deg": MAX_ROUNDTRIP_ERROR_DEG,
            "height_range_m": HEIGHT_RANGE_M, "median_product_difference_m": MAX_MEDIAN_PRODUCT_DIFF_M,
        },
        "publisher_statement": (
            "PGDA product 78: south polar stereographic X/Y in metres, surface height Z in metres, MOON_ME "
            "reference frame of ephemeris DE421 (https://pgda.gsfc.nasa.gov/products/78). The height reference "
            "radius is not named on that page; it is inferred from the checks recorded here."
        ),
        "assets": assets,
        "passed": all(a["passed"] for a in assets),
    }


def attest(manifest_path: Path, report_path: Path, report: dict[str, Any], reviewer: str) -> None:
    """Set both review flags for every asset, citing the evidence report and its hash."""
    if not report["passed"]:
        raise SystemExit("refusing to attest: at least one DEM check failed")
    report_sha = sha256_file(report_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id = {a["asset_id"]: a for a in report["assets"]}
    for asset in payload["assets"]:
        evidence = by_id[asset["asset_id"]]
        cite = f"Evidence {report_path.relative_to(ROOT)} (sha256 {report_sha}), reviewed by {reviewer} on {report['created_utc'][:10]}."
        asset["crs_contract_verified"] = True
        asset["crs_verification_note"] = (
            f"South-polar stereographic on a {report['body_radius_m']:.1f} m sphere confirmed functionally: pyproj "
            f"matches an independent hand projection to {evidence['max_projection_error_vs_hand_formula_m']:.2e} m and "
            f"round-trips to {evidence['max_roundtrip_error_deg']:.1e} deg; pixel size {evidence['pixel_size_m'][0]} m "
            f"matches the manifest. Publisher frame: MOON_ME / DE421, same as the SPICE geometry (Gate B). {cite}"
        )
        diff = evidence.get("difference_vs_regional_m")
        consistency = (
            f" Median difference to {diff['regional_asset']} {diff['median']:.2f} m over {diff['count']} points "
            f"(p05 {diff['p05']:.1f} m, p95 {diff['p95']:.1f} m)." if diff else ""
        )
        stats = evidence["height_stats_m"]
        asset["vertical_datum_verified"] = True
        asset["vertical_datum_verification_note"] = (
            "Heights treated as metres above the 1737.4 km reference sphere, the same radius as the SPICE PCK and "
            "the horizon observer model (r_obs = R + DEM ground height + observer height). Inferred, not stated by "
            f"the publisher: sampled heights {stats['min']:.0f} to {stats['max']:.0f} m lie within the lunar range "
            f"for that datum.{consistency} {cite}"
        )
    fd, temp = tempfile.mkstemp(dir=manifest_path.parent, prefix=".manifest.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2)
        stream.write("\n")
    os.replace(temp, manifest_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "dems" / "manifest.json")
    parser.add_argument("--out", type=Path, default=None, help="evidence JSON path")
    parser.add_argument("--attest", metavar="REVIEWER", default=None,
                        help="if every check passes, set both review flags with notes naming REVIEWER")
    args = parser.parse_args()
    report = review(args.manifest, ROOT)
    out = args.out or ROOT / "validation" / "evidence" / f"dem_review_{report['created_utc'][:10]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for asset in report["assets"]:
        print(f"\n{asset['asset_id']}: {'PASS' if asset['passed'] else 'FAIL'}")
        for name, ok in asset["checks"].items():
            print(f"  {'ok  ' if ok else 'FAIL'} {name}")
        print(f"  projection vs hand formula {asset['max_projection_error_vs_hand_formula_m']:.2e} m, "
              f"round trip {asset['max_roundtrip_error_deg']:.1e} deg")
        hs = asset["height_stats_m"]
        if hs.get("count"):
            print(f"  heights {hs['min']:.1f} .. {hs['max']:.1f} m (median {hs['median']:.1f}), "
                  f"valid {asset['valid_fraction_on_grid']:.1%}")
        if "difference_vs_regional_m" in asset:
            d = asset["difference_vs_regional_m"]
            print(f"  vs {d['regional_asset']}: median {d['median']:.2f} m, p05 {d['p05']:.1f}, p95 {d['p95']:.1f}, n={d['count']}")
    print(f"\nevidence: {out}\nOVERALL: {'PASS' if report['passed'] else 'FAIL'}")
    if args.attest:
        attest(args.manifest, out, report, args.attest)
        print(f"manifest updated: review flags set by {args.attest}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
