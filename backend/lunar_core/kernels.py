"""Kernel-manifest parsing, SHA-256 verification, and ordered CSPICE loading.

This module verifies the bytes on disk before furnishing them. Actual SPK/BPC epoch coverage
queries remain a separate science gate and must be checked against the loaded kernel pool before
analysis. An empty/not-configured manifest is an expected pre-data state, never a ready state.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from lunar_core.provenance import sha256_file
from lunar_core.spice_runtime import SPICE_LOCK

KernelKind = Literal["LSK", "PCK", "BPC", "FK", "SPK", "OTHER"]


class KernelManifestError(ValueError):
    """Manifest syntax, schema or source-contract failure."""


class KernelLoadError(RuntimeError):
    """Kernel bytes failed integrity checks or CSPICE rejected the load sequence."""


class KernelAsset(BaseModel):
    """Manifest entry for one exact, immutable kernel file."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    kernel_id: str = Field(min_length=1, max_length=120)
    relative_path: str = Field(min_length=1, max_length=500)
    kernel_type: KernelKind
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    source_url: str = Field(min_length=1, max_length=2048)
    licence_credit: str = Field(min_length=1, max_length=1000)
    retrieved_utc: datetime
    load_order: int = Field(ge=0)
    # Binary PCK files store coverage for a specific frame class, which can be the parent
    # orientation frame rather than the final ME frame requested by the geometry API.
    coverage_frame: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("relative_path")
    @classmethod
    def relative_path_is_confined(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("relative_path must use forward slashes")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
            raise ValueError("relative_path must be a clean relative path without traversal")
        return value

    @field_validator("source_url")
    @classmethod
    def source_must_be_http(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("source_url must use HTTP(S)")
        return value

    @field_validator("retrieved_utc")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_utc must include a timezone")
        if value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("retrieved_utc must be UTC")
        return value


class KernelManifest(BaseModel):
    """Versioned manifest for the ordered kernel load set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    manifest_state: Literal["not_configured", "configured"]
    frame_contract: str = Field(min_length=1, max_length=2000)
    kernels: list[KernelAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_load_set(self) -> KernelManifest:
        if self.manifest_state == "not_configured" and self.kernels:
            raise ValueError("not_configured manifest must have an empty kernels list")
        if self.manifest_state == "configured" and not self.kernels:
            raise ValueError("configured manifest must contain kernels")
        if self.manifest_state == "configured":
            required_types = {"LSK", "PCK", "BPC", "FK", "SPK"}
            present_types = {asset.kernel_type for asset in self.kernels}
            missing_types = required_types - present_types
            if missing_types:
                raise ValueError(
                    "configured manifest is missing required kernel types: "
                    + ", ".join(sorted(missing_types))
                )
        for asset in self.kernels:
            if asset.kernel_type == "BPC" and not asset.coverage_frame:
                raise ValueError(
                    f"BPC asset {asset.kernel_id} must declare coverage_frame, the exact frame class "
                    "whose orientation is stored in this binary PCK"
                )
            if asset.kernel_type != "BPC" and asset.coverage_frame is not None:
                raise ValueError("coverage_frame is valid only for BPC assets")
        ids = [asset.kernel_id for asset in self.kernels]
        orders = [asset.load_order for asset in self.kernels]
        if len(set(ids)) != len(ids):
            raise ValueError("kernel_id values must be unique")
        if len(set(orders)) != len(orders):
            raise ValueError("load_order values must be unique")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedKernel:
    asset: KernelAsset
    absolute_path: Path
    actual_sha256: str


@dataclass(frozen=True, slots=True)
class KernelPreflightReport:
    manifest_state: str
    ready_to_load: bool
    manifest_sha256: str
    verified_kernels: tuple[VerifiedKernel, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KernelLoadReport:
    manifest_sha256: str
    loaded_kernel_ids: tuple[str, ...]
    loaded_paths: tuple[str, ...]
    kernel_hashes: tuple[tuple[str, str], ...]


class SpiceKernelPool(Protocol):
    def kclear(self) -> None: ...

    def furnsh(self, path: str) -> None: ...


def load_kernel_manifest(path: Path) -> KernelManifest:
    """Parse and validate a kernel manifest; malformed data raises an actionable exception."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KernelManifestError(f"cannot read kernel manifest at {path}: {exc}") from exc
    try:
        return KernelManifest.model_validate(payload)
    except ValidationError as exc:
        raise KernelManifestError(f"kernel manifest could not be validated: {exc}") from exc


def preflight_kernel_files(manifest_path: Path, project_root: Path) -> KernelPreflightReport:
    """Verify manifest state, path confinement, existence and SHA-256 before loading kernels."""
    manifest = load_kernel_manifest(manifest_path)
    manifest_hash = sha256_file(manifest_path)
    if manifest.manifest_state == "not_configured":
        return KernelPreflightReport(
            manifest_state=manifest.manifest_state,
            ready_to_load=False,
            manifest_sha256=manifest_hash,
            verified_kernels=(),
            issues=("kernel manifest is not configured; no SPICE geometry may run",),
        )

    root = project_root.resolve(strict=True)
    verified: list[VerifiedKernel] = []
    issues: list[str] = []
    for asset in sorted(manifest.kernels, key=lambda item: item.load_order):
        candidate = root / asset.relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            issues.append(f"{asset.kernel_id}: file not found at {asset.relative_path}")
            continue
        if not resolved.is_relative_to(root):
            issues.append(f"{asset.kernel_id}: path resolves outside project root")
            continue
        if not resolved.is_file():
            issues.append(f"{asset.kernel_id}: path is not a regular file")
            continue
        actual_size = resolved.stat().st_size
        if actual_size != asset.size_bytes:
            issues.append(
                f"{asset.kernel_id}: size mismatch (expected {asset.size_bytes} bytes, got {actual_size})"
            )
            continue
        try:
            actual_hash = sha256_file(resolved)
        except OSError as exc:
            issues.append(f"{asset.kernel_id}: cannot hash file ({exc})")
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", actual_hash) or actual_hash != asset.sha256:
            issues.append(
                f"{asset.kernel_id}: SHA-256 mismatch (expected {asset.sha256}, got {actual_hash})"
            )
            continue
        verified.append(VerifiedKernel(asset, resolved, actual_hash))

    return KernelPreflightReport(
        manifest_state=manifest.manifest_state,
        ready_to_load=not issues and len(verified) == len(manifest.kernels),
        manifest_sha256=manifest_hash,
        verified_kernels=tuple(verified),
        issues=tuple(issues),
    )


def load_verified_kernels(
    manifest_path: Path,
    project_root: Path,
    spice_pool: SpiceKernelPool,
) -> KernelLoadReport:
    """Replace the process kernel pool with the verified manifest load sequence.

    `kclear` is deliberate: the application owns this kernel pool and must avoid invisible kernels
    left by a previous run. Calls are serialized with all geometry operations. If one `furnsh`
    fails, the partially loaded pool is cleared and an exception is raised.
    """
    report = preflight_kernel_files(manifest_path, project_root)
    if not report.ready_to_load:
        issues = "; ".join(report.issues) if report.issues else "no verified kernels"
        raise KernelLoadError(f"kernel preflight failed: {issues}")

    loaded_ids: list[str] = []
    loaded_paths: list[str] = []
    loaded_hashes: list[tuple[str, str]] = []
    root = project_root.resolve(strict=True)
    with SPICE_LOCK:
        spice_pool.kclear()
        try:
            for kernel in report.verified_kernels:
                # Re-hash immediately before furnishing to narrow the file-change race after
                # preflight. No user-provided arbitrary path reaches CSPICE.
                current_path = kernel.absolute_path.resolve(strict=True)
                if not current_path.is_relative_to(root):
                    raise KernelLoadError(
                        f"{kernel.asset.kernel_id}: path escaped project root after preflight"
                    )
                current_hash = sha256_file(current_path)
                if current_hash != kernel.asset.sha256:
                    raise KernelLoadError(
                        f"{kernel.asset.kernel_id}: SHA-256 changed after preflight"
                    )
                spice_pool.furnsh(str(current_path))
                loaded_ids.append(kernel.asset.kernel_id)
                loaded_paths.append(str(current_path))
                loaded_hashes.append((kernel.asset.kernel_id, current_hash))
        except Exception as exc:
            spice_pool.kclear()
            if isinstance(exc, KernelLoadError):
                raise
            raise KernelLoadError(f"CSPICE failed during ordered kernel loading: {exc}") from exc

    return KernelLoadReport(
        manifest_sha256=report.manifest_sha256,
        loaded_kernel_ids=tuple(loaded_ids),
        loaded_paths=tuple(loaded_paths),
        kernel_hashes=tuple(loaded_hashes),
    )
