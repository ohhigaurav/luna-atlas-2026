from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from lunar_core.kernels import (
    KernelLoadError,
    KernelManifestError,
    load_kernel_manifest,
    load_verified_kernels,
    preflight_kernel_files,
)


class FakeKernelPool:
    def __init__(self, fail_on_path: str | None = None) -> None:
        self.furnsh_calls: list[str] = []
        self.kclear_calls = 0
        self.fail_on_path = fail_on_path

    def kclear(self) -> None:
        self.kclear_calls += 1

    def furnsh(self, path: str) -> None:
        self.furnsh_calls.append(path)
        if path == self.fail_on_path:
            raise RuntimeError("synthetic SPICE load failure")


def write_manifest(root: Path, *, mismatch_hash: bool = False) -> Path:
    kernel_dir = root / "kernels"
    kernel_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for order, (kernel_id, kind) in enumerate((
        ("lsk-test", "LSK"),
        ("pck-test", "PCK"),
        ("fk-test", "FK"),
        ("bpc-test", "BPC"),
        ("spk-test", "SPK"),
    )):
        relative_path = f"kernels/{kernel_id}.bin"
        content = f"test kernel bytes: {kernel_id}".encode()
        path = root / relative_path
        path.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        if mismatch_hash and kernel_id == "spk-test":
            digest = "0" * 64
        record = {
            "kernel_id": kernel_id,
            "relative_path": relative_path,
            "kernel_type": kind,
            "sha256": digest,
            "size_bytes": len(content),
            "source_url": f"https://example.nasa.gov/{kernel_id}",
            "licence_credit": "NAIF kernel; cite source and applicable data terms",
            "retrieved_utc": datetime(2026, 10, 25, tzinfo=UTC).isoformat(),
            "load_order": order,
        }
        if kind == "BPC":
            record["coverage_frame"] = "MOON_PA_DE421"
        records.append(record)
    manifest_path = root / "data" / "manifests" / "kernels.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({
        "schema_version": "1.0",
        "manifest_state": "configured",
        "frame_contract": "MOON_ME; test-only manifest",
        "kernels": records,
    }), encoding="utf-8")
    return manifest_path


def test_empty_default_manifest_is_not_ready_to_load(unconfigured_project: Path) -> None:
    root = unconfigured_project
    manifest = root / "data" / "manifests" / "kernels.json"
    report = preflight_kernel_files(manifest, root)
    assert not report.ready_to_load
    assert report.manifest_state == "not_configured"
    assert report.verified_kernels == ()
    assert "not configured" in report.issues[0]


