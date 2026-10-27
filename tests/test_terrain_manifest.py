from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from lunar_core.provenance import sha256_file
from lunar_core.terrain import (
    DEMManifestError,
    build_cached_horizon_from_dem_assets,
    preflight_dem_assets,
    _physical_elevation_array_m,
)

RADIUS_M = 1_737_400.0


def _make_project(tmp_path: Path, *, verified: bool = True, elevation_units: str = "m", pixel_value: float = 0.0, scale: float = 1.0, offset: float = 0.0, resolution: float = 5.0) -> tuple[Path, str]:
    root = tmp_path
    raster_path = root / "data/dems/assets/synthetic-flat.tif"
    raster_path.parent.mkdir(parents=True)
    source_crs = f"+proj=longlat +R={RADIUS_M} +no_defs +type=crs"
    target_crs = f"+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R={RADIUS_M} +units=m +no_defs +type=crs"
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    sx, sy = transformer.transform(0.0, -85.0)
    extent = resolution * 800
    transform = from_origin(sx - extent / 2, sy + extent / 2, resolution, resolution)
    values = np.full((800, 800), pixel_value, dtype=np.float32)
    with rasterio.open(
        raster_path, "w", driver="GTiff", width=800, height=800, count=1,
        dtype="float32", crs=target_crs, transform=transform, nodata=-9999.0,
    ) as raster:
        raster.write(values, 1)
        raster.scales = (scale,)
        raster.offsets = (offset,)
    asset_id = "test-flat-dem"
    manifest = {
        "schema_version": "1.0",
        "manifest_state": "configured",
        "body_radius_m": RADIUS_M,
        "coordinate_contract": "Synthetic test-only spherical lunar coordinate contract.",
        "assets": [{
            "asset_id": asset_id,
            "relative_path": "data/dems/assets/synthetic-flat.tif",
            "site_ids": ["reference-test-site"],
            "source_url": "https://example.invalid/synthetic-flat-dem",
            "product_id": "synthetic-test-only",
            "sha256": sha256_file(raster_path),
            "native_resolution_m": resolution,
            "min_range_m": 0.0,
            "max_range_m": 1_000.0,
            "elevation_units": elevation_units,
            "vertical_datum": "Synthetic elevation relative to radius used by test.",
            "crs_contract": "Synthetic lunar stereographic projection, spherical body radius in metres.",
            "crs_contract_verified": verified,
            "crs_verification_note": "Test fixture only." if verified else None,
            "vertical_datum_verified": verified,
            "vertical_datum_verification_note": "Test fixture only." if verified else None,
            "nodata_policy": "unknown",
        }],
        "notes": ["TEST DATA ONLY; not a lunar terrain asset."],
    }
    manifest_path = root / "data/dems/manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path, asset_id


def test_preflight_requires_explicit_crs_and_vertical_datum_review(tmp_path: Path) -> None:
    manifest_path, _ = _make_project(tmp_path, verified=False)
    with pytest.raises(DEMManifestError, match="CRS contract is unverified"):
        preflight_dem_assets(manifest_path, tmp_path, "reference-test-site")


def test_real_raster_ingestion_builds_and_reuses_hash_keyed_horizon(tmp_path: Path) -> None:
    manifest_path, _ = _make_project(tmp_path, verified=True)
    kwargs = dict(
        site_id="reference-test-site",
        latitude_deg=-85.0,
        longitude_deg=0.0,
        observer_height_m=2.0,
        reference_radius_m=RADIUS_M,
        max_range_m=1_000.0,
        azimuth_step_deg=10.0,
        near_range_m=500.0,
        near_step_m=100.0,
        far_step_m=100.0,
        manifest_path=manifest_path,
        project_root=tmp_path,
    )
    horizon, ground, first = build_cached_horizon_from_dem_assets(**kwargs)
    assert ground == pytest.approx(0.0)
    assert len(horizon.bins) == 36
    assert all(bin_.coverage_status == "complete" for bin_ in horizon.bins)
    assert first["cache_hit"] is False
    assert len(first["cache_key"]) == 64

    cached_horizon, cached_ground, second = build_cached_horizon_from_dem_assets(**kwargs)
    assert cached_ground == pytest.approx(ground)
    assert second["cache_hit"] is True
    assert [item.elevation_rad for item in cached_horizon.bins] == [item.elevation_rad for item in horizon.bins]

    raster_path = tmp_path / "data/dems/assets/synthetic-flat.tif"
    raster_path.write_bytes(raster_path.read_bytes() + b"tamper")
    with pytest.raises(DEMManifestError, match="SHA-256 mismatch"):
        build_cached_horizon_from_dem_assets(**kwargs)


def test_dem_scale_offset_and_declared_units_are_applied_to_metres(tmp_path: Path) -> None:
    manifest_path, _ = _make_project(
        tmp_path, elevation_units="km", pixel_value=10.0, scale=0.5, offset=2.0
    )
    horizon, ground, metadata = build_cached_horizon_from_dem_assets(
        "reference-test-site", -85.0, 0.0, observer_height_m=2.0,
        reference_radius_m=RADIUS_M, max_range_m=1_000.0, azimuth_step_deg=10.0,
        near_range_m=500.0, near_step_m=100.0, far_step_m=100.0,
        manifest_path=manifest_path, project_root=tmp_path,
    )
    # (raw 10 × scale 0.5 + offset 2) km = 7,000 m.
    assert ground == pytest.approx(7_000.0)
    assert horizon.observer_radius_m == pytest.approx(RADIUS_M + 7_002.0)
    assert metadata["assets"][0]["raster_scales"] == (0.5,)
    assert metadata["assets"][0]["raster_offsets"] == (2.0,)
    assert metadata["assets"][0]["elevation_units"] == "km"


