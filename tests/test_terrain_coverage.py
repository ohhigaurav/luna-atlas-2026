from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import rasterio
from lunar_core.terrain import dem_coverage_inventory
from pyproj import CRS
from rasterio.transform import from_origin

BODY_RADIUS_M = 1_737_400.0


def _make_dem(path: Path) -> None:
    polar = CRS.from_proj4(
        f"+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R={BODY_RADIUS_M} +units=m +no_defs +type=crs"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=100, height=100, count=1,
        dtype="float32", crs=polar,
        transform=from_origin(-50_000, 50_000, 1_000, 1_000), nodata=-9999.0,
    ) as ds:
        ds.write(np.zeros((100, 100), dtype=np.float32), 1)


def _manifest(raster: Path, root: Path, *, crs_verified: bool = False, datum_verified: bool = False) -> Path:
    payload = {
        "schema_version": "1.0",
        "manifest_state": "configured",
        "body_radius_m": BODY_RADIUS_M,
        "coordinate_contract": "Synthetic test fixture; not a real lunar terrain dataset.",
        "assets": [{
            "asset_id": "synthetic-coverage",
            "relative_path": str(raster.relative_to(root)),
            "site_ids": ["reference-test-site"],
            "source_url": "https://example.invalid/synthetic.tif",
            "product_id": "Synthetic coverage fixture",
            "sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
            "retrieved_utc": "2026-10-26T00:00:00Z",
            "size_bytes": raster.stat().st_size,
            "native_resolution_m": 1_000.0,
            "min_range_m": 0,
            "max_range_m": 200_000,
            "vertical_datum": "Synthetic; unverified",
            "crs_contract": "Synthetic polar stereographic CRS",
            "crs_contract_verified": crs_verified,
            "crs_verification_note": "Synthetic test fixture only." if crs_verified else None,
            "vertical_datum_verified": datum_verified,
            "vertical_datum_verification_note": "Synthetic test fixture only." if datum_verified else None,
            "elevation_units": "m",
        }],
        "notes": ["Synthetic test fixture only."],
    }
    target = root / "data" / "dems" / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_coverage_endpoint_emits_polygon_for_hash_verified_but_unreviewed_asset(tmp_path: Path) -> None:
    root = tmp_path
    raster = root / "data" / "dems" / "assets" / "synthetic.tif"
    _make_dem(raster)
    manifest = _manifest(raster, root)

    result = dem_coverage_inventory(manifest, root, edge_samples=8)

    assert result["asset_count"] == 1
    assert result["verified_coverage_count"] == 0
    assert result["provisional_coverage_count"] == 1
    asset = result["assets"][0]
    assert asset["hash_verified"] is True
    assert asset["footprint_status"] == "provisional"
    assert len(asset["footprint"]) == 32
    assert asset["issue"] is not None
    assert all(-90 <= point["latitude_deg"] <= 90 for point in asset["footprint"])


def test_coverage_is_only_verified_when_hash_crs_and_datum_review_pass(tmp_path: Path) -> None:
    root = tmp_path
    raster = root / "data" / "dems" / "assets" / "synthetic.tif"
    _make_dem(raster)
    manifest = _manifest(raster, root, crs_verified=True, datum_verified=True)

    result = dem_coverage_inventory(manifest, root, edge_samples=4)

    assert result["verified_coverage_count"] == 1
    assert result["provisional_coverage_count"] == 0
    assert result["assets"][0]["footprint_status"] == "verified"
    assert result["assets"][0]["issue"] is None


def test_coverage_refuses_to_render_hash_mismatched_raster(tmp_path: Path) -> None:
    root = tmp_path
    raster = root / "data" / "dems" / "assets" / "synthetic.tif"
    _make_dem(raster)
    manifest = _manifest(raster, root)
    raster.write_bytes(raster.read_bytes() + b"tampered")

    result = dem_coverage_inventory(manifest, root)

    asset = result["assets"][0]
    assert asset["file_present"] is True
    assert asset["hash_verified"] is False
    assert asset["footprint"] == []
    assert "SHA-256 mismatch" in asset["issue"]


def test_coverage_refuses_raster_outside_project_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.tif"
    _make_dem(outside)
    # Create a manifest with a path that escapes the project. A hash does not grant path access.
    payload = {
        "schema_version": "1.0", "manifest_state": "configured", "body_radius_m": BODY_RADIUS_M,
        "coordinate_contract": "Synthetic test fixture.", "assets": [{
            "asset_id": "escape", "relative_path": "../outside.tif", "site_ids": ["*"],
            "source_url": "https://example.invalid/outside.tif", "product_id": "Synthetic",
            "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(), "size_bytes": outside.stat().st_size,
            "native_resolution_m": 1000, "min_range_m": 0, "max_range_m": 200000,
            "vertical_datum": "unverified", "crs_contract": "unverified", "elevation_units": "m",
        }], "notes": [],
    }
    manifest = root / "data/dems/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = dem_coverage_inventory(manifest, root)

    assert result["assets"][0]["footprint"] == []
    assert "outside" in result["assets"][0]["issue"]
