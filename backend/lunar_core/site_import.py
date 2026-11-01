"""Format-tolerant, fail-closed parsing of lunar site lists.

The official challenge site list will only be published on 13 Nov 2026 and its format is unknown.
This module reads the plausible formats (CSV/TSV/semicolon text, XLSX, JSON, GeoJSON, KML) into
plain rows, finds the id/name/latitude/longitude columns through a fixed alias table, and parses
coordinates written as signed decimals, decimals with a hemisphere letter, or degrees-minutes-seconds.

Fail-closed rules (each raises ``SiteImportError`` with the row locator):

* The longitude sign convention is never guessed. It must come from a hemisphere letter on the
  value, a per-row convention column, a header that names it (``east_longitude``), or an explicit
  caller setting. If two of those sources disagree, the row is rejected.
* A negative number that also carries a hemisphere letter is rejected (``-10 W`` is ambiguous).
* Two columns matching the same role are rejected unless the caller maps the role explicitly.
* Comma decimal separators are rejected rather than reinterpreted.

Every parsed row keeps its raw cells verbatim so the caller can store them with the file hash.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

LongitudeDirection = Literal["east_positive", "west_positive"]
LatitudeType = Literal["planetocentric", "planetographic"]

MAX_SOURCE_BYTES = 20 * 1024 * 1024
TEXT_SUFFIXES = {".csv", ".tsv", ".txt", ".tab"}
XLSX_SUFFIXES = {".xlsx", ".xlsm"}
JSON_SUFFIXES = {".json"}
GEOJSON_SUFFIXES = {".geojson"}
KML_SUFFIXES = {".kml"}

# Geometry-derived cells injected for GeoJSON/KML points (spec order is lon, lat; both formats are
# defined for Earth, so lunar use carries no sign convention of its own and still needs one).
GEOM_LAT = "geometry_latitude"
GEOM_LON = "geometry_longitude"

ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("source_site_id", "site_id", "id", "site_code", "code", "identifier", "site_number", "no"),
    "name": ("name", "site_name", "landing_site", "site", "location", "target", "title", "mission"),
    "latitude": (
        "latitude_deg", "latitude", "lat", "lat_deg", "latitude_degrees", "center_latitude",
        "centre_latitude", "planetocentric_latitude", "planetographic_latitude", GEOM_LAT,
    ),
    "longitude": (
        "longitude_deg", "longitude", "lon", "long", "lng", "lon_deg", "longitude_degrees",
        "center_longitude", "centre_longitude", GEOM_LON,
        # Headers that name the convention. Their direction is recorded in HEADER_DIRECTION.
        "east_longitude", "longitude_east", "longitude_e", "lon_east", "lon_e", "elon",
        "longitude_east_positive", "west_longitude", "longitude_west", "longitude_w", "lon_west",
        "lon_w", "wlon",
    ),
    "latitude_type": ("latitude_type", "lat_type", "latitude_system"),
    "longitude_direction": ("longitude_direction", "lon_direction", "longitude_convention", "lon_convention"),
}

HEADER_DIRECTION: dict[str, LongitudeDirection] = {
    **{name: "east_positive" for name in (
        "east_longitude", "longitude_east", "longitude_e", "lon_east", "lon_e", "elon",
        "longitude_east_positive",
    )},
    **{name: "west_positive" for name in (
        "west_longitude", "longitude_west", "longitude_w", "lon_west", "lon_w", "wlon",
    )},
}

DIRECTION_WORDS: dict[str, LongitudeDirection] = {
    "east_positive": "east_positive", "east": "east_positive", "e": "east_positive",
    "+e": "east_positive", "positive_east": "east_positive", "east-positive": "east_positive",
    "west_positive": "west_positive", "west": "west_positive", "w": "west_positive",
    "+w": "west_positive", "positive_west": "west_positive", "west-positive": "west_positive",
}

LATITUDE_TYPE_WORDS: dict[str, LatitudeType] = {
    "planetocentric": "planetocentric", "centric": "planetocentric", "pc": "planetocentric",
    "planetographic": "planetographic", "graphic": "planetographic", "pg": "planetographic",
}


class SiteImportError(ValueError):
    """A site list cannot be read without guessing; nothing should be written."""


@dataclass(frozen=True)
class RawRow:
    locator: str
    cells: dict[str, str]


@dataclass(frozen=True)
class ParsedSite:
    locator: str
    source_id: str
    id_derived_from_name: bool
    name: str
    latitude_deg: float
    longitude_east_deg: float  # canonical east-positive [0, 360)
    latitude_type: LatitudeType
    longitude_rule: str  # how the sign convention for this row was established
    raw: dict[str, str]


@dataclass
class ParseReport:
    source_format: str
    column_map: dict[str, str]
    sites: list[ParsedSite] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalise_header(header: str) -> str:
    """Lower-case, drop bracketed units and degree signs, collapse non-alphanumerics to '_'."""
    text = unicodedata.normalize("NFKC", header).strip().lower()
    # A bracketed unit may carry the longitude convention, e.g. "Longitude (°E)" or "Lon [W]".
    for content in re.findall(r"\(([^)]*)\)|\[([^\]]*)\]", text):
        unit = re.sub(r"[^a-z]+", "", "".join(content).replace("deg", ""))
        if unit in {"e", "east", "eastpositive", "epositive"}:
            text += " east"
        elif unit in {"w", "west", "westpositive", "wpositive"}:
            text += " west"
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    text = text.replace("°", " ")
    text = re.sub(r"[^a-z0-9+]+", "_", text).strip("_")
    return text


# --------------------------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------------------------

def read_rows(source: Path, *, sheet: str | None = None) -> tuple[str, list[RawRow]]:
    if not source.is_file():
        raise FileNotFoundError(source)
    size = source.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise SiteImportError(f"source file is {size} bytes; limit is {MAX_SOURCE_BYTES}")
    suffix = source.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return "delimited_text", _read_delimited(source)
    if suffix in XLSX_SUFFIXES:
        return "xlsx", _read_xlsx(source, sheet)
    if suffix in GEOJSON_SUFFIXES:
        return "geojson", _read_geojson(_load_json(source))
    if suffix in JSON_SUFFIXES:
        payload = _load_json(source)
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            return "geojson", _read_geojson(payload)
        return "json", _read_json_records(payload)
    if suffix in KML_SUFFIXES:
        return "kml", _read_kml(source)
    if suffix == ".pdf":
        raise SiteImportError(
            "PDF tables are not parsed automatically. Transcribe the table to CSV, keep the PDF and "
            "its SHA-256 next to the CSV, and have a second person check every coordinate"
        )
    raise SiteImportError(f"unsupported site-list format {suffix!r}")


def _read_delimited(source: Path) -> list[RawRow]:
    text = source.read_text(encoding="utf-8-sig")
    sample = text[:8192]
    if source.suffix.lower() in {".tsv", ".tab"}:
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    header_index = next((i for i, row in enumerate(rows) if any(cell.strip() for cell in row)), None)
    if header_index is None:
        raise SiteImportError("delimited file is empty")
    headers = [cell.strip() for cell in rows[header_index]]
    _check_unique_headers(headers)
    result: list[RawRow] = []
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(headers):
            raise SiteImportError(f"line {offset}: {len(row)} cells but {len(headers)} headers")
        cells = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
        result.append(RawRow(f"line {offset}", cells))
    return result


def _read_xlsx(source: Path, sheet: str | None) -> list[RawRow]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - dependency is optional
        raise SiteImportError("reading .xlsx needs openpyxl (pip install openpyxl)") from exc
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        if sheet is None:
            if len(workbook.sheetnames) != 1:
                raise SiteImportError(
                    f"workbook has sheets {workbook.sheetnames}; choose one with --sheet"
                )
            worksheet = workbook[workbook.sheetnames[0]]
        else:
            if sheet not in workbook.sheetnames:
                raise SiteImportError(f"sheet {sheet!r} not in {workbook.sheetnames}")
            worksheet = workbook[sheet]
        rows = [["" if v is None else _cell_text(v) for v in row] for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    header_index = next((i for i, row in enumerate(rows) if any(c.strip() for c in row)), None)
    if header_index is None:
        raise SiteImportError("worksheet is empty")
    headers = [c.strip() for c in rows[header_index]]
    while headers and not headers[-1]:
        headers.pop()
    _check_unique_headers(headers)
    result: list[RawRow] = []
    for offset, row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any(c.strip() for c in row):
            continue
        if any(c.strip() for c in row[len(headers):]):
            raise SiteImportError(f"{worksheet.title} row {offset}: values beyond the last header")
        result.append(RawRow(f"{worksheet.title} row {offset}", {h: row[i] if i < len(row) else "" for i, h in enumerate(headers)}))
    return result


def _cell_text(value: Any) -> str:
    if isinstance(value, float):
        # repr keeps every stored digit; str() would too in Python 3, but be explicit.
        return repr(value)
    return str(value)


def _load_json(source: Path) -> Any:
    try:
        return json.loads(source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SiteImportError(f"invalid JSON: {exc}") from exc


def _read_json_records(payload: Any) -> list[RawRow]:
    records: Any = payload
    if isinstance(payload, dict):
        lists = [key for key, value in payload.items() if isinstance(value, list)]
        if len(lists) != 1:
            raise SiteImportError(f"JSON object must hold exactly one list of sites; found lists {lists}")
        records = payload[lists[0]]
    if not isinstance(records, list):
        raise SiteImportError("JSON site list must be an array of objects")
    result: list[RawRow] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SiteImportError(f"record {index}: expected an object")
        result.append(RawRow(f"record {index}", {str(k): _scalar_text(v, f"record {index}") for k, v in record.items()}))
    return result


def _scalar_text(value: Any, locator: str) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise SiteImportError(f"{locator}: boolean where text or number expected")
    if isinstance(value, (int, float, str)):
        return repr(value) if isinstance(value, float) else str(value)
    raise SiteImportError(f"{locator}: nested value {value!r}; flatten the record first")


def _read_geojson(payload: Any) -> list[RawRow]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        raise SiteImportError("GeoJSON must be a FeatureCollection")
    features = payload.get("features")
    if not isinstance(features, list):
        raise SiteImportError("GeoJSON FeatureCollection has no features array")
    result: list[RawRow] = []
    for index, feature in enumerate(features):
        locator = f"feature {index}"
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        if not isinstance(geometry, dict) or geometry.get("type") != "Point":
            raise SiteImportError(f"{locator}: only Point geometries are site locations")
        coords = geometry.get("coordinates")
        if not (isinstance(coords, list) and len(coords) in (2, 3) and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in coords)):
            raise SiteImportError(f"{locator}: Point coordinates must be [lon, lat] or [lon, lat, h]")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise SiteImportError(f"{locator}: properties must be an object")
        cells = {str(k): _scalar_text(v, locator) for k, v in properties.items()}
        if "id" in feature and "id" not in cells:
            cells["id"] = _scalar_text(feature["id"], locator)
        cells[GEOM_LON] = repr(float(coords[0]))
        cells[GEOM_LAT] = repr(float(coords[1]))
        result.append(RawRow(locator, cells))
    return result


def _read_kml(source: Path) -> list[RawRow]:
    text = source.read_text(encoding="utf-8-sig")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise SiteImportError("KML with DOCTYPE/ENTITY declarations is rejected")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SiteImportError(f"invalid KML: {exc}") from exc
    result: list[RawRow] = []
    placemarks = [el for el in root.iter() if _local(el.tag) == "Placemark"]
    for index, placemark in enumerate(placemarks):
        locator = f"placemark {index}"
        cells: dict[str, str] = {}
        for child in placemark:
            if _local(child.tag) == "name" and child.text:
                cells["name"] = child.text.strip()
        for data in (el for el in placemark.iter() if _local(el.tag) == "Data"):
            key = data.get("name")
            value = next((v.text or "" for v in data if _local(v.tag) == "value"), "")
            if key:
                cells[key] = value.strip()
        for data in (el for el in placemark.iter() if _local(el.tag) == "SimpleData"):
            key = data.get("name")
            if key:
                cells[key] = (data.text or "").strip()
        points = [el for el in placemark.iter() if _local(el.tag) == "Point"]
        if len(points) != 1:
            raise SiteImportError(f"{locator}: expected exactly one Point, found {len(points)}")
        coord_el = next((el for el in points[0].iter() if _local(el.tag) == "coordinates"), None)
        parts = (coord_el.text or "").strip().split(",") if coord_el is not None else []
        if len(parts) not in (2, 3):
            raise SiteImportError(f"{locator}: Point coordinates must be 'lon,lat[,alt]'")
        cells[GEOM_LON] = parts[0].strip()
        cells[GEOM_LAT] = parts[1].strip()
        result.append(RawRow(locator, cells))
    return result


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _check_unique_headers(headers: list[str]) -> None:
    seen: dict[str, str] = {}
    for header in headers:
        key = normalise_header(header)
        if not key:
            continue
        if key in seen:
            raise SiteImportError(f"headers {seen[key]!r} and {header!r} normalise to the same name")
        seen[key] = header


# --------------------------------------------------------------------------------------------
# Column roles
# --------------------------------------------------------------------------------------------

def resolve_columns(headers: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Map roles (id, name, latitude, longitude, ...) to source headers; ambiguous matches fail."""
    overrides = dict(overrides or {})
    unknown_roles = set(overrides) - set(ROLE_ALIASES)
    if unknown_roles:
        raise SiteImportError(f"unknown column roles {sorted(unknown_roles)}; valid: {sorted(ROLE_ALIASES)}")
    by_norm = {normalise_header(h): h for h in headers}
    mapping: dict[str, str] = {}
    for role, aliases in ROLE_ALIASES.items():
        if role in overrides:
            header = overrides[role]
            if header not in headers:
                raise SiteImportError(f"--column {role}={header!r}: no such header in {headers}")
            mapping[role] = header
            continue
        matches = [by_norm[a] for a in aliases if a in by_norm]
        matches = list(dict.fromkeys(matches))
        if role == "name" and len(matches) > 1:
            # 'name' beats looser descriptors such as 'mission' or 'target' when both exist.
            matches = matches[:1]
        if len(matches) > 1:
            raise SiteImportError(
                f"several columns could be the {role}: {matches}; choose one with --column {role}=HEADER"
            )
        if matches:
            mapping[role] = matches[0]
    for required in ("name", "latitude", "longitude"):
        if required not in mapping:
            raise SiteImportError(
                f"no {required} column found in headers {headers}; map it with --column {required}=HEADER"
            )
    claimed = [h for h in mapping.values()]
    if len(claimed) != len(set(claimed)):
        raise SiteImportError(f"one header was assigned to two roles: {mapping}")
    return mapping