def test_preflight_checks_all_sha256_hashes_and_orders_assets(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    report = preflight_kernel_files(manifest_path, tmp_path)

    assert report.ready_to_load
    assert not report.issues
    assert [kernel.asset.load_order for kernel in report.verified_kernels] == list(range(5))
    assert all(kernel.actual_sha256 == kernel.asset.sha256 for kernel in report.verified_kernels)


def test_preflight_fails_closed_on_hash_mismatch(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path, mismatch_hash=True)
    report = preflight_kernel_files(manifest_path, tmp_path)

    assert not report.ready_to_load
    assert any("SHA-256 mismatch" in issue for issue in report.issues)
    with pytest.raises(KernelLoadError, match="preflight failed"):
        load_verified_kernels(manifest_path, tmp_path, FakeKernelPool())


def test_path_traversal_is_rejected_by_manifest_schema(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["kernels"][0]["relative_path"] = "../outside.bin"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(KernelManifestError, match="relative path"):
        load_kernel_manifest(manifest_path)


def test_verified_kernels_are_furnished_in_declared_order(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    spice = FakeKernelPool()
    result = load_verified_kernels(manifest_path, tmp_path, spice)

    assert result.loaded_kernel_ids == (
        "lsk-test", "pck-test", "fk-test", "bpc-test", "spk-test"
    )
    assert spice.kclear_calls == 1
    assert spice.furnsh_calls == list(result.loaded_paths)
    assert len(result.kernel_hashes) == 5


def test_partial_spice_load_is_cleared_and_reported(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    fail_path = str((tmp_path / "kernels" / "bpc-test.bin").resolve())
    spice = FakeKernelPool(fail_on_path=fail_path)

    with pytest.raises(KernelLoadError, match="ordered kernel loading"):
        load_verified_kernels(manifest_path, tmp_path, spice)

    assert spice.kclear_calls == 2  # Clear before load, then clear partial state on failure.
    assert spice.furnsh_calls[-1] == fail_path


def test_configured_manifest_requires_core_kernel_roles(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["kernels"] = [asset for asset in payload["kernels"] if asset["kernel_type"] != "BPC"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(KernelManifestError, match="missing required kernel types: BPC"):
        load_kernel_manifest(manifest_path)


def test_preflight_rejects_symlink_that_escapes_project_root(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    outside = tmp_path.parent / f"outside-{tmp_path.name}.bin"
    outside.write_bytes(b"outside bytes")
    link = tmp_path / "kernels" / "lsk-test.bin"
    link.unlink()
    link.symlink_to(outside)

    report = preflight_kernel_files(manifest_path, tmp_path)
    assert not report.ready_to_load
    assert any("path resolves outside project root" in issue for issue in report.issues)


def test_bpc_manifest_requires_explicit_stored_coverage_frame(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    bpc_record = next(asset for asset in payload["kernels"] if asset["kernel_type"] == "BPC")
    del bpc_record["coverage_frame"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(KernelManifestError, match="must declare coverage_frame"):
        load_kernel_manifest(manifest_path)


def test_preflight_rejects_size_mismatch_before_hash_acceptance(tmp_path: Path) -> None:
    manifest_path = write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["kernels"][0]["size_bytes"] += 1
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    report = preflight_kernel_files(manifest_path, tmp_path)
    assert not report.ready_to_load
    assert any("size mismatch" in issue for issue in report.issues)


def test_analysis_kernel_pool_is_loaded_once_and_reloaded_only_when_bytes_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lunar_core import analysis_service

    manifest_path = write_manifest(tmp_path)
    monkeypatch.setattr(analysis_service, "KERNEL_MANIFEST", manifest_path)
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", None)
    pool = FakeKernelPool()

    first = analysis_service._ensure_kernels_loaded(pool)
    second = analysis_service._ensure_kernels_loaded(pool)
    assert second is first
    assert pool.kclear_calls == 1  # no kclear/furnsh on the second request
    assert len(pool.furnsh_calls) == 5

    # Replace a kernel's bytes and update the manifest accordingly: the pool must be reloaded.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    new_bytes = b"replacement kernel bytes"
    (tmp_path / "kernels" / "spk-test.bin").write_bytes(new_bytes)
    for record in manifest["kernels"]:
        if record["kernel_id"] == "spk-test":
            record["sha256"] = hashlib.sha256(new_bytes).hexdigest()
            record["size_bytes"] = len(new_bytes)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    third = analysis_service._ensure_kernels_loaded(pool)
    assert third is not first
    assert pool.kclear_calls == 2
    assert len(pool.furnsh_calls) == 10


def test_analysis_kernel_pool_refuses_tampered_bytes_even_when_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lunar_core import analysis_service

    manifest_path = write_manifest(tmp_path)
    monkeypatch.setattr(analysis_service, "KERNEL_MANIFEST", manifest_path)
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", None)
    pool = FakeKernelPool()
    analysis_service._ensure_kernels_loaded(pool)
    (tmp_path / "kernels" / "lsk-test.bin").write_bytes(b"test kernel bytes: lsk-tesX")
    with pytest.raises(analysis_service.AnalysisNotReady, match="SHA-256 mismatch"):
        analysis_service._ensure_kernels_loaded(pool)
