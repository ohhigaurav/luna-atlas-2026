"""Sky-geometry endpoint: conventions, maths and locking, with a fake SPICE (no kernels needed).

Real-kernel checks against JPL Horizons are in tools/check_sky_geometry.py and run on a machine
with the verified kernel set.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest
from lunar_core import analysis_service
from lunar_core.analysis_service import AnalysisNotReady
from lunar_core.api_models import SkyGeometryRequest, SkyGeometryResponse
from lunar_core.sky_geometry import compute_sky_geometry, sub_point
from pydantic import ValidationError

AU_KM = 149_597_870.7
SYNODIC_S = 29.530588 * 86_400.0


class FakeSpice:
    """Sun circles the Moon's equator once per synodic month; Earth sits near +X."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def spkpos(self, target: str, et: float, frame: str, abcorr: str, observer: str) -> tuple[list[float], float]:
        self.calls.append(("spkpos", target, frame, abcorr, observer))
        if target == "SUN":
            angle = 2.0 * math.pi * et / SYNODIC_S
            return [AU_KM * math.cos(angle), AU_KM * math.sin(angle), AU_KM * 0.02], AU_KM / 299_792.458
        if target == "EARTH":
            return [384_400.0, -1_000.0, 2_000.0], 1.28
        raise AssertionError(target)

    def phaseq(self, et: float, target: str, illmn: str, obsrvr: str, abcorr: str) -> float:
        self.calls.append(("phaseq", target, illmn, obsrvr, abcorr))
        return (2.0 * math.pi * et / SYNODIC_S) % (2.0 * math.pi)


class FakeGeometry:
    frame = "MOON_ME"
    aberration_correction = "LT+S"
    reference_radius_m = 1_737_400.0

    def utc_to_et(self, utc: str) -> float:
        return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()

    def et_to_utc(self, et_s: float) -> str:
        return datetime.fromtimestamp(et_s, tz=UTC).isoformat().replace("+00:00", "Z")


def _request(**overrides: Any) -> SkyGeometryRequest:
    values: dict[str, Any] = {"start_utc": "2027-01-01T00:00:00Z", "end_utc": "2027-01-02T00:00:00Z", "step_min": 60}
    values.update(overrides)
    return SkyGeometryRequest(**values)


# --- sub-point maths -------------------------------------------------------------------------

def test_sub_point_axes_and_east_longitude() -> None:
    assert sub_point([10.0, 0.0, 0.0])[1:] == (10.0, 0.0, 0.0)
    _unit, _d, lat, lon = sub_point([0.0, -5.0, 0.0])
    assert lat == 0.0 and lon == pytest.approx(270.0)
    unit, distance, lat, _lon = sub_point([0.0, 0.0, -2.0])
    assert unit == [0.0, 0.0, -1.0] and distance == 2.0 and lat == -90.0


def test_sub_point_never_returns_360() -> None:
    _unit, _d, _lat, lon = sub_point([1.0, -1e-15, 0.0])
    assert 0.0 <= lon < 360.0
    assert round(lon, 6) != 360.0


@pytest.mark.parametrize("vector", [[0.0, 0.0, 0.0], [math.nan, 1.0, 0.0]])
def test_sub_point_rejects_degenerate_vectors(vector: list[float]) -> None:
    with pytest.raises(ValueError):
        sub_point(vector)


# --- series --------------------------------------------------------------------------------

def test_series_uses_run_frame_correction_and_moon_observer() -> None:
    spice = FakeSpice()
    compute_sky_geometry(spice, [0.0, 3600.0], frame="MOON_ME", aberration_correction="LT+S", et_to_utc=str)
    spk = [call for call in spice.calls if call[0] == "spkpos"]
    assert {call[1] for call in spk} == {"SUN", "EARTH"}
    assert all(call[2:] == ("MOON_ME", "LT+S", "MOON") for call in spk)
    assert all(call[1:] == ("EARTH", "SUN", "MOON", "LT+S") for call in spice.calls if call[0] == "phaseq")


def test_series_values() -> None:
    quarter = SYNODIC_S / 4.0
    series = compute_sky_geometry(
        FakeSpice(), [0.0, quarter, 2 * quarter], frame="MOON_ME", aberration_correction="LT+S", et_to_utc=str,
    )
    sun, earth = series["sun"], series["earth"]
    assert len(series["utc"]) == len(sun["unit"]) == len(earth["illuminated_fraction"]) == 3
    for vector in sun["unit"] + earth["unit"]:
        assert math.fsum(component * component for component in vector) == pytest.approx(1.0, abs=1e-6)
    assert sun["sub_lon_east_deg"] == pytest.approx([0.0, 90.0, 180.0], abs=1e-6)
    assert sun["sub_lat_deg"][0] == pytest.approx(math.degrees(math.atan(0.02)), abs=1e-6)
    # Phase 0 -> full Earth, 90 deg -> half, 180 deg -> new.
    assert earth["illuminated_fraction"] == pytest.approx([1.0, 0.5, 0.0], abs=1e-6)
    assert earth["phase_angle_deg"] == pytest.approx([0.0, 90.0, 180.0], abs=1e-6)
    # Sun ~0.2666 deg semidiameter at 1 AU (x1.0002 for the 0.02 z offset); Earth ~0.95 deg at 384,400 km.
    assert sun["angular_radius_deg"][0] == pytest.approx(0.2665, abs=2e-4)
    assert earth["angular_radius_deg"][0] == pytest.approx(0.9507, abs=2e-4)
    assert earth["sub_lon_east_deg"][0] > 359.0  # small negative y -> just west of 0, as east longitude


