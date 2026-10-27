from __future__ import annotations

from datetime import UTC, datetime
from math import pi, sin
from pathlib import Path

import pytest
from lunar_core import analysis_service
from lunar_core.api_models import AnalysisRequest, FinderRequest, MissionConstraints
from lunar_core.geometry import ObserverSite, TargetDirection


class SyntheticGeometry:
    """Deterministic test geometry; this is deliberately not real lunar ephemeris."""

    reference_radius_m = 1_737_400.0
    frame = "MOON_ME_TEST_FIXTURE"
    aberration_correction = "SYNTHETIC"
    origin_et = datetime(2027, 1, 1, tzinfo=UTC).timestamp()

    def utc_to_et(self, utc: str) -> float:
        return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()

    def et_to_utc(self, et_s: float) -> str:
        return datetime.fromtimestamp(et_s, tz=UTC).isoformat().replace("+00:00", "Z")

    def direction_at_et(
        self,
        site: ObserverSite,
        et_s: float,
        *,
        target: str,
        observer_height_m: float,
    ) -> TargetDirection:
        phase = 2.0 * pi * (et_s - self.origin_et) / 43_200.0
        elevation = 0.10 * sin(phase) if target == "SUN" else 0.10
        distance = 149_597_870_700.0 if target == "SUN" else 384_400_000.0
        return TargetDirection(
            site_id=site.site_id,
            target=target,  # type: ignore[arg-type]
            utc=self.et_to_utc(et_s),
            ephemeris_time_s=et_s,
            range_m=distance,
            azimuth_deg=(90.0 + (phase * 180.0 / pi)) % 360.0,
            elevation_rad=elevation,
            light_time_s=distance / 299_792_458.0,
            frame=self.frame,
            aberration_correction=self.aberration_correction,
        )


TEST_SITE = {
    "site_id": "synthetic-integration-site",
    "name": "Synthetic Integration Site",
    "origin": "synthetic",
    "catalogue_kind": "test_fixture",
    "latitude_deg": -89.0,
    "longitude_deg": 10.0,
    "latitude_type": "planetocentric",
    "longitude_direction": "east_positive",
    "source_url": "https://example.invalid/test-fixture",
    "source_record": "synthetic test fixture; not a lunar site claim",
}


@pytest.fixture
def synthetic_service_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> SyntheticGeometry:
    geometry = SyntheticGeometry()
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {TEST_SITE["site_id"]: TEST_SITE})
    monkeypatch.setattr(
        analysis_service,
        "_spice_runtime",
        lambda: (object(), geometry, "a" * 64, [{"kernel_id": "synthetic", "path": "not-a-real-kernel", "sha256": "a" * 64}]),
    )
    monkeypatch.setattr(
        analysis_service,
        "assert_required_spk_coverage",
        lambda _spice, _kernels, start, end: {
            "requested_et_s": [start, end], "synthetic_fixture": True,
        },
    )
    monkeypatch.setattr(
        analysis_service,
        "assert_required_bpc_coverage",
        lambda _spice, _kernels, start, end, *, frame: {
            "frame": frame, "requested_et_s": [start, end], "synthetic_fixture": True,
        },
    )
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path / "runs")
    return geometry


def test_analysis_service_runs_full_synthetic_pipeline_and_persists_provenance(
    synthetic_service_environment: SyntheticGeometry,
) -> None:
    request = AnalysisRequest(
        site_ids=[TEST_SITE["site_id"]],
        start_utc="2027-01-01T00:00:00Z",
        end_utc="2027-01-02T00:00:00Z",
        coarse_step_min=30,
        event_tolerance_s=0.1,
        horizon_mode="flat",
    )

    result = analysis_service.run_analysis(request)

    assert result["analysis_kind"] == "spice_backed_analysis"
    assert result["validation_status"] == "computed_not_independently_validated"
    assert result["sites"][0]["site"]["origin"] == "synthetic"
    assert len(result["sites"][0]["series"]) == 49
    assert result["sites"][0]["sun_windows"]
    assert result["provenance"]["spk_coverage_preflight"]["synthetic_fixture"] is True
    assert result["provenance"]["bpc_coverage_preflight"]["frame"] == "MOON_ME_TEST_FIXTURE"
    saved = analysis_service.load_saved_run(result["run_id"])
    assert saved["run_id"] == result["run_id"]
    listed = analysis_service.list_saved_runs()
    assert listed["total"] == 1
    assert listed["runs"][0]["run_id"] == result["run_id"]


