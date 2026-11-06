"""Keys for pre-computed API answers, so the static judge site answers like the live server.

Judging runs for weeks after 15 Nov and nobody's laptop stays on, so the judged site is static
(docs/static_bundle.md). ``tools/bake_answers.py`` calls the real endpoints and saves each
response unmodified. In static mode the frontend's ``post()`` builds the same key from its
request body and reads the saved answer (``frontend/app/src/data/staticAnswers.ts``, an exact
mirror of ``make_key``). Shared test vectors: ``frontend/app/tests/static_keys.golden.json``.

Key = "<endpoint>?<field>=<value>&...", with fields in the fixed order of ``KEY_SPEC`` and
missing fields replaced by the server's defaults (listed here, published in the answers index):
  * place: ``site_id``, or ``point:<lat %.4f>,<lon in [0,360) %.4f>`` for a clicked point;
  * times: ``YYYY-MM-DDTHH:MM:SSZ``;
  * numbers: integer-valued as integers ("2", not "2.0"); otherwise the shortest round-trip form
    (Python ``repr``, JavaScript ``String``; they agree for these values);
  * ``true`` / ``false`` / ``null``; strings verbatim.
``/api/compare`` is stored per single place; the frontend asks each place and merges the rows.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

KEY_SPEC: dict[str, list[tuple[str, Any]]] = {
    "landing-windows": [("place", None), ("search_start_utc", None), ("search_days", 90), ("mission_days", 10),
                        ("panel_height_m", 2), ("require_earth_at_landing", True), ("max_sun_elevation_deg", 20),
                        ("min_sun_elevation_deg", "auto")],
    "check": [("place", None), ("start_utc", None), ("days", 30), ("panel_height_m", 2)],
    "compare": [("place", None), ("at_utc", None), ("days", 30), ("panel_height_m", 2)],
    "landing-ellipse": [("site_id", None), ("start_utc", None), ("days", 14), ("semi_major_m", 250),
                        ("semi_minor_m", None), ("orientation_deg", 0), ("spacing_m", None), ("panel_height_m", 2)],
}
TIME_FIELDS = {"search_start_utc", "start_utc", "at_utc"}


def norm_time(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"time without timezone: {value}")
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("non-finite number in a key")
        return str(int(f)) if f.is_integer() else repr(f)
    return str(value)


def place_of(body: dict[str, Any]) -> str:
    if body.get("site_id") is not None:
        return str(body["site_id"])
    lat, lon = float(body["latitude_deg"]), float(body["longitude_deg"]) % 360.0
    return f"point:{lat:.4f},{lon:.4f}"


def make_key(endpoint: str, body: dict[str, Any]) -> str:
    if endpoint not in KEY_SPEC:
        raise ValueError(f"no static answers for {endpoint}")
    parts = []
    for name, default in KEY_SPEC[endpoint]:
        value = place_of(body) if name == "place" else body.get(name, default)
        if name in TIME_FIELDS:
            value = norm_time(value)
        parts.append(f"{name}={fmt(value)}")
    return f"{endpoint}?" + "&".join(parts)


__all__ = ["KEY_SPEC", "fmt", "make_key", "norm_time", "place_of"]
