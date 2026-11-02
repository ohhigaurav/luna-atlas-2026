"""Offline tests for tools/bake_static.py helpers (no kernels or DEMs)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools import bake_static as bake


def test_plan_terrain_heights_for_polar_sites_and_one_flat_run_elsewhere() -> None:
    sites = [{"site_id": "b-equator", "latitude_deg": 0.67}, {"site_id": "a-pole", "latitude_deg": -89.45},
             {"site_id": "c-edge", "latitude_deg": -60.0}, {"site_id": "d-north", "latitude_deg": -59.99}]
    plan = bake.plan_runs(sites, (0.0, 2.0))
    assert plan == [("a-pole", "terrain", 0.0), ("a-pole", "terrain", 2.0), ("b-equator", "flat", 2.0),
                    ("c-edge", "terrain", 0.0), ("c-edge", "terrain", 2.0), ("d-north", "flat", 2.0)]


def test_run_key_is_stable_text() -> None:
    assert bake.run_key("reference-lola-site-001", "terrain", 0.0) == "reference-lola-site-001|terrain|0m"
    assert bake.run_key("x", "flat", 2.5) == "x|flat|2.5m"


def test_atomic_write_returns_hash_of_bytes_written(tmp_path: Path) -> None:
    target = tmp_path / "runs" / "r.json"
    digest = bake.write_json_atomic(target, {"a": [1, 2], "é": "x"})
    assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": [1, 2], "é": "x"}
    assert [p.name for p in target.parent.iterdir()] == ["r.json"]


def test_resume_only_with_identical_settings_and_existing_files(tmp_path: Path) -> None:
    settings = {"start_utc": "2027-01-01T00:00:00Z", "step_min": 30}
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "kept.json").write_text("{}", encoding="utf-8")
    manifest = {"settings": settings, "runs": {"k1": {"file": "runs/kept.json"}, "k2": {"file": "runs/gone.json"}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert set(bake.load_previous(tmp_path / "manifest.json", settings)) == {"k1"}
    assert bake.load_previous(tmp_path / "manifest.json", {**settings, "step_min": 60}) == {}
    assert bake.load_previous(tmp_path / "missing.json", settings) == {}