def test_finder_service_runs_from_same_pipeline_and_saves_failure_reasons(
    synthetic_service_environment: SyntheticGeometry,
) -> None:
    request = FinderRequest(
        site_ids=[TEST_SITE["site_id"]],
        search_start_utc="2027-01-01T00:00:00Z",
        search_end_utc="2027-01-02T00:00:00Z",
        candidate_step_days=1,
        mission_duration_days=1,
        coarse_step_min=30,
        event_tolerance_s=0.1,
        horizon_mode="flat",
        constraints=MissionConstraints(
            max_darkness_h=1.0,
            max_dte_gap_h=0.5,
            max_joint_outage_h=0.5,
            min_sunlit_fraction=0.9,
        ),
    )

    result = analysis_service.run_finder(request)

    assert result["analysis_kind"] == "landing_window_finder"
    assert len(result["grid"]) == 2
    assert all(cell["feasible"] is False for cell in result["grid"])
    assert all(cell["first_failed_constraint"] for cell in result["grid"])
    assert all(cell["failures"] for cell in result["grid"])
    assert analysis_service.load_saved_run(result["run_id"])["grid"] == result["grid"]


class RatedSyntheticGeometry(SyntheticGeometry):
    """Same synthetic motion, but also returns analytic angular rates like SPICE azlcpo."""

    def direction_at_et(self, site, et_s, *, target, observer_height_m):  # type: ignore[no-untyped-def]
        from dataclasses import replace
        from math import cos

        base = super().direction_at_et(site, et_s, target=target, observer_height_m=observer_height_m)
        omega = 2.0 * pi / 43_200.0
        phase = omega * (et_s - self.origin_et)
        el_rate = 0.10 * omega * cos(phase) if target == "SUN" else 0.0
        return replace(base, azimuth_rate_rad_s=omega, elevation_rate_rad_s=el_rate)


def test_analysis_reports_certified_discovery_when_geometry_supplies_rates(
    synthetic_service_environment: SyntheticGeometry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry = RatedSyntheticGeometry()
    monkeypatch.setattr(
        analysis_service, "_spice_runtime",
        lambda: (object(), geometry, "a" * 64, [{"kernel_id": "synthetic", "path": "x", "sha256": "a" * 64}]),
    )
    request = AnalysisRequest(
        site_ids=[TEST_SITE["site_id"]], start_utc="2027-01-01T00:00:00Z",
        end_utc="2027-01-02T00:00:00Z", coarse_step_min=30, event_tolerance_s=0.1,
        horizon_mode="flat",
    )
    result = analysis_service.run_analysis(request)
    precision = result["sites"][0]["event_precision"]
    assert precision["discovery_certified"] is True
    assert precision["sun_possible_grazing"] == []
    # Synthetic 12 h "day" over 24 h: visible at the start, one full window, visible at the end.
    windows = result["sites"][0]["sun_windows"]
    assert len(windows) == 3
    assert windows[0]["start_truncated"] and windows[-1]["end_truncated"]
    assert not windows[1]["start_truncated"] and not windows[1]["end_truncated"]
    assert windows[1]["duration_s"] > 20_000


def test_analysis_without_rates_is_explicitly_not_certified(
    synthetic_service_environment: SyntheticGeometry,
) -> None:
    request = AnalysisRequest(
        site_ids=[TEST_SITE["site_id"]], start_utc="2027-01-01T00:00:00Z",
        end_utc="2027-01-02T00:00:00Z", coarse_step_min=30, event_tolerance_s=0.1,
        horizon_mode="flat",
    )
    precision = analysis_service.run_analysis(request)["sites"][0]["event_precision"]
    assert precision["discovery_certified"] is False
    assert "Not certified" in precision["claim"]
