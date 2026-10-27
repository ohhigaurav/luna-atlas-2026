from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_core.provenance import sha256_file


def test_sha256_matches_standard_library(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"SPICE and DEM assets must be hash-verified")
    assert sha256_file(path, chunk_size=7) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_hash_rejects_nonpositive_chunk_size(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(b"test")
    with pytest.raises(ValueError, match="positive"):
        sha256_file(path, chunk_size=0)
