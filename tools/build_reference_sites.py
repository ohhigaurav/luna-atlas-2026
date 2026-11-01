#!/usr/bin/env python3
"""Merge the stand-in landing-site list into data/reference/reference_sites.json.

Until the official challenge site list exists (Resources tab, 13 Nov 2026), the curated list the
challenge statement describes (Apollo, CLPS targets, other commercial and national missions) is
approximated by ``data/reference/landing_sites_standin.csv``: one published source per row,
coordinates written in the source's own notation. The CSV goes through the same parser as the
official importer (``lunar_core.site_import``), so this also exercises that code on real rows.

These are reference sites, never official ones: they are written to the reference catalogue
with ``kind = mission_landing_site`` and the official catalogue is not touched. Existing
literature reference points are kept unchanged; rows previously produced by this tool are
replaced. Use --check to verify the JSON is up to date without writing.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.provenance import sha256_file  # noqa: E402
from lunar_core.references import ReferenceCatalogue  # noqa: E402
from lunar_core.site_import import SiteImportError, parse_site_file  # noqa: E402

DEFAULT_CSV = ROOT / "data/reference/landing_sites_standin.csv"
DEFAULT_JSON = ROOT / "data/reference/reference_sites.json"
REQUIRED_EXTRA = ("group", "position_kind", "source_url", "source_note")
NOTE = (
    "Exploratory reference sites, not the official NASA Space Apps 2026 candidate-site catalogue. "
    "Two kinds: south-polar literature reference points, and published mission landing sites "
    "(Apollo, CLPS, other national programmes) built by tools/build_reference_sites.py from "
    "data/reference/landing_sites_standin.csv with one cited source per coordinate. A "
    "'target_region_centre' position is the centre of a named feature, not a landing point."
)


def build(csv_path: Path, json_path: Path) -> dict[str, Any]:
    report = parse_site_file(csv_path)
    with csv_path.open(encoding="utf-8", newline="") as stream:
        headers = next(csv.reader(stream))
    missing = [h for h in REQUIRED_EXTRA if h not in headers]
    if missing:
        raise SiteImportError(f"stand-in CSV lacks columns {missing}")
    csv_hash = sha256_file(csv_path)
    existing = json.loads(json_path.read_text(encoding="utf-8"))
    kept = [s for s in existing["sites"] if s.get("kind") != "mission_landing_site"]
    kept_ids = {s["site_id"] for s in kept}
    new_sites: list[dict[str, Any]] = []
    for site in report.sites:
        raw = site.raw
        site_id = f"reference-{site.source_id}"
        if site_id in kept_ids:
            raise SiteImportError(f"{site.locator}: {site_id} collides with a literature reference point")
        source_record = (
            f"{raw['source_note']} | stand-in CSV row {site.locator}, sha256 {csv_hash[:16]}; "
            f"source values lat={raw['latitude']!r} lon={raw['longitude']!r}; {site.longitude_rule}."
        )
        new_sites.append({
            "site_id": site_id,
            "name": site.name,
            "latitude_deg": site.latitude_deg,
            "longitude_deg": round(site.longitude_east_deg, 10),
            "latitude_type": site.latitude_type,
            "longitude_direction": "east_positive",
            "source_url": raw["source_url"],
            "source_record": source_record,
            "terrain_status": "none",
            "kind": "mission_landing_site",
            "group": raw["group"],
            "position_kind": raw["position_kind"],
        })
    catalogue = {
        "schema_version": existing["schema_version"],
        "catalogue_kind": existing["catalogue_kind"],
        "note": NOTE,
        "sites": kept + new_sites,
    }
    ReferenceCatalogue.model_validate(catalogue)
    return catalogue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--check", action="store_true", help="fail if the JSON differs from a fresh build")
    args = parser.parse_args()
    try:
        catalogue = build(args.csv, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Reference build rejected; nothing written: {exc}\n")
    text = json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != text:
            parser.exit(1, "reference_sites.json is out of date; run tools/build_reference_sites.py\n")
        print("reference_sites.json is up to date")
        return 0
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(args.output)
    kinds: dict[str, int] = {}
    for site in catalogue["sites"]:
        kinds[site["kind"]] = kinds.get(site["kind"], 0) + 1
    print(json.dumps({"output": str(args.output), "site_counts": kinds}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
