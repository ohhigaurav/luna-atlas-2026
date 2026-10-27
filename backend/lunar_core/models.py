"""Typed data contracts. These schemas validate provenance; they do not establish scientific validity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Origin = Literal["official", "synthetic"]
LatitudeType = Literal["planetocentric", "planetographic"]
TerrainStatus = Literal["verified", "incomplete", "none"]


class SiteRecord(BaseModel):
    """Minimum site record contract from PRD FR-01 / DR-06."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    site_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    origin: Origin
    latitude_deg: float | None
    longitude_deg: float | None
    latitude_type: LatitudeType
    longitude_direction: Literal["east_positive"]
    source_url: str = Field(min_length=1, max_length=2048)
    source_record: str = Field(min_length=1, max_length=2000)
    retrieved_utc: datetime | None
    terrain_status: TerrainStatus
    dem_assets: list[str] = Field(default_factory=list)

    @field_validator("latitude_deg")
    @classmethod
    def check_latitude(cls, value: float | None) -> float | None:
        if value is not None and not -90.0 <= value <= 90.0:
            raise ValueError("latitude_deg must be within [-90, 90]")
        return value

    @field_validator("longitude_deg")
    @classmethod
    def check_longitude(cls, value: float | None) -> float | None:
        # The accepted numerical convention is deliberately documented separately; this
        # validator rejects only impossible values without silently normalising input.
        if value is not None and not -360.0 <= value <= 360.0:
            raise ValueError("longitude_deg must be within [-360, 360]")
        return value

    @field_validator("retrieved_utc")
    @classmethod
    def retrieved_time_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("retrieved_utc must include a timezone")
        if value is not None and value.utcoffset() != timezone.utc.utcoffset(value):
            # Normalize is a caller responsibility; requiring explicit UTC avoids ambiguous
            # retrieval timestamps in a provenance manifest.
            raise ValueError("retrieved_utc must be UTC (use Z or +00:00)")
        return value

    @model_validator(mode="after")
    def check_origin_contract(self) -> "SiteRecord":
        expected_prefix = "official-" if self.origin == "official" else "synthetic-"
        if not self.site_id.startswith(expected_prefix):
            raise ValueError(f"site_id for origin={self.origin!r} must start with {expected_prefix!r}")
        if self.origin == "official":
            if self.latitude_deg is None or self.longitude_deg is None:
                raise ValueError("official site coordinates must come from the official source")
            if not self.source_url.startswith(("https://", "http://")):
                raise ValueError("official site source_url must be HTTP(S)")
            if self.retrieved_utc is None:
                raise ValueError("official site requires retrieved_utc provenance")
        return self


class SiteCatalogue(BaseModel):
    """Default site-catalogue file contract; synthetic entries are forbidden here."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    catalogue_state: Literal["awaiting_official_source", "loaded"]
    source_url: str | None
    retrieved_utc: datetime | None
    sites: list[SiteRecord] = Field(default_factory=list)

    @field_validator("retrieved_utc")
    @classmethod
    def catalogue_time_must_be_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("catalogue retrieved_utc must include a timezone")
        if value is not None and value.utcoffset().total_seconds() != 0:
            raise ValueError("catalogue retrieved_utc must be UTC")
        return value

    @model_validator(mode="after")
    def check_catalogue_state(self) -> "SiteCatalogue":
        if any(site.origin != "official" for site in self.sites):
            raise ValueError("default catalogue must never contain synthetic test sites")
        if self.catalogue_state == "awaiting_official_source":
            if self.sites or self.source_url is not None or self.retrieved_utc is not None:
                raise ValueError("awaiting_official_source catalogue must be empty and un-sourced")
        elif not self.sites:
            raise ValueError("loaded catalogue must contain at least one official site")
        elif not self.source_url or not self.source_url.startswith(("https://", "http://")):
            raise ValueError("loaded catalogue requires an HTTP(S) source_url")
        elif self.retrieved_utc is None:
            raise ValueError("loaded catalogue requires retrieved_utc provenance")
        return self
