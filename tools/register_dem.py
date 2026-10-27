#!/usr/bin/env python3
"""Inspect and register a local lunar elevation GeoTIFF/COG without certifying its datum.

An analyst must explicitly verify both the horizontal coordinate contract and the vertical datum
before terrain rays may consume this asset. Merely opening a raster, knowing its nominal pixel
spacing, or finding a CRS string is not sufficient evidence of compatibility.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.provenance import sha256_file  # noqa: E402
from lunar_core.terrain import DEMAsset, DEMManifest, load_dem_manifest  # noqa: E402


def safe_id(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    if not slug:
        raise ValueError("asset ID contains no safe filename characters")
    return slug[:100]


def register(args: argparse.Namespace) -> dict[str, Any]:
    source = args.file.resolve(strict=True)
    if not source.is_file():
        raise ValueError("--file must point to a regular raster file")
    if not args.source_url.startswith("https://"):
        raise ValueError("--source-url must be an HTTPS publisher/data-product URL")
    if not args.vertical_datum.strip() or not args.crs_contract.strip():
        raise ValueError("--vertical-datum and --crs-contract must describe the inspected asset")
    if args.verify_vertical_datum and not (args.vertical_datum_verification_note or "").strip():
        raise ValueError("--vertical-datum-verification-note is required to affirm vertical datum verification")
    if args.verify_crs_contract and not (args.crs_verification_note or "").strip():
        raise ValueError("--crs-verification-note is required to affirm coordinate-contract verification")

    try:
        import rasterio
    except ImportError as exc:
        raise RuntimeError("Rasterio is required; install project dependencies first") from exc
    with rasterio.open(source, "r") as raster:
        if raster.crs is None:
            raise ValueError("raster has no CRS; cannot register it for terrain-aware analysis")
        if raster.count < 1 or raster.width < 2 or raster.height < 2:
            raise ValueError("raster dimensions/band count are invalid")
        raster_summary = {
            "driver": raster.driver,
            "width": raster.width,
            "height": raster.height,
            "band_count": raster.count,
            "crs": raster.crs.to_string(),
            "bounds": tuple(float(v) for v in raster.bounds),
            "transform": tuple(float(v) for v in raster.transform)[:6],
            "nodata": raster.nodata,
            "dtype": raster.dtypes[0],
            "scales": tuple(float(v) for v in raster.scales),
            "offsets": tuple(float(v) for v in raster.offsets),
            "band_units": raster.units,
            "elevation_units_declared": args.elevation_units,
            "block_shapes": raster.block_shapes,
        }

    manifest_path = args.manifest.resolve()
    if manifest_path.exists():
        existing = load_dem_manifest(manifest_path)
    else:
        existing = DEMManifest.model_validate({
            "schema_version": "1.0", "manifest_state": "not_configured",
            "body_radius_m": 1_737_400.0,
            "coordinate_contract": "Moon body-fixed lat/lon are transformed into the raster's declared CRS; verify frame/radius/axis conventions before use.",
            "assets": [], "notes": [],
        })
    if any(item.asset_id == args.asset_id for item in existing.assets):
        raise ValueError(f"asset ID already exists: {args.asset_id}; use a new ID after comparing its hashes")
    if any(item.relative_path == f"data/dems/assets/{safe_id(args.asset_id)}{source.suffix.lower()}" for item in existing.assets):
        raise ValueError("asset path already exists in manifest")

    relative_path = Path("data/dems/assets") / f"{safe_id(args.asset_id)}{source.suffix.lower()}"
    destination = ROOT / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"destination exists; refusing overwrite: {destination}")
    shutil.copy2(source, destination)
    try:
        asset = DEMAsset.model_validate({
            "asset_id": args.asset_id,
            "relative_path": relative_path.as_posix(),
            "site_ids": args.site_ids,
            "source_url": args.source_url,
            "product_id": args.product_id,
            "sha256": sha256_file(destination),
            "retrieved_utc": args.retrieved_utc,
            "size_bytes": destination.stat().st_size,
            "native_resolution_m": args.native_resolution_m,
            "min_range_m": args.min_range_m,
            "max_range_m": args.max_range_m,
            "elevation_units": args.elevation_units,
            "vertical_datum": args.vertical_datum,
            "crs_contract": args.crs_contract,
            "crs_contract_verified": args.verify_crs_contract,
            "crs_verification_note": args.crs_verification_note,
            "vertical_datum_verified": args.verify_vertical_datum,
            "vertical_datum_verification_note": args.vertical_datum_verification_note,
            "nodata_policy": "unknown",
        })
        raw = existing.model_dump(mode="json")
        raw["manifest_state"] = "configured"
        raw["assets"] = [item.model_dump(mode="json") for item in existing.assets] + [asset.model_dump(mode="json")]
        raw["notes"] = list(existing.notes) + [
            f"Registered {asset.asset_id}; raster metadata snapshot: {json.dumps(raster_summary, sort_keys=True)}"
        ]
        parsed = DEMManifest.model_validate(raw)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
        temporary.write_text(json.dumps(parsed.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
    except Exception:
        # Do not leave an unreferenced copied raster after a failed schema/manifest update.
        destination.unlink(missing_ok=True)
        raise
    return {
        "asset_id": asset.asset_id,
        "destination": str(destination),
        "sha256": asset.sha256,
        "size_bytes": destination.stat().st_size,
        "raster_metadata": raster_summary,
        "crs_contract_verified": asset.crs_contract_verified,
        "vertical_datum_verified": asset.vertical_datum_verified,
        "terrain_use_allowed": asset.crs_contract_verified and asset.vertical_datum_verified,
        "manifest": str(manifest_path),
        "next_step": "Re-run DEM preflight and synthetic CRS/coverage tests; verification must be supported by recorded evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--asset-id", required=True)
    parser.add_argument("--site-ids", nargs="+", required=True, help="site IDs or * for a verified regional asset")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--retrieved-utc", default=None,
                        help="publisher download time in UTC ISO-8601; omit if unknown rather than substituting registration time")
    parser.add_argument("--product-id", required=True, help="e.g. NASA PGDA 78 or 90")
    parser.add_argument("--native-resolution-m", type=float, required=True, help="resolution metadata, not accuracy")
    parser.add_argument("--min-range-m", type=float, default=0.0)
    parser.add_argument("--max-range-m", type=float, required=True)
    parser.add_argument("--elevation-units", choices=("m", "km", "cm", "mm"), required=True,
                        help="physical units of elevations after applying raster band scale/offset")
    parser.add_argument("--vertical-datum", required=True, help="verbatim publisher statement or unresolved status")
    parser.add_argument("--crs-contract", required=True, help="frame, projection, axis order and units")
    parser.add_argument("--verify-crs-contract", action="store_true")
    parser.add_argument("--crs-verification-note", default=None)
    parser.add_argument("--verify-vertical-datum", action="store_true")
    parser.add_argument("--vertical-datum-verification-note", default=None)
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/dems/manifest.json")
    args = parser.parse_args()
    try:
        print(json.dumps(register(args), indent=2))
    except Exception as exc:
        parser.exit(2, f"DEM registration failed: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
