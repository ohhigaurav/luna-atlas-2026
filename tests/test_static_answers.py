"""Static answer keys (lunar_core.static_answers) against the vectors the frontend tests too."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from lunar_core.static_answers import fmt, make_key, norm_time

GOLDEN = Path(__file__).resolve().parents[1] / "frontend/app/tests/static_keys.golden.json"


@pytest.mark.parametrize("case", json.loads(GOLDEN.read_text())["cases"], ids=lambda c: c["endpoint"])
def test_golden_keys(case: dict) -> None:
    assert make_key(case["endpoint"], case["body"]) == case["key"]


def test_formatting_rules() -> None:
    assert fmt(2.0) == "2" and fmt(2) == "2" and fmt(2.5) == "2.5" and fmt(0.1) == "0.1"
    assert fmt(True) == "true" and fmt(None) == "null" and fmt("auto") == "auto"
    assert norm_time("2027-01-01T05:30:00+05:30") == "2027-01-01T00:00:00Z"
    with pytest.raises(ValueError):
        norm_time("2027-01-01T00:00:00")
    with pytest.raises(ValueError):
        make_key("analysis", {})