def test_radial_sampling_never_oversamples_beyond_declared_dem_pixel_size(tmp_path: Path) -> None:
    manifest_path, _ = _make_project(tmp_path, verified=True, resolution=80.0)
    horizon, _ground, metadata = build_cached_horizon_from_dem_assets(
        "reference-test-site", -85.0, 0.0, observer_height_m=2.0,
        reference_radius_m=RADIUS_M, max_range_m=1_000.0, azimuth_step_deg=10.0,
        near_range_m=500.0, near_step_m=5.0, far_step_m=100.0,
        manifest_path=manifest_path, project_root=tmp_path,
    )
    assert len(horizon.bins) == 36
    assert metadata["radial_sample_count"] < 20
    assert metadata["radial_sampling_segments"][0]["native_resolution_m"] == 80.0
    assert metadata["radial_sampling_segments"][0]["effective_step_m"] == 80.0
    assert metadata["near_step_m_requested"] == 5.0


def test_vectorized_raster_samples_preserve_mask_nodata_scale_offset_and_units() -> None:
    from types import SimpleNamespace

    samples = np.ma.array(
        [[10.0], [-9999.0], [25.0], [np.nan]],
        mask=[[False], [False], [True], [False]],
    )
    dataset = SimpleNamespace(nodata=-9999.0, scales=(0.5,), offsets=(2.0,))
    result = _physical_elevation_array_m(dataset, samples, "km")
    assert result[0] == pytest.approx(7_000.0)
    assert np.isnan(result[1])  # Raw NoData is not transformed into an elevation.
    assert np.isnan(result[2])  # A Rasterio masked sample remains unknown.
    assert np.isnan(result[3])  # Non-finite samples remain unknown.


def test_nested_dem_uses_coarser_valid_pixel_when_fine_asset_is_outside_footprint(tmp_path: Path) -> None:
    """A fine tile's NoData must not mask a valid overlapping regional DEM sample."""
    import json
    from rasterio.transform import from_origin

    root = tmp_path
    data_dir = root / "data/dems/assets"
    data_dir.mkdir(parents=True)
    source_crs = f"+proj=longlat +R={RADIUS_M} +no_defs +type=crs"
    target_crs = f"+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R={RADIUS_M} +units=m +no_defs +type=crs"
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    center_x, center_y = transformer.transform(0.0, -85.0)
    assets = []
    for name, resolution, width, height, value in (
        ("fine", 5.0, 10, 10, 10.0),
        ("regional", 10.0, 1000, 1000, 0.0),
    ):
        raster_path = data_dir / f"{name}.tif"
        extent_x = width * resolution
        extent_y = height * resolution
        with rasterio.open(
            raster_path, "w", driver="GTiff", width=width, height=height, count=1,
            dtype="float32", crs=target_crs,
            transform=from_origin(center_x - extent_x / 2, center_y + extent_y / 2, resolution, resolution),
            nodata=-9999.0,
        ) as ds:
            ds.write(np.full((height, width), value, dtype=np.float32), 1)
        assets.append({
            "asset_id": name, "relative_path": str(raster_path.relative_to(root)),
            "site_ids": ["reference-test-site"], "source_url": f"https://example.invalid/{name}.tif",
            "product_id": f"Synthetic {name} DEM", "sha256": sha256_file(raster_path),
            "native_resolution_m": resolution, "min_range_m": 0, "max_range_m": 1000,
            "elevation_units": "m", "vertical_datum": "synthetic test fixture",
            "crs_contract": "synthetic spherical stereographic CRS",
            "crs_contract_verified": True, "crs_verification_note": "Synthetic test only.",
            "vertical_datum_verified": True, "vertical_datum_verification_note": "Synthetic test only.",
        })
    manifest_path = root / "data/dems/manifest.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "1.0", "manifest_state": "configured", "body_radius_m": RADIUS_M,
        "coordinate_contract": "Synthetic test contract", "assets": assets, "notes": [],
    }), encoding="utf-8")

    horizon, ground, metadata = build_cached_horizon_from_dem_assets(
        "reference-test-site", -85.0, 0.0, observer_height_m=2.0,
        reference_radius_m=RADIUS_M, max_range_m=1000.0, azimuth_step_deg=10.0,
        near_range_m=500.0, near_step_m=100.0, far_step_m=100.0,
        manifest_path=manifest_path, project_root=root,
    )

    assert ground == pytest.approx(10.0)
    assert all(item.coverage_status == "complete" for item in horizon.bins)
    counts = metadata["asset_sample_counts_total"]
    assert counts["fine"] > 0
    assert counts["regional"] > counts["fine"]
    assert metadata["fallback_sample_count_total"] > 0
    assert metadata["missing_sample_count_total"] == 0
    # Sample assignment is explicit and auditable; fine samples do not overwrite regional fallback.
    assert sum(counts.values()) == len(horizon.bins) * metadata["radial_sample_count"]
