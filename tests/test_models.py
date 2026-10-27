from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from lunar_core.models import SiteCatalogue, SiteRecord

FIXTURES = Path(__file__).parent / "fixtures"


def test_synthetic_fixture_records_validate_but_remain_synthetic() -> None:
    records = json.loads((FIXTURES / "synthetic_sites.json").read_text(encoding="utf-8"))
    sites = [SiteRecord.model_validate(record) for record in records]
    assert len(sites) == 2
    assert {site.origin for site in sites} == {"synthetic"}
    assert all(site.site_id.startswith("synthetic-") for site in sites)


def test_official_site_requires_sourced_coordinates_and_utc_timestamp() -> None:
    payload = {
        "site_id": "official-test-001",
        "name": "Example from an official source",
        "origin": "official",
        "latitude_deg": -89.5,
        "longitude_deg": 10.0,
        "latitude_type": "planetocentric",
        "longitude_direction": "east_positive",
        "source_url": "https://example.nasa.gov/sites.csv",
        "source_record": "row 4; SHA-256 to be recorded in the manifest",
        "retrieved_utc": datetime(2026, 10, 28, tzinfo=timezone.utc),
        "terrain_status": "none",
        "dem_assets": [],
    }
    site = SiteRecord.model_validate(payload)
    assert site.origin == "official"

    payload["retrieved_utc"] = datetime(2026, 10, 28)  # naive timestamp is not auditable
    with pytest.raises(ValidationError, match="must include a timezone"):
        SiteRecord.model_validate(payload)


def test_official_record_cannot_use_synthetic_id() -> None:
    with pytest.raises(ValidationError, match="must start with 'official-'"):
        SiteRecord.model_validate({
            "site_id": "synthetic-labeled-as-official",
            "name": "Wrong origin",
            "origin": "official",
            "latitude_deg": -89.5,
            "longitude_deg": 12.0,
            "latitude_type": "planetocentric",
            "longitude_direction": "east_positive",
            "source_url": "https://example.nasa.gov/sites.csv",
            "source_record": "test",
            "retrieved_utc": datetime(2026, 10, 28, tzinfo=timezone.utc),
            "terrain_status": "none",
            "dem_assets": [],
        })


def test_default_catalogue_rejects_synthetic_records() -> None:
    with pytest.raises(ValidationError, match="must never contain synthetic"):
        SiteCatalogue.model_validate({
            "schema_version": "1.0",
            "catalogue_state": "loaded",
            "source_url": "https://example.nasa.gov/sites.csv",
            "retrieved_utc": datetime(2026, 10, 28, tzinfo=timezone.utc),
            "sites": [json.loads((FIXTURES / "synthetic_sites.json").read_text(encoding="utf-8"))[0]],
        })
