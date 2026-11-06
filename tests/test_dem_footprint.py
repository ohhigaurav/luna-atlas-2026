"""Location-based DEM selection (independent review finding 1): same place, same terrain, whatever the site ID."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from lunar_core.provenance import sha256_file
from lunar_core.terrain import DEMAsset, asset_selected, preflight_dem_assets, south_polar_stereo_m

R = 1_737_400.0


def _asset(**kw: object) -> DEMAsset:
    base = dict(asset_id="tile", relative_path="t.tif", site_ids=["reference-lola-site-001"],
                source_url="https://example.invalid/t", product_id="p", sha256="0" * 64,
                native_resolution_m=5.0, min_range_m=0.0, max_range_m=8000.0, vertical_datum="v",
                crs_contract="c", elevation_units="m")
    return DEMAsset(**{**base, **kw})


def test_stereo_matches_the_projection_used_everywhere() -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.find_summit import to_stereo  # the tools' own implementation, checked against Goddard maps

    for lat, lon in ((-89.45, 222.69), (-85.99, 357.07), (-60.0, 90.0)):
        assert south_polar_stereo_m(lat, lon, R) == pytest.approx(to_stereo(lat, lon, R), abs=1e-6)
    x, y = south_polar_stereo_m(-89.45, 222.69, R)
    assert (x, y) == pytest.approx((-11_308.2, -12_258.9), abs=0.5)  # Site 001, ~16.7 km from the pole


def test_selection_by_id_star_and_footprint() -> None:
    x, y = south_polar_stereo_m(-89.45, 222.69, R)
    fp = (x - 8000, y - 8000, x + 8000, y + 8000)
    tile = _asset(footprint_stereo_m=fp, select_by_footprint=True)
    assert asset_selected(tile, "reference-lola-site-001", None, None, R)          # by ID
    assert asset_selected(tile, "custom-point", -89.45, 223.2, R)                  # 150 m away: inside
    assert asset_selected(tile, "official-ridge", -89.45, 222.69, R)               # official site, same place
    assert not asset_selected(tile, "custom-point", -85.99, 357.07, R)             # Malapert: outside
    assert not asset_selected(tile, "custom-point", 0.67, 23.47, R)                # northern hemisphere
    assert not asset_selected(_asset(footprint_stereo_m=fp), "custom-point", -89.45, 223.2, R)  # not opted in
    assert asset_selected(_asset(site_ids=["*"]), "anything", None, None, R)
    with pytest.raises(ValueError, match="footprint"):
        _asset(select_by_footprint=True)


def test_preflight_picks_the_tile_for_a_point_inside_it(tmp_path: Path) -> None:
    (tmp_path / "t.tif").write_bytes(b"tile"), (tmp_path / "r.tif").write_bytes(b"regional")
    x, y = south_polar_stereo_m(-89.45, 222.69, R)
    common = dict(source_url="https://example.invalid/x", product_id="p", min_range_m=0.0, vertical_datum="v",
                  crs_contract="c", crs_contract_verified=True, crs_verification_note="test",
                  vertical_datum_verified=True, vertical_datum_verification_note="test", elevation_units="m")
    manifest = {"schema_version": "1.0", "manifest_state": "configured", "body_radius_m": R,
                "coordinate_contract": "test", "assets": [
                    {**common, "asset_id": "tile", "relative_path": "t.tif", "site_ids": ["reference-lola-site-001"],
                     "sha256": sha256_file(tmp_path / "t.tif"), "native_resolution_m": 5.0, "max_range_m": 8000.0,
                     "footprint_stereo_m": [x - 8000, y - 8000, x + 8000, y + 8000], "select_by_footprint": True},
                    {**common, "asset_id": "regional", "relative_path": "r.tif", "site_ids": ["*"],
                     "sha256": sha256_file(tmp_path / "r.tif"), "native_resolution_m": 240.0, "max_range_m": 200000.0}]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    _, near = preflight_dem_assets(path, tmp_path, "custom-point", -89.45, 223.2)
    assert [v.asset.asset_id for v in near] == ["tile", "regional"]          # finest first
    _, far = preflight_dem_assets(path, tmp_path, "custom-point", -85.99, 357.07)
    assert [v.asset.asset_id for v in far] == ["regional"]
    _, legacy = preflight_dem_assets(path, tmp_path, "custom-point")         # no coordinates: ID rules only
    assert [v.asset.asset_id for v in legacy] == ["regional"]
