"""Cache keys change whenever what produced an answer changes (lunar_core.cache_keys; review 6 Nov)."""
from __future__ import annotations

from pathlib import Path

from lunar_core import cache_keys, landing
from lunar_core.api_models import LandingRequest


def test_site_record_and_manifest_content_enter_the_key(tmp_path: Path, monkeypatch) -> None:
    from lunar_core import analysis_service

    km, dm = tmp_path / "kernels.json", tmp_path / "dems.json"
    km.write_text("{}"), dm.write_text('{"a": 1}')
    monkeypatch.setattr(analysis_service, "KERNEL_MANIFEST", km)
    monkeypatch.setattr(analysis_service, "DEM_MANIFEST", dm)
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path / "runs")
    req = LandingRequest(site_id="official-a", search_start_utc="2027-01-01T00:00:00Z")
    a = {"site_id": "official-a", "latitude_deg": -85.99, "longitude_deg": 357.07, "origin": "official"}
    k1 = landing._cache_path(req, a)
    assert landing._cache_path(req, dict(a)) == k1                              # stable
    assert landing._cache_path(req, {**a, "longitude_deg": 2.93}) != k1         # re-imported coordinates
    dm.write_text('{"a": 2}')                                                   # same size, new content
    assert landing._cache_path(req, a) != k1


def test_write_atomic_and_fingerprint(tmp_path: Path) -> None:
    target = tmp_path / "sub" / "x.json"
    cache_keys.write_atomic(target, '{"ok": true}')
    assert target.read_text() == '{"ok": true}' and not list(target.parent.glob(".tmp-*"))
    assert len(cache_keys.code_fingerprint()) == 16
    assert cache_keys.file_digest(tmp_path / "missing") is None