def test_series_rejects_empty_grid_and_bad_phase() -> None:
    with pytest.raises(ValueError):
        compute_sky_geometry(FakeSpice(), [], frame="MOON_ME", aberration_correction="LT+S", et_to_utc=str)

    class NanPhase(FakeSpice):
        def phaseq(self, *args: Any) -> float:
            return math.nan

    with pytest.raises(ValueError, match="phase"):
        compute_sky_geometry(NanPhase(), [0.0], frame="MOON_ME", aberration_correction="LT+S", et_to_utc=str)


# --- request contract ----------------------------------------------------------------------

def test_request_defaults_and_limits() -> None:
    assert _request(step_min=30).step_min == 30
    with pytest.raises(ValidationError, match="400 days"):
        _request(end_utc="2028-03-01T00:00:00Z", step_min=1440)
    with pytest.raises(ValidationError, match="18000 samples"):
        _request(end_utc="2027-01-14T00:00:00Z", step_min=1)
    with pytest.raises(ValidationError, match="after start"):
        _request(end_utc="2027-01-01T00:00:00Z")
    with pytest.raises(ValidationError, match="timezone"):
        _request(start_utc="2027-01-01T00:00:00")
    with pytest.raises(ValidationError):
        _request(step_min=0)
    with pytest.raises(ValidationError):
        _request(site_ids=["x"])


# --- service: kernels and locking ----------------------------------------------------------

@pytest.fixture
def fake_runtime(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    reuse_flags: list[bool] = []

    def runtime(*, reuse_loaded: bool = False) -> tuple[Any, ...]:
        reuse_flags.append(reuse_loaded)
        kernels = [{"kernel_id": "de421", "path": "x", "sha256": "b" * 64}]
        return FakeSpice(), FakeGeometry(), "a" * 64, kernels

    monkeypatch.setattr(analysis_service, "_spice_runtime", runtime)
    monkeypatch.setattr(
        analysis_service, "coverage_preflight",
        lambda _spice, _kernels, start, end, frame: ({"start_et": start, "end_et": end}, {"frame": frame}),
    )
    return reuse_flags


def test_service_payload_matches_response_model(fake_runtime: list[bool]) -> None:
    payload = analysis_service.run_sky_geometry(_request())
    model = SkyGeometryResponse.model_validate(payload)
    assert model.settings.sample_count == 25
    assert model.series.utc[0] == "2027-01-01T00:00:00Z" and model.series.utc[-1] == "2027-01-02T00:00:00Z"
    assert model.frame == "MOON_ME" and model.aberration_correction == "LT+S"
    assert model.provenance.kernel_pool == "preflighted"
    assert model.provenance.loaded_kernel_ids == ["de421"]
    assert fake_runtime == [False]
    assert not analysis_service._RUN_LOCK.locked()


def test_service_includes_end_epoch_when_step_does_not_divide(fake_runtime: list[bool]) -> None:
    payload = analysis_service.run_sky_geometry(_request(end_utc="2027-01-01T01:45:00Z", step_min=60))
    assert payload["series"]["utc"] == ["2027-01-01T00:00:00Z", "2027-01-01T01:00:00Z", "2027-01-01T01:45:00Z"]


def test_service_reuses_loaded_pool_while_a_run_is_active(
    fake_runtime: list[bool], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", (("m", ()), object()))
    with analysis_service._RUN_LOCK:
        payload = analysis_service.run_sky_geometry(_request())
    assert payload["provenance"]["kernel_pool"] == "reused_from_active_run"
    assert fake_runtime == [True]


def test_service_waits_then_fails_closed_while_a_run_is_still_loading(
    fake_runtime: list[bool], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", None)
    monkeypatch.setattr(analysis_service, "SKY_LOCK_WAIT_S", 0.05)
    with analysis_service._RUN_LOCK, pytest.raises(AnalysisNotReady, match="still loading"):
        analysis_service.run_sky_geometry(_request())
    assert fake_runtime == []


def test_service_releases_lock_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*, reuse_loaded: bool = False) -> tuple[Any, ...]:
        raise AnalysisNotReady("no kernels")

    monkeypatch.setattr(analysis_service, "_spice_runtime", broken)
    with pytest.raises(AnalysisNotReady):
        analysis_service.run_sky_geometry(_request())
    assert not analysis_service._RUN_LOCK.locked()


# --- HTTP layer (needs FastAPI; runs on the project environment) -----------------------------

def test_http_contract(fake_runtime: list[bool]) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from lunar_core.api import app

    client = TestClient(app)
    ok = client.post("/api/sky-geometry", json={"start_utc": "2027-01-01T00:00:00Z", "end_utc": "2027-01-01T02:00:00Z"})
    assert ok.status_code == 200
    assert ok.json()["settings"]["sample_count"] == 5
    bad = client.post("/api/sky-geometry", json={"start_utc": "2027-01-01T00:00:00", "end_utc": "2027-01-02T00:00:00Z"})
    assert bad.status_code == 422 and isinstance(bad.json()["detail"], list)
    schema = client.get("/api/openapi.json").json()
    assert "SkyGeometryResponse" in schema["components"]["schemas"]


@pytest.mark.usefixtures("unconfigured_project")
def test_http_unconfigured_is_503() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from lunar_core.api import app

    response = TestClient(app).post(
        "/api/sky-geometry", json={"start_utc": "2027-01-01T00:00:00Z", "end_utc": "2027-01-02T00:00:00Z"},
    )
    assert response.status_code == 503
