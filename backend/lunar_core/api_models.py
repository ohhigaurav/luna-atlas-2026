"""Public API request contracts. Units are explicit in field names; invalid spans fail early."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CommonScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    site_ids: list[str] = Field(min_length=1, max_length=4)
    coarse_step_min: int = Field(default=30, ge=5, le=120)
    event_tolerance_s: float = Field(default=1.0, ge=0.1, le=60.0)
    sun_observer_height_m: float = Field(default=2.0, ge=0.0, le=100.0)
    antenna_height_m: float = Field(default=2.0, ge=0.0, le=100.0)
    earth_min_clearance_deg: float = Field(default=0.0, ge=0.0, le=10.0)
    horizon_mode: Literal["flat", "terrain"] = "flat"
    terrain_azimuth_step_deg: float = Field(default=0.5, ge=0.25, le=5.0)
    terrain_max_range_m: float = Field(default=200_000.0, ge=10_000.0, le=250_000.0)
    terrain_near_range_m: float = Field(default=8_000.0, ge=100.0, le=50_000.0)
    terrain_near_step_m: float = Field(default=5.0, ge=1.0, le=100.0)
    terrain_far_step_m: float = Field(default=240.0, ge=5.0, le=2000.0)

    @field_validator("site_ids")
    @classmethod
    def ids_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("site_ids must be unique")
        return value

    @model_validator(mode="after")
    def terrain_ranges_valid(self) -> CommonScenario:
        if self.terrain_near_range_m >= self.terrain_max_range_m:
            raise ValueError("terrain_near_range_m must be less than terrain_max_range_m")
        return self


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include timezone (use Z or +00:00)")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamps must be UTC (non-zero offsets are not accepted)")
    return value.astimezone(UTC)


class AnalysisRequest(CommonScenario):
    start_utc: datetime
    end_utc: datetime

    @field_validator("start_utc", "end_utc")
    @classmethod
    def timestamps_must_be_explicit_utc(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_scenario(self) -> AnalysisRequest:
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        span_days = (self.end_utc - self.start_utc).total_seconds() / 86400.0
        if span_days > 60:
            raise ValueError("analysis span is capped at 60 days; use the date finder for wider searches")
        sample_count = int(span_days * 1440 / self.coarse_step_min) + 2
        if sample_count > 18_000:
            raise ValueError("analysis sample count exceeds safety cap")
        return self


class MissionConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_darkness_h: float | None = Field(default=50.0, ge=0.0, le=24 * 60)
    max_dte_gap_h: float | None = Field(default=24.0, ge=0.0, le=24 * 60)
    max_joint_outage_h: float | None = Field(default=12.0, ge=0.0, le=24 * 60)
    min_sunlit_fraction: float | None = Field(default=0.6, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_active_constraint(self) -> MissionConstraints:
        if all(getattr(self, name) is None for name in (
            "max_darkness_h", "max_dte_gap_h", "max_joint_outage_h", "min_sunlit_fraction"
        )):
            raise ValueError("at least one mission constraint must be enabled")
        return self


class FinderRequest(CommonScenario):
    search_start_utc: datetime
    search_end_utc: datetime
    candidate_step_days: int = Field(default=1, ge=1, le=14)
    mission_duration_days: int = Field(default=14, ge=1, le=30)
    constraints: MissionConstraints = Field(default_factory=MissionConstraints)

    @field_validator("search_start_utc", "search_end_utc")
    @classmethod
    def search_timestamps_must_be_explicit_utc(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_search(self) -> FinderRequest:
        if self.search_end_utc < self.search_start_utc:
            raise ValueError("search_end_utc must not precede search_start_utc")
        candidate_count = int(
            (self.search_end_utc - self.search_start_utc).total_seconds()
            / (self.candidate_step_days * 86400)
        ) + 1
        if candidate_count > 180:
            raise ValueError("finder is capped at 180 candidate start dates")
        if (self.search_end_utc - self.search_start_utc).total_seconds() / 86400 > 180:
            raise ValueError("finder search range is capped at 180 days")
        return self


SKY_GEOMETRY_MAX_DAYS = 400
SKY_GEOMETRY_MAX_SAMPLES = 18_000


class SkyGeometryRequest(BaseModel):
    """Time grid for Moon-centred Sun/Earth directions (the 3D scene's lighting and sky)."""

    model_config = ConfigDict(extra="forbid")

    start_utc: datetime
    end_utc: datetime
    step_min: int = Field(default=30, ge=1, le=1440)

    @field_validator("start_utc", "end_utc")
    @classmethod
    def sky_timestamps_must_be_explicit_utc(cls, value: datetime) -> datetime:
        return _utc_datetime(value)

    @model_validator(mode="after")
    def validate_grid(self) -> SkyGeometryRequest:
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        span_s = (self.end_utc - self.start_utc).total_seconds()
        if span_s / 86400.0 > SKY_GEOMETRY_MAX_DAYS:
            raise ValueError(f"sky geometry span is capped at {SKY_GEOMETRY_MAX_DAYS} days")
        if int(span_s // (self.step_min * 60)) + 2 > SKY_GEOMETRY_MAX_SAMPLES:
            raise ValueError(
                f"sky geometry is capped at {SKY_GEOMETRY_MAX_SAMPLES} samples; use a larger step_min"
            )
        return self


class BodyTrackModel(BaseModel):
    unit: list[list[float]] = Field(description="Unit vectors in the run frame, one [x, y, z] per sample")
    distance_km: list[float]
    sub_lat_deg: list[float] = Field(description="Planetocentric latitude of the sub-point")
    sub_lon_east_deg: list[float] = Field(description="East longitude of the sub-point in [0, 360)")
    angular_radius_deg: list[float]


class EarthTrackModel(BodyTrackModel):
    phase_angle_deg: list[float] = Field(description="Angle Sun-Earth-Moon at Earth (SPICE phaseq)")
    illuminated_fraction: list[float] = Field(description="Lit fraction of Earth's disc seen from the Moon")


class SkySeriesModel(BaseModel):
    utc: list[str]
    et_s: list[float]
    sun: BodyTrackModel
    earth: EarthTrackModel


class SkyGeometrySettings(BaseModel):
    start_utc: str
    end_utc: str
    step_min: int
    sample_count: int


class SkyGeometryProvenance(BaseModel):
    software_version: str
    kernel_manifest_sha256: str
    loaded_kernel_ids: list[str]
    kernel_pool: Literal["preflighted", "reused_from_active_run"]
    spk_coverage_preflight: object
    bpc_coverage_preflight: object
    time_contract: str


class SkyGeometryResponse(BaseModel):
    schema_version: Literal["1.0"]
    kind: Literal["sky_geometry"]
    frame: str
    observer_center: Literal["MOON"]
    aberration_correction: str
    moon_reference_radius_m: float
    conventions: dict[str, str]
    settings: SkyGeometrySettings
    provenance: SkyGeometryProvenance
    series: SkySeriesModel


class CheckRequest(BaseModel):
    """One-button site check: the server picks every scientific setting (see lunar_core.check)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    site_id: str = Field(min_length=1, max_length=100)
    start_utc: datetime
    days: int = Field(default=30, ge=1, le=60)
    panel_height_m: float = Field(default=2.0, ge=0.0, le=10.0)

    @field_validator("start_utc")
    @classmethod
    def check_start_must_be_explicit_utc(cls, value: datetime) -> datetime:
        return _utc_datetime(value)


class LandingRequest(BaseModel):
    """Landing opportunities search (see lunar_core.landing for the rules)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    site_id: str = Field(min_length=1, max_length=100)
    search_start_utc: datetime
    search_days: int = Field(default=90, ge=1, le=180)
    mission_days: float = Field(default=10.0, ge=0.25, le=30.0)
    panel_height_m: float = Field(default=2.0, ge=0.0, le=10.0)
    require_earth_at_landing: bool = True
    max_sun_elevation_deg: float | None = Field(default=20.0, ge=0.0, le=90.0)

    @field_validator("search_start_utc")
    @classmethod
    def landing_start_must_be_explicit_utc(cls, value: datetime) -> datetime:
        return _utc_datetime(value)
