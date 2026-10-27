"""Load and validate the default official-site catalogue."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from lunar_core.models import SiteCatalogue


class CatalogueIntegrityError(RuntimeError):
    """Raised when default catalogue provenance or content is invalid."""


def default_catalogue_path() -> Path:
    """Resolve the repository's default catalogue without relying on the working directory."""
    return Path(__file__).resolve().parents[2] / "data" / "catalogue" / "sites.json"


def load_default_catalogue(path: Path | None = None) -> SiteCatalogue:
    """Load the official catalogue; fails closed on malformed or synthetic rows."""
    target = path or default_catalogue_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return SiteCatalogue.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise CatalogueIntegrityError(f"Catalogue could not be validated: {target}: {exc}") from exc
