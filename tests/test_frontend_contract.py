from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_literal_frontend_id_exists_in_html_or_is_explicitly_dynamic() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'\bid="([^"]+)"', html))
    js_ids = set(re.findall(r"\$\('([^']+)'\)", js))
    # This control is injected only when a finder cell is expanded.
    dynamically_created_ids = {"inspectFinderCell"}
    assert js_ids - html_ids == dynamically_created_ids


def test_frontend_uses_only_local_runtime_assets() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "app.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'href="/static/app.css"' in html
    assert 'src="/static/app.js"' in html
    assert not re.search(r"https?://", html, flags=re.IGNORECASE)
    assert not re.search(r"@import\s+url\(|url\(['\"]?https?://", css, flags=re.IGNORECASE)
    assert not re.search(r"<script[^>]+src=['\"]https?://", html, flags=re.IGNORECASE)
    assert "SIMULATED INTERFACE DATA ONLY" in js
    assert "Preview exports are disabled" in js


def test_finder_form_uses_api_contract_field_ids() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    for element_id in ("maxDarkness", "maxEarthGap", "maxJointGap", "minSunlit"):
        assert f'id="{element_id}"' in html
    assert "max_dte_gap_h: Number($('maxEarthGap').value)" in js


def test_datetime_local_values_are_converted_to_utc_not_mislabeled_with_z() -> None:
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "new Date(value)" in js
    assert "instant.toISOString()" in js
    assert "utcToLocalInput('2027-01-01T00:00:00Z')" in js
    assert "LOCAL DISPLAY" in html
    assert "LOCAL DISPLAY → UTC API" in html
    assert "return `${value}:00Z`" not in js


def test_finder_interval_navigation_converts_utc_instants_to_local_input() -> None:
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "$('analysisStart').value = utcToLocalInput(cell.start_utc)" in js
    assert "$('analysisEnd').value = utcToLocalInput(cell.end_utc)" in js
    assert "date.toISOString().slice(0, 16)" not in js


def test_assumptions_view_has_live_dem_inventory_and_non_claims() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="terrainInventorySummary"' in html
    assert 'id="terrainInventory"' in html
    assert 'id="terrainInventoryStatus"' in html
    assert "fetchJSON('/api/terrain-coverage')" in js
    assert "vertical datum" in js.lower()
    assert "provisional" in js.lower()
    assert "renderTerrainInventory();" in js


def test_compare_opens_with_labelled_ux_preview_populated() -> None:
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    init_start = js.index("async function init()")
    init_end = js.index("document.addEventListener('DOMContentLoaded', init)", init_start)
    init_body = js[init_start:init_end]
    assert "loadPreview();" in init_body
    assert "SIMULATED INTERFACE DATA ONLY" in js
    assert "Preview exports are disabled" in js
