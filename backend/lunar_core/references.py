"""Public research reference points; kept separate from the official challenge catalogue."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ReferenceSite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    site_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-360.0, le=360.0)
    latitude_type: Literal["planetocentric", "planetographic"]
    longitude_direction: Literal["east_positive"]
    source_url: str = Field(min_length=8, max_length=2048)
    source_record: str = Field(min_length=1, max_length=2000)
    terrain_status: Literal["verified", "incomplete", "none"] = "none"
    kind: Literal["literature_reference_point"]

    @field_validator("source_url")
    @classmethod
    def source_is_http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("source_url must use HTTP(S)")
        return value


class ReferenceCatalogue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"]
    catalogue_kind: Literal["literature_reference_points"]
    note: str
    sites: list[ReferenceSite]


def default_reference_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "reference" / "reference_sites.json"


def load_reference_catalogue(path: Path | None = None) -> ReferenceCatalogue:
    target = path or default_reference_path()
    try:
        return ReferenceCatalogue.model_validate(json.loads(target.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(f"Reference catalogue is invalid: {target}: {exc}") from exc