# --------------------------------------------------------------------------------------------
# Angles
# --------------------------------------------------------------------------------------------

_HEMI = {"N": "lat", "S": "lat", "E": "lon", "W": "lon"}
_AXIS_NAME = {"lat": "latitude", "lon": "longitude"}
_NUMBER = r"[0-9]+(?:\.[0-9]+)?"


def parse_angle(text: str, axis: Literal["lat", "lon"], locator: str) -> tuple[float, str | None]:
    """Return (signed value, hemisphere letter or None). DMS and letter forms are accepted."""
    raw = unicodedata.normalize("NFKC", text).strip()
    if not raw:
        raise SiteImportError(f"{locator}: empty {_AXIS_NAME[axis]}")
    cleaned = raw.replace("−", "-").replace("–", "-")
    cleaned = cleaned.replace("′", "'").replace("’", "'").replace("″", '"').replace("''", '"')
    if re.fullmatch(r"[+-]?[0-9]+,[0-9]+", cleaned.strip()):
        raise SiteImportError(f"{locator}: {raw!r} uses a comma decimal separator; convert it explicitly")
    hemi: str | None = None
    # Hemisphere letters are upper case only, so DMS unit letters (d, m, s) are never mistaken for S.
    match = re.fullmatch(r"([NSEW])\s*(.+)", cleaned) or re.fullmatch(r"(.+?)\s*([NSEW])", cleaned)
    if match:
        a, b = match.groups()
        letter, body = (a, b) if len(a) == 1 and a.upper() in _HEMI else (b, a)
        hemi = letter.upper()
        cleaned = body.strip()
        if _HEMI[hemi] != axis:
            raise SiteImportError(f"{locator}: {raw!r} has hemisphere {hemi!r} on the {_AXIS_NAME[axis]}")
    sign = 1.0
    if cleaned.startswith(("+", "-")):
        sign = -1.0 if cleaned[0] == "-" else 1.0
        cleaned = cleaned[1:].strip()
        if hemi is not None and sign < 0:
            raise SiteImportError(f"{locator}: {raw!r} combines a minus sign and a hemisphere letter")
    dms = re.fullmatch(
        rf"({_NUMBER})\s*(?:°|d|deg|\s)\s*(?:({_NUMBER})\s*(?:'|m|min|\s)\s*(?:({_NUMBER})\s*(?:\"|s|sec)?)?)?",
        cleaned,
    )
    plain = re.fullmatch(rf"({_NUMBER})\s*°?", cleaned)
    if plain:
        value = float(plain.group(1))
    elif dms:
        degrees = float(dms.group(1))
        minutes = float(dms.group(2) or 0.0)
        seconds = float(dms.group(3) or 0.0)
        if (dms.group(2) and not float(dms.group(1)).is_integer()) or (dms.group(3) and not minutes.is_integer()):
            raise SiteImportError(f"{locator}: {raw!r} mixes fractional degrees/minutes with smaller units")
        if minutes >= 60 or seconds >= 60:
            raise SiteImportError(f"{locator}: {raw!r} has minutes or seconds >= 60")
        value = degrees + minutes / 60.0 + seconds / 3600.0
    else:
        raise SiteImportError(f"{locator}: cannot read {_AXIS_NAME[axis]} {raw!r}")
    if not math.isfinite(value):
        raise SiteImportError(f"{locator}: non-finite {_AXIS_NAME[axis]} {raw!r}")
    if hemi in {"S", "W"}:
        value = -value
    return sign * value, hemi


