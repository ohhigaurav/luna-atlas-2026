#!/usr/bin/env python3
"""Import a source-provided official challenge site CSV into the validated catalogue.

Expected CSV headers:
  source_site_id,name,latitude_deg,longitude_deg,latitude_type,longitude_direction

Longitude sign conventions are explicit per row. West-positive inputs are converted to canonical
east-positive [0, 360) degrees, while the original row is retained verbatim in source_record and
the original file SHA-256 is recorded. The source CSV itself is never modified.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
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

REQUIRED = {
    "source_site_id", "name", "latitude_deg", "longitude_deg",
    "latitude_type", "longitude_direction",
}


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not result:
        raise ValueError("source_site_id/name must contain at least one ASCII letter or digit")
    return result[:80]


def import_catalogue(source: Path, source_url: str, output: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    parsed_source = urlparse(source_url)
    host = (parsed_source.hostname or "").lower().rstrip(".")
    official_host = (
        host == "spaceappschallenge.org"
        or host.endswith(".spaceappschallenge.org")
        or host == "nasa.gov"
        or host.endswith(".nasa.gov")
    )
    if parsed_source.scheme != "https" or not official_host:
        raise ValueError(
            "--source-url must be HTTPS on spaceappschallenge.org or a NASA-owned .nasa.gov host; "
            "unofficial research references belong in data/reference, never the official catalogue"
        )
    source_hash = sha256_file(source)
    retrieved = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    sites: list[dict[str, Any]] = []
    seen: set[str] = set()
    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = set(reader.fieldnames or [])
        missing = REQUIRED - headers
        if missing:
            raise ValueError(f"CSV missing required headers: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            if not any((value or "").strip() for value in row.values()):
                continue
            original_id = (row.get("source_site_id") or "").strip()
            name = (row.get("name") or "").strip()
            if not original_id or not name:
                raise ValueError(f"line {line_number}: source_site_id and name are required")
            slug = _slug(original_id)
            site_id = f"official-{slug}"
            if site_id in seen:
                raise ValueError(f"line {line_number}: duplicate normalised site ID {site_id}")
            seen.add(site_id)
            try:
                latitude = float((row.get("latitude_deg") or "").strip())
                longitude = float((row.get("longitude_deg") or "").strip())
            except ValueError as exc:
                raise ValueError(f"line {line_number}: coordinates must be numeric and non-empty") from exc
            if not (-90.0 <= latitude <= 90.0):
                raise ValueError(f"line {line_number}: latitude must lie in [-90, 90] degrees")
            if not (-360.0 <= longitude <= 360.0):
                raise ValueError(f"line {line_number}: longitude source value must lie in [-360, 360] degrees")
            lat_type = (row.get("latitude_type") or "").strip()
            source_direction = (row.get("longitude_direction") or "").strip()
            if source_direction == "east_positive":
                longitude_canonical = longitude % 360.0
            elif source_direction == "west_positive":
                longitude_canonical = (-longitude) % 360.0
            else:
                raise ValueError(
                    f"line {line_number}: longitude_direction must be exactly east_positive or west_positive"
                )
            source_record = json.dumps({
                "source_csv_sha256": source_hash,
                "source_line_number": line_number,
                "source_row": row,
            }, sort_keys=True, ensure_ascii=False)
            sites.append({
                "site_id": site_id,
                "name": name,
                "origin": "official",
                "latitude_deg": latitude,
                "longitude_deg": longitude_canonical,
                "latitude_type": lat_type,
                "longitude_direction": "east_positive",
                "source_url": source_url,
                "source_record": source_record,
                "retrieved_utc": retrieved,
                "terrain_status": "none",
                "dem_assets": [],
            })
    if not sites:
        raise ValueError("source CSV contains no site rows")
    catalogue = {
        "schema_version": "1.0",
        "catalogue_state": "loaded",
        "source_url": source_url,
        "retrieved_utc": retrieved,
        "sites": sites,
    }
    # Validate exactly the schema used by the runtime before writing a replacement file.
    parsed = SiteCatalogue.model_validate(catalogue)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(parsed.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(output)
    return {
        "catalogue_state": parsed.catalogue_state,
        "site_count": len(parsed.sites),
        "source_csv_sha256": source_hash,
        "retrieved_utc": retrieved,
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="unmodified official site CSV from challenge data")
    parser.add_argument("--source-url", required=True, help="official challenge page or dataset URL (HTTPS)")
    parser.add_argument("--output", type=Path, default=ROOT / "data/catalogue/sites.json")
    args = parser.parse_args()
    try:
        print(json.dumps(import_catalogue(args.csv_file, args.source_url, args.output), indent=2))
    except (OSError, ValueError, ValidationError) as exc:
        parser.exit(2, f"Import rejected; catalogue was not replaced: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
