#!/usr/bin/env python3
"""Import the official challenge site list into data/catalogue/sites.json.

Accepted inputs: CSV/TSV/semicolon text, XLSX (one sheet or --sheet), JSON records, GeoJSON
Point features and KML Placemarks. Column names are matched through the alias table in
``lunar_core.site_import``; anything ambiguous stops the import (see that module's docstring).

The original template header still works unchanged:
  source_site_id,name,latitude_deg,longitude_deg,latitude_type,longitude_direction

Provenance kept for every import:
* SHA-256 of the unmodified source file, and a byte-identical copy under <output dir>/sources/;
* per site: the source locator (line/row/feature), the raw cells verbatim and how the longitude
  sign convention was established;
* a sidecar <output stem>.source_rows.json with every raw row, the column map and warnings
  (needed because a site's source_record field is capped at 2000 characters).

Use --dry-run first: it prints the interpretation of every row and writes nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.models import SiteCatalogue  # noqa: E402
from lunar_core.provenance import sha256_file  # noqa: E402
from lunar_core.site_import import (  # noqa: E402
    LatitudeType,
    LongitudeDirection,
    ParseReport,
    SiteImportError,
    parse_site_file,
)

SOURCE_RECORD_LIMIT = 2000


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not result:
        raise SiteImportError(f"site id/name {value!r} must contain at least one ASCII letter or digit")
    return result[:80]


def check_official_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    official = (
        host == "spaceappschallenge.org" or host.endswith(".spaceappschallenge.org")
        or host == "nasa.gov" or host.endswith(".nasa.gov")
    )
    if parsed.scheme != "https" or not official:
        raise ValueError(
            "--source-url must be HTTPS on spaceappschallenge.org or a NASA-owned .nasa.gov host; "
            "unofficial research references belong in data/reference, never the official catalogue"
        )


def _source_record(source_hash: str, site_locator: str, raw: dict[str, str], rule: str, derived: bool) -> str:
    record: dict[str, Any] = {
        "source_file_sha256": source_hash,
        "source_locator": site_locator,
        "longitude_rule": rule,
        "id_derived_from_name": derived,
        "source_row": raw,
    }
    text = json.dumps(record, sort_keys=True, ensure_ascii=False)
    if len(text) <= SOURCE_RECORD_LIMIT:
        return text
    row_hash = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    record.pop("source_row")
    record["source_row_sha256"] = row_hash
    record["source_row_in"] = "sidecar source_rows.json (row exceeded source_record limit)"
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def build_catalogue(report: ParseReport, source_hash: str, source_url: str, retrieved: str) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    for site in report.sites:
        site_id = f"official-{_slug(site.source_id)}"
        if site_id in seen:
            raise SiteImportError(f"{site.locator}: duplicate normalised site ID {site_id}")
        seen.add(site_id)
        sites.append({
            "site_id": site_id,
            "name": site.name,
            "origin": "official",
            "latitude_deg": site.latitude_deg,
            "longitude_deg": site.longitude_east_deg,
            "latitude_type": site.latitude_type,
            "longitude_direction": "east_positive",
            "source_url": source_url,
            "source_record": _source_record(source_hash, site.locator, site.raw, site.longitude_rule, site.id_derived_from_name),
            "retrieved_utc": retrieved,
            "terrain_status": "none",
            "dem_assets": [],
        })
    return {
        "schema_version": "1.0",
        "catalogue_state": "loaded",
        "source_url": source_url,
        "retrieved_utc": retrieved,
        "sites": sites,
    }


def import_catalogue(
    source: Path,
    source_url: str,
    output: Path,
    *,
    sheet: str | None = None,
    column_overrides: dict[str, str] | None = None,
    longitude_direction: LongitudeDirection | None = None,
    latitude_type: LatitudeType | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    check_official_url(source_url)
    report = parse_site_file(
        source, sheet=sheet, column_overrides=column_overrides,
        longitude_direction=longitude_direction, latitude_type=latitude_type,
    )
    source_hash = sha256_file(source)
    retrieved = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    catalogue = build_catalogue(report, source_hash, source_url, retrieved)
    # Validate exactly the schema used by the runtime before anything is written.
    parsed = SiteCatalogue.model_validate(catalogue)
    summary: dict[str, Any] = {
        "catalogue_state": parsed.catalogue_state,
        "site_count": len(parsed.sites),
        "source_format": report.source_format,
        "source_file_sha256": source_hash,
        "column_map": report.column_map,
        "warnings": report.warnings,
        "retrieved_utc": retrieved,
        "rows": [
            {
                "locator": s.locator, "site_id": c["site_id"], "name": s.name,
                "latitude_deg": s.latitude_deg, "longitude_east_deg": s.longitude_east_deg,
                "latitude_type": s.latitude_type, "longitude_rule": s.longitude_rule,
                "raw_latitude": s.raw.get(report.column_map["latitude"]),
                "raw_longitude": s.raw.get(report.column_map["longitude"]),
            }
            for s, c in zip(report.sites, catalogue["sites"], strict=True)
        ],
        "dry_run": dry_run,
    }
    if dry_run:
        return summary

    archive_dir = output.parent / "sources"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived = archive_dir / f"{source_hash[:16]}_{source.name}"
    if archived.exists() and sha256_file(archived) != source_hash:
        raise SiteImportError(f"archive path {archived} exists with different contents")
    if not archived.exists():
        shutil.copyfile(source, archived)
    if sha256_file(archived) != source_hash:
        raise SiteImportError("archived source copy does not match the source hash")

    sidecar = output.with_name(output.stem + ".source_rows.json")
    sidecar_payload = {
        "source_file": source.name,
        "source_file_sha256": source_hash,
        "archived_copy": str(archived.relative_to(output.parent)),
        "source_url": source_url,
        "retrieved_utc": retrieved,
        "source_format": report.source_format,
        "column_map": report.column_map,
        "warnings": report.warnings,
        "rows": [
            {"locator": s.locator, "site_id": c["site_id"], "longitude_rule": s.longitude_rule, "raw": s.raw}
            for s, c in zip(report.sites, catalogue["sites"], strict=True)
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    for path, payload in ((sidecar, sidecar_payload), (output, parsed.model_dump(mode="json"))):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(path)
    summary.update({"output": str(output), "sidecar": str(sidecar), "archived_source": str(archived)})
    return summary


def _column_arg(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        role, sep, header = value.partition("=")
        if not sep or not role or not header:
            raise SiteImportError(f"--column expects ROLE=HEADER, got {value!r}")
        mapping[role.strip()] = header
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source_file", type=Path, help="unmodified official site list (csv/tsv/xlsx/json/geojson/kml)")
    parser.add_argument("--source-url", required=True, help="official challenge page or dataset URL (HTTPS)")
    parser.add_argument("--output", type=Path, default=ROOT / "data/catalogue/sites.json")
    parser.add_argument("--sheet", help="worksheet name for multi-sheet XLSX files")
    parser.add_argument("--column", action="append", default=[], metavar="ROLE=HEADER",
                        help="map a role (id, name, latitude, longitude, latitude_type, longitude_direction) to a header")
    parser.add_argument("--longitude-direction", choices=["east_positive", "west_positive"],
                        help="sign convention of plain longitude numbers, as stated by the source documentation")
    parser.add_argument("--latitude-type", choices=["planetocentric", "planetographic"],
                        help="latitude system, as stated by the source documentation")
    parser.add_argument("--dry-run", action="store_true", help="print the interpretation of every row; write nothing")
    args = parser.parse_args()
    try:
        result = import_catalogue(
            args.source_file, args.source_url, args.output, sheet=args.sheet,
            column_overrides=_column_arg(args.column), longitude_direction=args.longitude_direction,
            latitude_type=args.latitude_type, dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, ValidationError) as exc:
        parser.exit(2, f"Import rejected; catalogue was not replaced: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
