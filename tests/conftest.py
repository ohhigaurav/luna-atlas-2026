"""Shared fixtures.

Tests must not depend on what a developer has downloaded into ``data/``. The
``unconfigured_project`` fixture points every module-level data path at fresh, empty copies
in a temporary directory, so "fail closed when unconfigured" tests stay meaningful on a machine
that already has real kernels, DEMs, official sites or saved runs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

UNCONFIGURED_KERNELS = {
    "schema_version": "1.0",
    "manifest_state": "not_configured",
    "frame_contract": "MOON_ME; DE421-associated lunar orientation unless an alternative chain is documented and validated",
    "kernels": [],
}
UNCONFIGURED_DEMS = {
    "schema_version": "1.0",
    "manifest_state": "not_configured",
    "body_radius_m": 1737400.0,
    "coordinate_contract": "Test fixture: no DEM assets registered.",
    "assets": [],
    "notes": [],
}
EMPTY_CATALOGUE = {
    "schema_version": "1.0",
    "catalogue_state": "awaiting_official_source",
    "source_url": None,
    "retrieved_utc": None,
    "sites": [],
}


@pytest.fixture
def unconfigured_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from lunar_core import analysis_service, catalogue

    kernels = tmp_path / "data" / "manifests" / "kernels.json"
    dems = tmp_path / "data" / "dems" / "manifest.json"
    sites = tmp_path / "data" / "catalogue" / "sites.json"
    runs = tmp_path / "data" / "runs"
    for path, payload in ((kernels, UNCONFIGURED_KERNELS), (dems, UNCONFIGURED_DEMS), (sites, EMPTY_CATALOGUE)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    try:  # The API module needs FastAPI; pure-science tests can use this fixture without it.
        from lunar_core import api
    except ImportError:
        api = None
    if api is not None:
        monkeypatch.setattr(api, "KERNEL_MANIFEST_PATH", kernels)
        monkeypatch.setattr(api, "DEM_MANIFEST_PATH", dems)
    monkeypatch.setattr(analysis_service, "KERNEL_MANIFEST", kernels)
    monkeypatch.setattr(analysis_service, "DEM_MANIFEST", dems)
    monkeypatch.setattr(analysis_service, "RUNS_DIR", runs)
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", None)
    monkeypatch.setattr(catalogue, "default_catalogue_path", lambda: sites)
    return tmp_path
