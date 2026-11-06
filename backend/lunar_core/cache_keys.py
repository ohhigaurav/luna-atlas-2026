"""Shared ingredients for answer-cache keys, so a cached answer can never outlive what produced it.

Independent review (6 Nov) found three ways a cached landing, check or ellipse answer could go
stale while still being served with ``cache_hit: true``:
  * the key hashed the request (``site_id``), not the resolved site record, so re-importing an
    official site with corrected coordinates kept the old answer;
  * ``__version__`` never changed, so a code change that forgot a hand-bumped schema string was
    never invalidated;
  * manifests entered as file modification times, not contents.
Every key now includes the site record, a fingerprint of the backend source, and the manifests'
content hashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
SITE_FIELDS = ("site_id", "latitude_deg", "longitude_deg", "latitude_type", "longitude_direction", "origin")


@lru_cache(maxsize=1)
def code_fingerprint() -> str:
    """SHA-256 over the backend package's .py sources (names and bytes), computed once per process."""
    h = hashlib.sha256()
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


@lru_cache(maxsize=32)
def _digest(path: str, mtime_ns: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def file_digest(path: Path) -> str | None:
    """Content hash of a file, memoised by (path, mtime, size); None if missing."""
    try:
        st = path.stat()
    except OSError:
        return None
    return _digest(str(path), st.st_mtime_ns, st.st_size)


def site_fingerprint(site: dict[str, Any]) -> dict[str, Any]:
    """The parts of a resolved site record that change answers."""
    return {k: site.get(k) for k in SITE_FIELDS}


def key_material(*, site: dict[str, Any], manifests: tuple[Path, ...]) -> dict[str, Any]:
    return {"code": code_fingerprint(), "site": site_fingerprint(site),
            "manifests": {p.name: file_digest(p) for p in manifests}}


def write_atomic(path: Path, text: str) -> None:
    """Write via a temp file and rename, so a reader never sees half a cache entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


__all__ = ["code_fingerprint", "file_digest", "key_material", "site_fingerprint", "write_atomic"]
