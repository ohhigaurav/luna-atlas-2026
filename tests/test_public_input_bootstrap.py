from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import Mock

import pytest

from tools.prepare_public_inputs import download_atomic


class FakeResponse:
    def __init__(self, data: bytes, url: str, content_length: str | None = None):
        self._stream = io.BytesIO(data)
        self._url = url
        self.headers = {"Content-Length": content_length} if content_length is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._stream.close()

    def read(self, size=-1):
        return self._stream.read(size)

    def geturl(self):
        return self._url


def test_atomic_public_download_hashes_bytes_and_records_size(tmp_path: Path) -> None:
    body = b"synthetic public asset bytes"
    opener = Mock(return_value=FakeResponse(body, "https://pgda.gsfc.nasa.gov/fake.tif", str(len(body))))
    target = tmp_path / "data/assets/sample.tif"
    result = download_atomic(
        "https://pgda.gsfc.nasa.gov/fake.tif", target,
        allowed_hosts={"pgda.gsfc.nasa.gov"}, max_bytes=1024, opener=opener,
    )
    import hashlib
    assert target.read_bytes() == body
    assert result["sha256"] == hashlib.sha256(body).hexdigest()
    assert result["size_bytes"] == len(body)
    assert result["downloaded"] is True
    assert result["retrieved_utc"].endswith("Z")
    assert list(target.parent.glob("*.part")) == []


def test_public_download_rejects_non_allowlisted_origin_before_network(tmp_path: Path) -> None:
    opener = Mock()
    with pytest.raises(ValueError, match="allowlisted"):
        download_atomic(
            "https://evil.example/fake.tif", tmp_path / "fake.tif",
            allowed_hosts={"pgda.gsfc.nasa.gov"}, max_bytes=1024, opener=opener,
        )
    opener.assert_not_called()


def test_public_download_rejects_redirect_to_non_allowlisted_host(tmp_path: Path) -> None:
    body = b"not accepted"
    opener = Mock(return_value=FakeResponse(body, "https://evil.example/fake.tif", str(len(body))))
    target = tmp_path / "fake.tif"
    with pytest.raises(ValueError, match="redirect"):
        download_atomic(
            "https://pgda.gsfc.nasa.gov/fake.tif", target,
            allowed_hosts={"pgda.gsfc.nasa.gov"}, max_bytes=1024, opener=opener,
        )
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


def test_public_download_rejects_truncated_response_without_replacing_target(tmp_path: Path) -> None:
    target = tmp_path / "fake.tif"
    opener = Mock(return_value=FakeResponse(b"short", "https://pgda.gsfc.nasa.gov/fake.tif", "100"))
    with pytest.raises(ValueError, match="Truncated"):
        download_atomic(
            "https://pgda.gsfc.nasa.gov/fake.tif", target,
            allowed_hosts={"pgda.gsfc.nasa.gov"}, max_bytes=1024, opener=opener,
        )
    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))


def test_public_download_honors_size_cap(tmp_path: Path) -> None:
    opener = Mock(return_value=FakeResponse(b"12345", "https://pgda.gsfc.nasa.gov/fake.tif", "5"))
    with pytest.raises(ValueError, match="cap"):
        download_atomic(
            "https://pgda.gsfc.nasa.gov/fake.tif", tmp_path / "fake.tif",
            allowed_hosts={"pgda.gsfc.nasa.gov"}, max_bytes=4, opener=opener,
        )
    assert not (tmp_path / "fake.tif").exists()


def _write_reference_tif(path: Path, resolution: float, site_id: str, value: float = 10.0) -> None:
    import json
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    from tools.prepare_public_inputs import BODY_RADIUS_M
    catalogue = json.loads((Path(__file__).resolve().parents[1] / "data/reference/reference_sites.json").read_text())
    sites = {site["site_id"]: site for site in catalogue["sites"]}
    src = f"+proj=longlat +R={BODY_RADIUS_M:.3f} +no_defs +type=crs"
    dst = f"+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +R={BODY_RADIUS_M:.3f} +units=m +no_defs +type=crs"
    if site_id == "*":
        # A broad synthetic polar tile includes the full set of literature landmarks.
        center_x, center_y = 0.0, 0.0
        width = height = 500
        resolution = 1_000.0
    else:
        site = sites[site_id]
        lon_deg, lat_deg = float(site["longitude_deg"]), float(site["latitude_deg"])
        center_x, center_y = Transformer.from_crs(src, dst, always_xy=True).transform(((lon_deg + 180) % 360) - 180, lat_deg)
        width = height = 200
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1,
        dtype="float32", crs=dst,
        transform=from_origin(center_x - width / 2 * resolution, center_y + height / 2 * resolution, resolution, resolution),
        nodata=-9999.0,
    ) as ds:
        ds.write(np.full((height, width), value, dtype=np.float32), 1)