# --------------------------------------------------------------------------------------------
# Row interpretation
# --------------------------------------------------------------------------------------------

def _word(value: str, table: dict[str, Any], what: str, locator: str) -> Any:
    key = value.strip().lower().replace(" ", "_")
    if key not in table:
        raise SiteImportError(f"{locator}: unrecognised {what} {value!r}; expected one of {sorted(set(table))}")
    return table[key]


def parse_sites(
    rows: list[RawRow],
    *,
    source_format: str,
    column_overrides: dict[str, str] | None = None,
    longitude_direction: LongitudeDirection | None = None,
    latitude_type: LatitudeType | None = None,
) -> ParseReport:
    if not rows:
        raise SiteImportError("source contains no site rows")
    headers = list(dict.fromkeys(h for row in rows for h in row.cells))
    mapping = resolve_columns(headers, column_overrides)
    report = ParseReport(source_format=source_format, column_map=mapping)
    lon_header_norm = normalise_header(mapping["longitude"])
    header_direction = HEADER_DIRECTION.get(lon_header_norm)
    seen_ids: dict[str, str] = {}
    seen_coords: dict[tuple[float, float], str] = {}
    for row in rows:
        loc = row.locator
        cells = row.cells
        name = (cells.get(mapping["name"]) or "").strip()
        if not name:
            raise SiteImportError(f"{loc}: empty site name")
        source_id = (cells.get(mapping["id"]) or "").strip() if "id" in mapping else ""
        derived = not source_id
        if derived:
            source_id = name
        id_key = source_id.casefold()
        if id_key in seen_ids:
            raise SiteImportError(f"{loc}: site id {source_id!r} repeats {seen_ids[id_key]}")
        seen_ids[id_key] = loc

        latitude, lat_hemi = parse_angle(cells.get(mapping["latitude"], ""), "lat", loc)
        if not -90.0 <= latitude <= 90.0:
            raise SiteImportError(f"{loc}: latitude {latitude} outside [-90, 90]")
        longitude, lon_hemi = parse_angle(cells.get(mapping["longitude"], ""), "lon", loc)
        if not -360.0 <= longitude <= 360.0:
            raise SiteImportError(f"{loc}: longitude {longitude} outside [-360, 360]")

        # Collect every stated convention and require them to agree.
        stated: dict[str, LongitudeDirection] = {}
        if "longitude_direction" in mapping and (cells.get(mapping["longitude_direction"]) or "").strip():
            stated["row column"] = _word(cells[mapping["longitude_direction"]], DIRECTION_WORDS, "longitude direction", loc)
        if header_direction:
            stated[f"header {mapping['longitude']!r}"] = header_direction
        if longitude_direction:
            stated["caller setting"] = longitude_direction
        if len(set(stated.values())) > 1:
            raise SiteImportError(f"{loc}: conflicting longitude conventions {stated}")
        if lon_hemi is not None:
            if lon_hemi == "W" and header_direction == "east_positive" or lon_hemi == "E" and header_direction == "west_positive":
                raise SiteImportError(f"{loc}: hemisphere {lon_hemi!r} contradicts header {mapping['longitude']!r}")
            east = longitude  # already signed by the letter: E positive, W negative
            rule = f"hemisphere letter {lon_hemi}"
        elif stated:
            direction = next(iter(stated.values()))
            east = longitude if direction == "east_positive" else -longitude
            rule = f"{direction} from " + ", ".join(sorted(stated))
        else:
            raise SiteImportError(
                f"{loc}: longitude {cells.get(mapping['longitude'])!r} has no stated sign convention. "
                "Read the source documentation and pass --longitude-direction east_positive|west_positive"
            )
        east_canonical = east % 360.0
        if east_canonical >= 360.0:  # guard float edge where -tiny % 360 == 360.0
            east_canonical = 0.0

        lat_type: LatitudeType | None = None
        if "latitude_type" in mapping and (cells.get(mapping["latitude_type"]) or "").strip():
            lat_type = _word(cells[mapping["latitude_type"]], LATITUDE_TYPE_WORDS, "latitude type", loc)
            if latitude_type and lat_type != latitude_type:
                raise SiteImportError(f"{loc}: row latitude type {lat_type} contradicts caller setting {latitude_type}")
        else:
            header_norm = normalise_header(mapping["latitude"])
            if header_norm.startswith("planetographic"):
                lat_type = "planetographic"
            elif header_norm.startswith("planetocentric"):
                lat_type = "planetocentric"
            lat_type = lat_type or latitude_type
        if lat_type is None:
            raise SiteImportError(
                f"{loc}: latitude type not stated. Pass --latitude-type. (On the IAU spherical Moon used "
                "here, planetocentric and planetographic latitude are numerically equal.)"
            )
        key = (round(latitude, 6), round(east_canonical, 6))
        if key in seen_coords:
            report.warnings.append(f"{loc}: same coordinates as {seen_coords[key]}")
        seen_coords[key] = loc
        report.sites.append(ParsedSite(
            locator=loc, source_id=source_id, id_derived_from_name=derived, name=name,
            latitude_deg=latitude, longitude_east_deg=east_canonical, latitude_type=lat_type,
            longitude_rule=rule, raw=dict(cells),
        ))
    return report


def parse_site_file(
    source: Path,
    *,
    sheet: str | None = None,
    column_overrides: dict[str, str] | None = None,
    longitude_direction: LongitudeDirection | None = None,
    latitude_type: LatitudeType | None = None,
) -> ParseReport:
    fmt, rows = read_rows(source, sheet=sheet)
    return parse_sites(
        rows, source_format=fmt, column_overrides=column_overrides,
        longitude_direction=longitude_direction, latitude_type=latitude_type,
    )
