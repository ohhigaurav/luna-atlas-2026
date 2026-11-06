"""One list of every site the app shows: official challenge sites first, then reference points.

Until 13 Nov the official catalogue is empty and the app shows reference points only. After
``tools/import_official_sites.py`` writes ``data/catalogue/sites.json``, the official sites must
appear without any frontend change beyond reading this list (an internal document (not published)). Each entry
keeps its own origin, so the app can say "Official challenge site" or "Reference point, not
official", and so official and reference records can never be confused.
"""
from __future__ import annotations

from typing import Any

OFFICIAL_GROUP = "Official challenge sites"
OFFICIAL_KIND = "official_challenge_site"


def build_site_index(official: Any, reference: Any) -> dict[str, Any]:
    """``official``: SiteCatalogue; ``reference``: ReferenceSiteCatalogue (pydantic models)."""
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
    return {
        "schema_version": "1.0",
        "official_state": official.catalogue_state,
        "official_count": sum(1 for s in sites if s["origin"] == "official"),
        "official_source_url": official.source_url,
        "official_retrieved_utc": official.retrieved_utc.isoformat() if getattr(official, "retrieved_utc", None) else None,
        "reference_count": sum(1 for s in sites if s["origin"] == "reference"),
        "unplaced_official": unplaced,
        "sites": sites,
        "note": ("Official challenge sites come first; reference points are published landmarks and missions, "
                 "not official challenge coordinates."),
    }
