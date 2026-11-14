"""One list of every site the app shows: official challenge sites first, then reference points.

The challenge's Resources (13 Nov 2026) contain no site list, so the official catalogue is empty
and the app shows reference points only. If a list is ever imported with
``tools/import_official_sites.py`` (writes ``data/catalogue/sites.json``), the official sites
appear without any frontend change beyond reading this list. Each entry
keeps its own origin, so the app can say "Official challenge site" or "Reference point, not
official", and so official and reference records can never be confused.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SITE_NOTES = Path(__file__).resolve().parents[2] / "data" / "reference" / "site_notes.json"
OFFICIAL_GROUP = "Official challenge sites"
OFFICIAL_KIND = "official_challenge_site"


def load_site_notes(path: Path = SITE_NOTES) -> dict[str, dict[str, Any]]:
    """Our analysis notes per site ID (data/reference/site_notes.json), kept apart from the citations."""
    if not path.is_file():
        return {}
    notes: dict[str, dict[str, Any]] = json.loads(path.read_text(encoding="utf-8")).get("notes", {})
    for site_id, note in notes.items():
        if not note.get("text") or not note.get("evidence"):
            raise ValueError(f"site note for {site_id} needs text and evidence")
    return notes


def build_site_index(official: Any, reference: Any, notes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``official``: SiteCatalogue; ``reference``: ReferenceSiteCatalogue (pydantic models).

    ``notes`` (from ``load_site_notes``) attach as ``analysis_note`` to the matching site; a note
    for an unknown site ID is an error, so stale notes cannot linger silently.
    """
    notes = notes or {}
    sites: list[dict[str, Any]] = []
    unplaced: list[dict[str, str]] = []
    seen: set[str] = set()
    for site in official.sites:
        record = site.model_dump(mode="json")
        if record.get("latitude_deg") is None or record.get("longitude_deg") is None:
            unplaced.append({"site_id": record["site_id"], "name": record["name"],
                             "reason": "no coordinates in the official source"})
            continue
        record["longitude_deg"] = float(record["longitude_deg"]) % 360.0
        record.update({"origin": "official", "kind": OFFICIAL_KIND, "group": OFFICIAL_GROUP,
                       "catalogue_kind": "official_challenge"})
        sites.append(record)
        seen.add(record["site_id"])
    for site in reference.sites:
        record = site.model_dump(mode="json")
        if record["site_id"] in seen:
            raise ValueError(f"site ID {record['site_id']} is in both the official and the reference catalogue")
        record.update({"origin": "reference", "catalogue_kind": "literature_reference_points"})
        sites.append(record)
    by_id = {s["site_id"]: s for s in sites}
    for site_id, note in notes.items():
        if site_id not in by_id:
            raise ValueError(f"site note for unknown site ID {site_id}")
        by_id[site_id]["analysis_note"] = note
    return {
        "schema_version": "1.0",
        "official_state": official.catalogue_state,
        "official_count": sum(1 for s in sites if s["origin"] == "official"),
        "official_source_url": official.source_url,
        "official_retrieved_utc": official.retrieved_utc.isoformat() if getattr(official, "retrieved_utc", None) else None,
        "reference_count": sum(1 for s in sites if s["origin"] == "reference"),
        "unplaced_official": unplaced,
        "sites": sites,
        "note": ("Official challenge sites, if any, come first. Reference points are published landmarks and "
                 "missions, each with its source; the challenge published no site list (Resources, 13 Nov 2026)."),
    }
