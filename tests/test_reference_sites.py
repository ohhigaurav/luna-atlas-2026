"""The stand-in landing-site list stays reproducible, cited and separate from official sites."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
from build_reference_sites import DEFAULT_CSV, DEFAULT_JSON, build  # noqa: E402
from lunar_core.references import load_reference_catalogue  # noqa: E402


def test_committed_reference_json_matches_fresh_build() -> None:
    fresh = json.dumps(build(DEFAULT_CSV, DEFAULT_JSON), indent=2, ensure_ascii=False) + "\n"
    assert DEFAULT_JSON.read_text(encoding="utf-8") == fresh, "run tools/build_reference_sites.py"


def test_mission_sites_are_cited_and_cover_the_statement_groups() -> None:
    catalogue = load_reference_catalogue()
    missions = [s for s in catalogue.sites if s.kind == "mission_landing_site"]
    assert all(s.source_url.startswith("https://") for s in missions)
    assert all(s.group and s.position_kind for s in missions)
    groups = {s.group for s in missions}
    # Challenge statement: past Apollo missions, CLPS targets, other countries' programmes.
    assert {"Apollo", "CLPS (flown)", "CLPS (future target)"} <= groups
    assert len(groups - {"Apollo", "CLPS (flown)", "CLPS (future target)"}) >= 3
    # The point of the stand-in list: sites outside the south-polar DEM coverage.
    assert any(s.latitude_deg > -60 for s in missions)
    assert any(90 < s.longitude_deg < 270 for s in missions)  # far side


def test_known_values_survive_the_parser() -> None:
    sites = {s.site_id: s for s in load_reference_catalogue().sites}
    # West-of-meridian Apollo 12, signed east-positive in the source.
    assert sites["reference-apollo-12"].longitude_deg == 336.5781
    # Hemisphere-letter rows.
    assert sites["reference-clps-im-1"].latitude_deg == -80.13
    assert sites["reference-intl-change-4"].longitude_deg == 177.5885
    # Planetographic gazetteer value kept as stated (identical on the spherical Moon).
    assert sites["reference-clps-im-3-target"].latitude_type == "planetographic"
    assert sites["reference-clps-im-3-target"].position_kind == "target_region_centre"


def test_reference_sites_never_enter_the_official_catalogue() -> None:
    official = json.loads((ROOT / "data/catalogue/sites.json").read_text(encoding="utf-8"))
    assert official["catalogue_state"] == "awaiting_official_source"
    assert official["sites"] == []
