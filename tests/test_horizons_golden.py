"""Offline tests for the Horizons golden-geometry tool (network replaced by a fake fetcher)."""
from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import horizons_golden as golden

SAMPLE_RESULT = """*******************************************************************************
Ephemeris / API_USER
*******************************************************************************
 Date_________JDUT, , ,  Azi____(a-app),  Elev____(a-app),             delta,     deldot,
*******************************************************************************
$$SOE
 2461406.500000000, , ,  12.3456789012, -0.1234567890,  1.47109876543E+08,  0.1234567,
$$EOE
*******************************************************************************
"""


def test_parse_observer_csv_reads_azimuth_elevation_and_range() -> None:
    parsed = golden.parse_observer_csv(SAMPLE_RESULT)
    assert parsed == {"azimuth_deg": 12.3456789012, "elevation_deg": -0.123456789, "range_km": 1.47109876543e8}


def test_parse_rejects_missing_ephemeris_block() -> None:
    with pytest.raises(ValueError, match="SOE"):
        golden.parse_observer_csv("No ephemeris for target")


def test_query_uses_lunar_surface_site_airless_apparent_and_utc_jd() -> None:
    params = golden.build_query("EARTH", -2.93, -85.99, 0.002, 2461406.5)
    assert params["COMMAND"] == "'399'"
    assert params["CENTER"] == "'coord@301'"
    assert params["SITE_COORD"] == "'357.070000000,-85.990000000,0.002000000'"
    assert params["APPARENT"] == "'AIRLESS'" and params["TIME_TYPE"] == "'UT'"
    url = golden.query_url(params)
    assert url.startswith("https://ssd.jpl.nasa.gov/api/horizons.api?")
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["QUANTITIES"] == ["'4,20'"]


def test_utc_to_jd_matches_known_epoch() -> None:
    assert golden.utc_to_jd("2000-01-01T12:00:00.000Z") == pytest.approx(2451545.0, abs=1e-9)
    with pytest.raises(ValueError):
        golden.utc_to_jd("2000-01-01T12:00:00")


def test_select_epochs_includes_ends_middle_and_near_horizon_samples() -> None:
    series = [{"sun_elevation_deg": 3.0 - i, "earth_elevation_deg": 5.0} for i in range(7)]
    series[5]["earth_elevation_deg"] = 0.2
    chosen = dict(golden.select_epochs(series))
    assert set(chosen) == {0, 3, 6, 5}
    assert chosen[3] is True   # Sun elevation 0.0 at index 3
    assert chosen[5] is True   # Earth elevation 0.2 at index 5
    assert chosen[0] is False


def _run(tmp_path: Path, created: datetime) -> Path:
    start = datetime(2027, 1, 1, tzinfo=UTC)
    def series() -> list[dict[str, float | str]]:
        return [{
            "utc": (start + timedelta(minutes=30 * i)).isoformat().replace("+00:00", "Z"),
            "sun_azimuth_deg": 10.0 + i, "sun_elevation_deg": 1.0 - 0.5 * i, "sun_range_m": 1.5e11,
            "earth_azimuth_deg": 359.0, "earth_elevation_deg": 4.0, "earth_range_m": 3.8e8,
        } for i in range(5)]
    run = {
        "run_id": "00000000-0000-4000-8000-000000000001", "analysis_kind": "spice_backed_analysis",
        "validation_status": "computed_not_independently_validated",
        "created_utc": created.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "settings": {"sun_observer_height_m": 2.0, "antenna_height_m": 2.0},
        "sites": [
            {"site": {"site_id": sid, "latitude_deg": lat, "longitude_deg": 10.0}, "terrain": {}, "series": series()}
            for sid, lat in (("site-a", -89.0), ("site-b", -86.0))
        ],
    }
    path = tmp_path / "run.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    return path


def _fake_fetcher(run_path: Path, offset_deg: float):
    run = json.loads(run_path.read_text(encoding="utf-8"))
    def fetch(url: str) -> dict[str, str]:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        target = "SUN" if query["COMMAND"] == ["'10'"] else "EARTH"
        jd = float(query["TLIST"][0].strip("'"))
        when = datetime.fromtimestamp((jd - golden.JD_UNIX_EPOCH) * 86_400.0, tz=UTC)
        row = min(run["sites"][0]["series"], key=lambda r: abs(datetime.fromisoformat(r["utc"]) - when))
        prefix = target.lower()
        text = SAMPLE_RESULT.replace("12.3456789012", repr(row[f"{prefix}_azimuth_deg"] + offset_deg)) \
            .replace("-0.1234567890", repr(row[f"{prefix}_elevation_deg"])) \
            .replace("1.47109876543E+08", repr(row[f"{prefix}_range_m"] / 1000.0))
        return {"result": text}
    return fetch


def _tolerances(tmp_path: Path, declared: datetime) -> Path:
    path = tmp_path / "tol.json"
    path.write_text(json.dumps({
        "status": "approved_before_run", "approved_by": "test",
        "predeclared_utc": declared.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "azimuth_tolerance_arcsec": 1.0, "elevation_tolerance_arcsec": 1.0, "range_tolerance_km": 1.0,
        "minimum_site_count": 2, "minimum_epochs_per_site": 3, "requires_near_horizon_epoch": True,
    }), encoding="utf-8")
    return path


def test_end_to_end_pass_and_fail_with_archived_raw_responses(tmp_path: Path) -> None:
    created = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    run_path = _run(tmp_path, created)
    tolerances = _tolerances(tmp_path, created - timedelta(minutes=30))

    reference = golden.build_reference(run_path, tmp_path / "ev", pause_s=0.0, fetcher=_fake_fetcher(run_path, 0.0))
    report = golden.compare_run(run_path, reference, tolerances, tmp_path / "ok.json")
    assert report["passed"] and report["max_azimuth_error_arcsec"] < 1e-6
    raw_files = list((tmp_path / "ev" / "horizons_raw").rglob("*.json"))
    assert len(raw_files) == report["reference_count"]
    assert json.loads(raw_files[0].read_text())["query_url"].startswith(golden.HORIZONS_API)

    shifted = golden.build_reference(run_path, tmp_path / "ev2", pause_s=0.0,
                                     fetcher=_fake_fetcher(run_path, 2.0 / 3600.0))
    failed = golden.compare_run(run_path, shifted, tolerances, tmp_path / "bad.json")
    assert not failed["passed"]
    assert failed["max_azimuth_error_arcsec"] == pytest.approx(2.0, abs=1e-6)


def test_comparison_refuses_tolerances_declared_after_the_run(tmp_path: Path) -> None:
    created = datetime(2026, 10, 28, 9, 0, tzinfo=UTC)
    run_path = _run(tmp_path, created)
    reference = golden.build_reference(run_path, tmp_path / "ev", pause_s=0.0, fetcher=_fake_fetcher(run_path, 0.0))
    with pytest.raises(ValueError, match="not declared before"):
        golden.compare_run(run_path, reference, _tolerances(tmp_path, created + timedelta(hours=1)), tmp_path / "r.json")