def test_prepare_public_dems_records_provenance_but_keeps_science_gates_closed(tmp_path: Path, monkeypatch) -> None:
    import json
    import shutil
    from tools import prepare_public_inputs as module

    root = tmp_path
    (root / "data/reference").mkdir(parents=True)
    (root / "data/dems").mkdir(parents=True)
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "data/reference/reference_sites.json",
        root / "data/reference/reference_sites.json",
    )
    (root / "data/dems/manifest.json").write_text(json.dumps({
        "schema_version": "1.0", "manifest_state": "not_configured",
        "body_radius_m": 1737400.0,
        "coordinate_contract": "Synthetic fixture; not real Moon data.",
        "assets": [], "notes": [],
    }), encoding="utf-8")

    def fake_download(url, destination, *, allowed_hosts, max_bytes, force=False, opener=None, progress=None):
        asset = next(item for item in module.DEM_SOURCES if item["url"] == url)
        _write_reference_tif(destination, float(asset["native_resolution_m"]), asset["site_ids"][0])
        return {
            "path": destination,
            "sha256": module.sha256_file(destination),
            "size_bytes": destination.stat().st_size,
            "retrieved_utc": "2026-10-26T10:00:00Z",
            "downloaded": True,
            "source_url": url,
        }

    monkeypatch.setattr(module, "download_atomic", fake_download)
    result = module.prepare_dems(root, include_regional=True)
    assert result["asset_count"] == 3
    assert result["terrain_analysis_allowed"] is False
    assert result["terrain_allowed_by_site"] == {
        "reference-lola-site-001": False, "reference-lola-site-004": False,
    }
    manifest = json.loads((root / "data/dems/manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_state"] == "configured"
    assert len(manifest["assets"]) == 3
    assert all(asset["crs_contract_verified"] is False for asset in manifest["assets"])
    assert all(asset["vertical_datum_verified"] is False for asset in manifest["assets"])
    assert all(asset["retrieved_utc"] == "2026-10-26T10:00:00Z" for asset in manifest["assets"])
    assert all(asset["size_bytes"] > 0 for asset in manifest["assets"])
    asset_map = {asset["asset_id"]: asset for asset in manifest["assets"]}
    assert asset_map["pgda78-site01-surface"]["site_ids"] == ["reference-lola-site-001"]
    assert asset_map["pgda78-site04-surface"]["site_ids"] == ["reference-lola-site-004"]
    assert asset_map["pgda90-60s-240m-regional"]["site_ids"] == ["*"]


def test_dem_asset_provenance_timestamp_must_be_utc() -> None:
    from pydantic import ValidationError
    from lunar_core.terrain import DEMAsset

    base = {
        "asset_id": "test", "relative_path": "data/dems/assets/test.tif",
        "site_ids": ["reference-lola-site-001"],
        "source_url": "https://example.org/test.tif", "product_id": "synthetic-test",
        "sha256": "a" * 64, "size_bytes": 100,
        "native_resolution_m": 5, "min_range_m": 0, "max_range_m": 100,
        "vertical_datum": "synthetic only", "crs_contract": "synthetic only",
        "elevation_units": "m",
    }
    accepted = DEMAsset.model_validate({**base, "retrieved_utc": "2026-10-26T10:00:00Z"})
    assert accepted.size_bytes == 100
    with pytest.raises(ValidationError, match="UTC"):
        DEMAsset.model_validate({**base, "retrieved_utc": "2026-10-26T10:00:00+05:30"})
