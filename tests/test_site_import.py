"""Format-tolerant site import: every plausible official format reads the same, ambiguity fails."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
from import_official_sites import import_catalogue  # noqa: E402
from lunar_core.site_import import (  # noqa: E402
    SiteImportError,
    normalise_header,
    parse_angle,
    parse_site_file,
)

URL = "https://www.spaceappschallenge.org/2026/challenges/clps-lunar-mission-browser/"

# Two sites written several ways. Expected canonical east-positive values:
#   Alpha: -84.79, 1.44 E      Beta: 26.13 N, 3.63 E -> but written west of 0 below as 356.37 E
EXPECTED = {"Alpha Ridge": (-84.79, 1.44), "Beta Plain": (26.13, 356.37)}


def _check(report) -> None:
    got = {s.name: (s.latitude_deg, s.longitude_east_deg) for s in report.sites}
    assert set(got) == set(EXPECTED)
    for name, (lat, lon) in EXPECTED.items():
        assert got[name][0] == pytest.approx(lat, abs=1e-9)
        assert got[name][1] == pytest.approx(lon, abs=1e-9)


# --- angles -------------------------------------------------------------------------------

@pytest.mark.parametrize(("text", "axis", "value", "hemi"), [
    ("-89.1", "lat", -89.1, None),
    ("89.1 S", "lat", -89.1, "S"),
    ("S 89.1", "lat", -89.1, "S"),
    ("89°06'00\"S", "lat", -89.1, "S"),
    ("89° 6′ 0″ S", "lat", -89.1, "S"),
    ("89 6 0 S", "lat", -89.1, "S"),
    ("89d6m0s", "lat", 89.1, None),
    ("3.63 W", "lon", -3.63, "W"),
    ("−5.5", "lon", -5.5, None),
    ("357.07", "lon", 357.07, None),
])
def test_angle_forms(text: str, axis: str, value: float, hemi: str | None) -> None:
    got, got_hemi = parse_angle(text, axis, "t")  # type: ignore[arg-type]
    assert got == pytest.approx(value)
    assert got_hemi == hemi


@pytest.mark.parametrize(("text", "axis", "message"), [
    ("-10 W", "lon", "minus sign and a hemisphere"),
    ("10 N", "lon", "hemisphere 'N' on the longitude"),
    ("89,5", "lat", "comma decimal"),
    ("12.5°30'", "lat", "mixes fractional"),
    ("10 61'", "lat", ">= 60"),
    ("", "lat", "empty latitude"),
    ("north-ish", "lat", "cannot read"),
])
def test_angle_rejections(text: str, axis: str, message: str) -> None:
    with pytest.raises(SiteImportError, match=message):
        parse_angle(text, axis, "t")  # type: ignore[arg-type]


def test_bracketed_units_keep_longitude_convention() -> None:
    assert normalise_header("Longitude (°E)") == "longitude_east"
    assert normalise_header("Lon [W]") == "lon_west"
    assert normalise_header("Latitude (deg)") == "latitude"


# --- formats ------------------------------------------------------------------------------

def test_template_csv_still_imports(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text(
        "source_site_id,name,latitude_deg,longitude_deg,latitude_type,longitude_direction\n"
        "a,Alpha Ridge,-84.79,1.44,planetocentric,east_positive\n"
        "b,Beta Plain,26.13,3.63,planetocentric,west_positive\n",
        encoding="utf-8",
    )
    _check(parse_site_file(src))


def test_semicolon_csv_with_hemisphere_letters_and_units(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text(
        "Site Name;Latitude (deg);Longitude (deg)\n"
        "Alpha Ridge;84.79 S;1.44 E\n"
        "Beta Plain;26.13 N;3.63 W\n",
        encoding="utf-8",
    )
    report = parse_site_file(src, latitude_type="planetocentric")
    _check(report)
    assert all(s.id_derived_from_name for s in report.sites)
    assert report.sites[0].longitude_rule == "hemisphere letter E"


def test_tsv_with_dms(tmp_path: Path) -> None:
    src = tmp_path / "t.tsv"
    src.write_text(
        "id\tname\tlat\tlon\n"
        "1\tAlpha Ridge\t84°47'24\"S\t1°26'24\"E\n"
        "2\tBeta Plain\t26°07'48\"N\t3°37'48\"W\n",
        encoding="utf-8",
    )
    _check(parse_site_file(src, latitude_type="planetocentric"))


def test_header_named_convention(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,latitude,Longitude (°E)\nAlpha Ridge,-84.79,1.44\nBeta Plain,26.13,-3.63\n", encoding="utf-8")
    report = parse_site_file(src, latitude_type="planetocentric")
    _check(report)
    assert "header" in report.sites[0].longitude_rule


def test_xlsx_single_sheet(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    src = tmp_path / "t.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Landing Site", "Latitude", "Longitude"])
    ws.append(["Alpha Ridge", -84.79, 1.44])
    ws.append(["Beta Plain", 26.13, -3.63])
    wb.save(src)
    _check(parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric"))


def test_xlsx_multi_sheet_requires_choice(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    src = tmp_path / "t.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Notes"
    ws = wb.create_sheet("Sites")
    ws.append(["name", "lat", "lon"])
    ws.append(["Alpha Ridge", -84.79, 1.44])
    ws.append(["Beta Plain", 26.13, 356.37])
    wb.save(src)
    with pytest.raises(SiteImportError, match="--sheet"):
        parse_site_file(src)
    _check(parse_site_file(src, sheet="Sites", longitude_direction="east_positive", latitude_type="planetocentric"))


def test_json_records(tmp_path: Path) -> None:
    src = tmp_path / "t.json"
    src.write_text(json.dumps({"landing_sites": [
        {"name": "Alpha Ridge", "lat": -84.79, "lon": 1.44, "longitude_direction": "east"},
        {"name": "Beta Plain", "lat": 26.13, "lon": 356.37, "longitude_direction": "east"},
    ]}), encoding="utf-8")
    _check(parse_site_file(src, latitude_type="planetocentric"))


def test_geojson_points_use_lon_lat_order(tmp_path: Path) -> None:
    src = tmp_path / "t.geojson"
    src.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": "Alpha Ridge"}, "geometry": {"type": "Point", "coordinates": [1.44, -84.79]}},
        {"type": "Feature", "properties": {"name": "Beta Plain"}, "geometry": {"type": "Point", "coordinates": [-3.63, 26.13]}},
    ]}), encoding="utf-8")
    with pytest.raises(SiteImportError, match="no stated sign convention"):
        parse_site_file(src, latitude_type="planetocentric")
    _check(parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric"))


def test_kml_placemarks(tmp_path: Path) -> None:
    src = tmp_path / "t.kml"
    src.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        '<Placemark><name>Alpha Ridge</name><Point><coordinates>1.44,-84.79,0</coordinates></Point></Placemark>'
        '<Placemark><name>Beta Plain</name><ExtendedData><Data name="code"><value>B</value></Data></ExtendedData>'
        '<Point><coordinates>356.37,26.13</coordinates></Point></Placemark>'
        '</Document></kml>',
        encoding="utf-8",
    )
    report = parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric")
    _check(report)
    assert report.sites[1].raw["code"] == "B"


def test_kml_with_entities_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "t.kml"
    src.write_text('<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY a "x">]><kml/>', encoding="utf-8")
    with pytest.raises(SiteImportError, match="DOCTYPE"):
        parse_site_file(src)


def test_pdf_is_refused_with_transcription_advice(tmp_path: Path) -> None:
    src = tmp_path / "t.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(SiteImportError, match="Transcribe"):
        parse_site_file(src)


# --- fail-closed rules -------------------------------------------------------------------

def test_conflicting_conventions_are_rejected(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,east_longitude,longitude_direction\nAlpha,-84,1.4,west\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="conflicting longitude conventions"):
        parse_site_file(src, latitude_type="planetocentric")


def test_letter_contradicting_header_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,West Longitude\nAlpha,-84,1.4 E\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="contradicts header"):
        parse_site_file(src, latitude_type="planetocentric")


def test_ambiguous_columns_need_explicit_mapping(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,latitude,lon\nAlpha,-84,-85,1\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="several columns could be the latitude"):
        parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric")
    report = parse_site_file(src, column_overrides={"latitude": "latitude"},
                             longitude_direction="east_positive", latitude_type="planetocentric")
    assert report.sites[0].latitude_deg == -85.0


def test_missing_latitude_type_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon\nAlpha,-84,1\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="latitude type not stated"):
        parse_site_file(src, longitude_direction="east_positive")


def test_duplicate_ids_rejected_and_duplicate_coordinates_warned(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon\nAlpha,-84,1\nalpha,-80,2\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="repeats"):
        parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric")
    src.write_text("name,lat,lon\nAlpha,-84,1\nBeta,-84,361\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="outside"):
        parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric")
    src.write_text("name,lat,lon\nAlpha,-84,1\nBeta,-84,-359\n", encoding="utf-8")
    report = parse_site_file(src, longitude_direction="east_positive", latitude_type="planetocentric")
    assert report.warnings and "same coordinates" in report.warnings[0]


def test_ragged_row_is_rejected(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon\nAlpha,-84,1,extra\n", encoding="utf-8")
    with pytest.raises(SiteImportError, match="cells but"):
        parse_site_file(src)


# --- end-to-end import -------------------------------------------------------------------

def test_import_writes_catalogue_sidecar_and_archived_copy(tmp_path: Path) -> None:
    src = tmp_path / "official sites.csv"
    src.write_text("Site Name;Latitude;Longitude\nAlpha Ridge;84.79 S;1.44 E\nBeta Plain;26.13 N;3.63 W\n", encoding="utf-8")
    out = tmp_path / "catalogue" / "sites.json"
    result = import_catalogue(src, URL, out, latitude_type="planetocentric")
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    assert result["source_file_sha256"] == digest
    catalogue = json.loads(out.read_text(encoding="utf-8"))
    assert [s["site_id"] for s in catalogue["sites"]] == ["official-alpha-ridge", "official-beta-plain"]
    assert catalogue["sites"][1]["longitude_deg"] == pytest.approx(356.37)
    record = json.loads(catalogue["sites"][1]["source_record"])
    assert record["source_row"]["Longitude"] == "3.63 W"
    assert record["longitude_rule"] == "hemisphere letter W"
    sidecar = json.loads((out.parent / "sites.source_rows.json").read_text(encoding="utf-8"))
    assert sidecar["source_file_sha256"] == digest
    archived = out.parent / sidecar["archived_copy"]
    assert archived.read_bytes() == src.read_bytes()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon\nAlpha,-84,1\n", encoding="utf-8")
    out = tmp_path / "out" / "sites.json"
    result = import_catalogue(src, URL, out, longitude_direction="east_positive",
                              latitude_type="planetocentric", dry_run=True)
    assert result["rows"][0]["longitude_east_deg"] == 1.0
    assert not out.parent.exists()


def test_long_rows_go_to_sidecar_not_truncated(tmp_path: Path) -> None:
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon,notes\nAlpha,-84,1," + "x" * 3000 + "\n", encoding="utf-8")
    out = tmp_path / "sites.json"
    import_catalogue(src, URL, out, longitude_direction="east_positive", latitude_type="planetocentric")
    record = json.loads(json.loads(out.read_text())["sites"][0]["source_record"])
    assert "source_row" not in record and len(record["source_row_sha256"]) == 64
    sidecar = json.loads((tmp_path / "sites.source_rows.json").read_text())
    assert len(sidecar["rows"][0]["raw"]["notes"]) == 3000


def test_failed_import_leaves_existing_catalogue_untouched(tmp_path: Path) -> None:
    out = tmp_path / "sites.json"
    out.write_text("previous", encoding="utf-8")
    src = tmp_path / "t.csv"
    src.write_text("name,lat,lon\nAlpha,-84,1\n", encoding="utf-8")
    with pytest.raises(SiteImportError):
        import_catalogue(src, URL, out, latitude_type="planetocentric")
    assert out.read_text(encoding="utf-8") == "previous"
