"""DEM asset overrides (PGDA error clones) through the real raster path. Needs rasterio/pyproj."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

from lunar_core.terrain import DEMManifestError, build_cached_horizon_from_dem_assets  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from test_terrain_manifest import RADIUS_M, _make_project  # noqa: E402

KWARGS = dict(
    site_id="reference-test-site", latitude_deg=-85.0, longitude_deg=0.0, observer_height_m=2.0,
    reference_radius_m=RADIUS_M, max_range_m=1_000.0, azimuth_step_deg=10.0, near_range_m=500.0,
    near_step_m=100.0, far_step_m=100.0,
)


def _write_like(base: Path, target: Path, values: np.ndarray, *, shift_m: float = 0.0) -> Path:
    with rasterio.open(base) as src:
        profile = src.profile
        if shift_m:
            t = src.transform
            profile["transform"] = from_origin(t.c + shift_m, t.f, t.a, -t.e)
    target.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(target, "w", **profile) as dst:
        dst.write(values.astype(np.float32), 1)
    return target


def test_clone_override_changes_pixels_not_contract_and_has_its_own_cache_key(tmp_path: Path) -> None:
    manifest_path, asset_id = _make_project(tmp_path, pixel_value=10.0)
    base = tmp_path / "data/dems/assets/synthetic-flat.tif"
    clone = _write_like(base, tmp_path / "data/dems/clones/clone-001.tif", np.full((800, 800), 13.0))
    kwargs = dict(KWARGS, manifest_path=manifest_path, project_root=tmp_path)

    _h, nominal_ground, nominal_meta = build_cached_horizon_from_dem_assets(**kwargs)
    _h, clone_ground, clone_meta = build_cached_horizon_from_dem_assets(**kwargs, asset_overrides={asset_id: clone})
    assert nominal_ground == pytest.approx(10.0)
    assert clone_ground == pytest.approx(13.0)
    assert clone_meta["cache_key"] != nominal_meta["cache_key"]
    record = clone_meta["asset_overrides"][0]
    assert record["asset_id"] == asset_id and record["override_path"] == "data/dems/clones/clone-001.tif"
    assert nominal_meta["asset_overrides"] == []

    _h, again_ground, again_meta = build_cached_horizon_from_dem_assets(**kwargs, asset_overrides={asset_id: clone})
    assert again_meta["cache_hit"] is True and again_ground == pytest.approx(13.0)
    _h, _g, nominal_again = build_cached_horizon_from_dem_assets(**kwargs)
    assert nominal_again["cache_hit"] is True and nominal_again["cache_key"] == nominal_meta["cache_key"]


def test_override_with_a_different_grid_is_refused(tmp_path: Path) -> None:
    manifest_path, asset_id = _make_project(tmp_path)
    base = tmp_path / "data/dems/assets/synthetic-flat.tif"
    shifted = _write_like(base, tmp_path / "data/dems/clones/shifted.tif", np.zeros((800, 800)), shift_m=5.0)
    with pytest.raises(DEMManifestError, match="does not share"):
        build_cached_horizon_from_dem_assets(
            **KWARGS, manifest_path=manifest_path, project_root=tmp_path, asset_overrides={asset_id: shifted},
        )


def test_override_must_name_a_selected_asset_and_live_under_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest_path, asset_id = _make_project(project)
    base = project / "data/dems/assets/synthetic-flat.tif"
    outside = _write_like(base, tmp_path / "elsewhere/clone.tif", np.zeros((800, 800)))
    kwargs = dict(KWARGS, manifest_path=manifest_path, project_root=project)
    with pytest.raises(DEMManifestError, match="not selected"):
        build_cached_horizon_from_dem_assets(**kwargs, asset_overrides={"no-such-asset": base})
    with pytest.raises(DEMManifestError, match="under the project root"):
        build_cached_horizon_from_dem_assets(**kwargs, asset_overrides={asset_id: outside})
