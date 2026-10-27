from __future__ import annotations

import json
from pathlib import Path

import pytest
from lunar_core.catalogue import CatalogueIntegrityError, load_default_catalogue

ROOT = Path(__file__).resolve().parents[1]


def test_default_catalogue_is_empty_until_official_source_is_added() -> None:
    catalogue = load_default_catalogue(ROOT / "data" / "catalogue" / "sites.json")
    assert catalogue.catalogue_state == "awaiting_official_source"
    assert catalogue.sites == []


def test_corrupt_catalogue_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    path.write_text('{"schema_version":', encoding="utf-8")
    with pytest.raises(CatalogueIntegrityError, match="could not be validated"):
        load_default_catalogue(path)


def test_loaded_catalogue_requires_provenance(tmp_path: Path) -> None:
    path = tmp_path / "sites.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "catalogue_state": "loaded",
        "source_url": None,
        "retrieved_utc": None,
        "sites": [],
    }), encoding="utf-8")
    with pytest.raises(CatalogueIntegrityError):
        load_default_catalogue(path)
