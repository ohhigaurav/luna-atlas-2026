"""Event-day path: site index (official first), warm order, and the event_day tool's pieces."""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from lunar_core.models import SiteCatalogue
from lunar_core.references import load_reference_catalogue
from lunar_core.site_index import build_site_index

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import event_day  # noqa: E402

OFFICIAL = {
    "schema_version": "1.0", "catalogue_state": "loaded",
    "source_url": "https://www.spaceappschallenge.org/2026/challenges/x", "retrieved_utc": "2026-11-13T05:00:00Z",
    "sites": [
        {"site_id": "official-a", "name": "Official A", "origin": "official", "latitude_deg": -89.45,
         "longitude_deg": -137.31, "latitude_type": "planetocentric", "longitude_direction": "east_positive",
         "source_url": "https://www.spaceappschallenge.org/2026/challenges/x", "source_record": "row 2",
         "retrieved_utc": "2026-11-13T05:00:00Z", "terrain_status": "none"},
    ],
}


def test_site_index_official_first_and_separate() -> None:
    official = SiteCatalogue.model_validate(OFFICIAL)
    ref = load_reference_catalogue()
    idx = build_site_index(official, ref)
    assert idx["official_state"] == "loaded" and idx["official_count"] == 1
    assert idx["sites"][0]["site_id"] == "official-a" and idx["sites"][0]["origin"] == "official"
    assert idx["sites"][0]["longitude_deg"] == pytest.approx(222.69)
    assert idx["sites"][0]["group"] == "Official challenge sites"
    assert idx["unplaced_official"] == []  # the model already refuses official rows without coordinates
    assert all(s["origin"] == "reference" for s in idx["sites"][1:])
    assert idx["reference_count"] == len(ref.sites)


def test_site_index_empty_official_and_id_clash() -> None:
    empty = SiteCatalogue.model_validate({"schema_version": "1.0", "catalogue_state": "awaiting_official_source",
                                          "source_url": None, "retrieved_utc": None, "sites": []})
    ref = load_reference_catalogue()
    idx = build_site_index(empty, ref)
    assert idx["official_count"] == 0 and idx["official_state"] == "awaiting_official_source"
    # Official IDs must start with "official-" (model) and reference IDs with "reference-", so the
    # index's clash guard is a second line of defence only.
    assert all(s.site_id.startswith("reference-") for s in ref.sites)


def test_distance_and_nearest() -> None:
    assert event_day.surface_km(0, 0, 0, 0) == 0.0
    # 1 deg of arc on the 1737.4 km sphere = 30.32 km
    assert event_day.surface_km(0, 0, 0, 1) == pytest.approx(30.3233, abs=1e-3)
    assert event_day.surface_km(-90, 0, -90, 123) == pytest.approx(0.0, abs=1e-9)
    refs = [{"site_id": "a", "name": "A", "latitude_deg": -89.45, "longitude_deg": 222.69},
            {"site_id": "b", "name": "B", "latitude_deg": -85.99, "longitude_deg": 357.07}]
    ref, d = event_day.nearest_reference(-89.45, -137.31 % 360, refs)
    assert ref["site_id"] == "a" and d < 1e-6


def test_import_command_is_dry_run_unless_write() -> None:
    base = dict(source=Path("x.csv"), source_url="https://e/x", longitude_direction="east_positive", latitude_type=None,
                column=["latitude=Lat (deg)"], sheet=None, write=False)
    cmd = event_day.import_command(argparse.Namespace(**base))
    assert cmd[-1] == "--dry-run" and "--longitude-direction" in cmd and "latitude=Lat (deg)" in cmd
    assert "--dry-run" not in event_day.import_command(argparse.Namespace(**{**base, "write": True}))


def test_site_row_and_report() -> None:
    site = {"site_id": "official-a", "name": "Official A", "latitude_deg": -89.45, "longitude_deg": 222.69}
    refs = [{"site_id": "r", "name": "Ref far", "latitude_deg": -85.0, "longitude_deg": 0.0}]
    landing: dict[str, Any] = {"horizon_mode": "terrain", "terrain": {"finest_resolution_m": 5.0},
                               "opportunity_count": 1, "closest_miss": None,
                               "summary": ["Next landing opportunity ..."], "opportunities": [{
                                   "touchdown_from_utc": "2027-01-09T21:00:00Z", "touchdown_until_utc": "2027-01-23T21:00:00Z",
                                   "best_touchdown_utc": "2027-01-09T21:00:00Z", "sun_elevation_at_best_deg": 1.07,
                                   "daylight_after_best_h": 770.0, "daylight_is_lower_bound": True,
                                   "earth_in_view_during_mission_pct": 100.0}]}
    row = event_day.site_row(site, landing, None, refs)
    assert row["polar"] and row["next_window"]["sun_deg"] == 1.07 and row["nearest_reference"]["km"] > 5
    bad = event_day.site_row({**site, "site_id": "x", "name": "X"}, None, "TerrainNotReady: no DEM", refs)
    md = event_day.report_markdown([row, bad], [], {"created_utc": "s", "official_count": 2, "unplaced": 0,
                                                    "source_url": "u", "start_utc": "2027-01-01T00:00:00Z"})
    assert "2027-01-09T21:00 → 2027-01-23T21:00" in md and "≥ 32 d 2 h" in md and "⚠" in md
    assert "error: TerrainNotReady" in md and "| 5 m |" in md


def test_warm_puts_official_sites_first(monkeypatch: pytest.MonkeyPatch) -> None:
    from lunar_core import catalogue, landing, warm

    asked: list[str] = []
    monkeypatch.setattr(catalogue, "load_default_catalogue", lambda: SiteCatalogue.model_validate(OFFICIAL))
    monkeypatch.setattr(landing, "run_landing", lambda req: asked.append(req.site_id) or {"cache_hit": True})
    done, failed = warm.warm_once(datetime(2027, 1, 1, tzinfo=UTC).strftime("%Y-%m-%dT00:00:00Z"))
    assert asked[0] == "official-a" and failed == 0
    assert done == 1 + len(load_reference_catalogue().sites)


def test_site_notes_attach_and_validate(tmp_path: Path) -> None:
    from lunar_core.site_index import load_site_notes

    notes = load_site_notes()  # the real file: every note names its evidence, every ID exists
    assert "reference-malapert-massif" in notes
    empty = SiteCatalogue.model_validate({"schema_version": "1.0", "catalogue_state": "awaiting_official_source",
                                          "source_url": None, "retrieved_utc": None, "sites": []})
    idx = build_site_index(empty, load_reference_catalogue(), notes)
    mal = next(s for s in idx["sites"] if s["site_id"] == "reference-malapert-massif")
    assert mal["analysis_note"]["suggested_point"]["longitude_deg"] == pytest.approx(2.1013)
    assert Path(__file__).resolve().parents[1].joinpath(mal["analysis_note"]["evidence"]).is_file()
    with pytest.raises(ValueError, match="unknown"):
        build_site_index(empty, load_reference_catalogue(), {"reference-nope": {"text": "x", "evidence": "y"}})
    bad = tmp_path / "n.json"
    bad.write_text('{"notes": {"reference-malapert-massif": {"text": "x"}}}')
    with pytest.raises(ValueError, match="evidence"):
        load_site_notes(bad)
    assert load_site_notes(tmp_path / "missing.json") == {}
