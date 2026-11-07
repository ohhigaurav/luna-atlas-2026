"""Gate S tool: comparison arithmetic, verdict, report, and refusal on missing inputs (no rasters)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import validate_slope as vs  # noqa: E402

CRIT = json.loads((ROOT / "validation" / "slope_tolerances.json").read_text())["criteria"]


def test_pass_rule_is_predeclared_and_complete() -> None:
    tol = json.loads((ROOT / "validation" / "slope_tolerances.json").read_text())
    assert tol["predeclared_utc"] == "2026-11-07T14:12:20Z"
    assert set(CRIT) == {"S1_same_grid", "S2_coverage_min_share", "S3_abs_median_difference_max_deg",
                         "S4_p95_abs_difference_max_deg", "S5_limit_disagreement_max_share", "S5_limit_deg"}
    assert tol["method_under_test"]["fixed_before_run"] is True


def test_identical_maps_pass_every_check() -> None:
    rng = np.random.default_rng(1)
    pub = rng.uniform(0, 20, (50, 50))
    r = vs.compare(pub.copy(), pub, np.ones((50, 50), bool), CRIT)
    assert r["checks"] == {"S2": True, "S3": True, "S4": True, "S5": True}
    assert r["difference_deg"]["max_abs"] == 0.0


def test_bias_scatter_coverage_and_limit_flips_are_caught() -> None:
    rng = np.random.default_rng(2)
    pub = rng.uniform(0, 20, (100, 100))
    dom = np.ones_like(pub, bool)
    assert vs.compare(pub + 0.3, pub, dom, CRIT)["checks"]["S3"] is False           # bias 0.3 > 0.25
    noisy = vs.compare(pub + rng.normal(0, 1.5, pub.shape), pub, dom, CRIT)
    assert noisy["checks"]["S4"] is False                                           # p95 ~2.9 > 1.5
    holes = pub.copy()
    holes[:2, :] = np.nan                                                           # 2 % unknown
    assert vs.compare(holes, pub, dom, CRIT)["checks"]["S2"] is False
    flipped = np.where(np.abs(pub - 8) < 1.0, 16 - pub, pub)                         # ~10 % cross the limit
    assert vs.compare(flipped, pub, dom, CRIT)["checks"]["S5"] is False
    empty = vs.compare(pub, pub, np.zeros_like(dom), CRIT)
    assert empty["compared_pixels"] == 0 and not any(empty["checks"].values())


def test_verdict_needs_both_sites_and_the_same_grid() -> None:
    ok = {"S1_same_grid": True, "primary": {"checks": {"S2": True, "S3": True, "S4": True, "S5": True}}}
    assert vs.verdict({"a": ok, "b": ok}) == "PASS"
    assert vs.verdict({"a": ok, "b": {**ok, "S1_same_grid": False}}) == "FAIL"
    assert vs.verdict({"a": ok, "b": {**ok, "primary": {"checks": {"S2": True, "S3": True, "S4": False, "S5": True}}}}) == "FAIL"
    assert vs.verdict({}) == "FAIL"


def test_report_states_fail_consequence() -> None:
    pub = np.full((10, 10), 5.0)
    prim = vs.compare(pub + 2.0, pub, np.ones((10, 10), bool), CRIT)
    ev = {"verdict": "FAIL", "run_utc": "2026-11-08T00:00:00Z", "git": {"commit": "abc", "dirty": False},
          "tolerances": {"path": "validation/slope_tolerances.json", "sha256": "0" * 64, "predeclared_utc": "x",
                         "status_at_run": "proposed_before_run", "criteria": CRIT},
          "sites": {"pgda78-site01-surface": {"site_id": "reference-lola-site-001", "S1_same_grid": True, "primary": prim}}}
    text = vs.report(ev)
    assert "— FAIL" in text and "S3:FAIL" in text and "SLOPE_SOURCE = 'published'" in text


def test_run_refuses_without_inputs_and_writes_no_evidence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from lunar_core import slope
    if all(slope.companion(a, "slope_deg", ROOT, slope.load_layers()) for a in vs.SITES):
        pytest.skip("published slope layers are staged here; this test is for machines without them")
    assert vs.run(tmp_path) == 2
    assert list(tmp_path.iterdir()) == []
    assert "missing" in capsys.readouterr().out
