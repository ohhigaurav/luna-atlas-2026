#!/usr/bin/env python3
"""Fetch the documented DE421/MOON_ME SPICE kernel set and create a hash manifest.

Hashes establish the exact bytes used by a run; they are not an independent signature. Review
source URLs, licenses/credits, coverage and the frame chain before treating geometry as validated.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.kernels import KernelManifest  # noqa: E402
from lunar_core.provenance import sha256_file  # noqa: E402

BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/"
# Strict per-file ceilings prevent a compromised endpoint or bad URL from filling disk.
# DE421 is much larger than the text/FK files; these limits are intentionally generous.
MAX_KERNEL_BYTES = {
    "naif0012": 2_000_000,
    "pck00011": 2_000_000,
    "moon_080317": 2_000_000,
    "moon_assoc_me": 2_000_000,
    "de421": 100_000_000,
    "moon_pa_de421_1900_2050": 20_000_000,
}
KERNELS = [
    ("naif0012", "LSK", "lsk/naif0012.tls", "NAIF generic leap-seconds kernel; time conversion"),
    ("pck00011", "PCK", "pck/pck00011.tpc", "NAIF generic text planetary constants kernel"),
    ("moon_080317", "FK", "fk/satellites/moon_080317.tf", "NAIF lunar frame definitions"),
    ("moon_assoc_me", "FK", "fk/satellites/moon_assoc_me.tf", "NAIF DE421-associated Moon Mean-Earth frame alias"),
    ("de421", "SPK", "spk/planets/a_old_versions/de421.bsp", "NAIF planetary ephemeris DE421"),
    ("moon_pa_de421_1900_2050", "BPC", "pck/moon_pa_de421_1900-2050.bpc", "NAIF binary lunar orientation kernel associated with DE421"),
]


def _download(
    url: str,
    destination: Path,
    force: bool,
    *,
    previous_sha256: str | None = None,
    previous_url: str | None = None,
    max_bytes: int = 100_000_000,
) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "naif.jpl.nasa.gov":
        raise ValueError(f"Refusing download outside the approved NAIF HTTPS host: {url}")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if destination.exists() and not force:
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise ValueError(f"Existing kernel path is not a non-empty file: {destination}")
        if destination.stat().st_size > max_bytes:
            raise ValueError(
                f"Existing kernel {destination.name} exceeds the {max_bytes} byte safety limit; "
                "review and fetch fresh bytes with --force"
            )
        actual = sha256_file(destination)
        if previous_sha256 is None or previous_url != url or actual != previous_sha256:
            raise FileExistsError(
                f"Refusing to bless existing bytes for {destination.name}: the prior manifest does not "
                "prove these exact bytes came from this URL. Review the file and rerun with --force to fetch fresh bytes."
            )
        return {"downloaded": False, "path": str(destination), "sha256": actual, "bytes": destination.stat().st_size}
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "lunar-south-pole-planner/0.7.1-dev"})
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temp.open("wb") as stream:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != "naif.jpl.nasa.gov":
                raise ValueError(f"Refusing unexpected redirect destination: {response.geturl()}")
            raw_length = response.headers.get("Content-Length")
            expected_length: int | None = None
            if raw_length is not None:
                try:
                    expected_length = int(raw_length)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Invalid Content-Length for {url}: {raw_length!r}") from exc
                if expected_length < 0 or expected_length > max_bytes:
                    raise ValueError(
                        f"Kernel response size {expected_length} exceeds limit {max_bytes} bytes: {url}"
                    )
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(f"Kernel download exceeded {max_bytes} byte limit: {url}")
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if temp.stat().st_size == 0:
            raise ValueError(f"Downloaded empty kernel file from {url}")
        if expected_length is not None and total != expected_length:
            raise ValueError(
                f"Truncated kernel download: expected {expected_length} bytes, received {total} from {url}"
            )
        os.replace(temp, destination)
    except (urllib.error.URLError, TimeoutError, OSError):
        temp.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)
    return {"downloaded": True, "path": str(destination), "sha256": sha256_file(destination), "bytes": destination.stat().st_size}


def fetch(project_root: Path, force: bool = False) -> dict[str, object]:
    destination_root = project_root / "data" / "kernels"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    entries: list[dict[str, object]] = []
    outcomes: list[dict[str, object]] = []
    manifest_path = project_root / "data" / "manifests" / "kernels.json"
    previous_by_id: dict[str, dict[str, object]] = {}
    if manifest_path.exists() and not force:
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            previous_by_id = {
                str(entry.get("kernel_id")): entry
                for entry in old.get("kernels", [])
                if isinstance(entry, dict)
            }
        except (OSError, json.JSONDecodeError):
            previous_by_id = {}
    for order, (kernel_id, kernel_type, rel_url, role) in enumerate(KERNELS):
        url = BASE + rel_url
        path = destination_root / Path(rel_url).name
        previous = previous_by_id.get(kernel_id, {})
        if path.exists() and not force and previous.get("source_url") == url:
            if not previous.get("retrieved_utc"):
                raise ValueError(
                    f"{kernel_id}: prior manifest is missing retrieved_utc; use --force to fetch fresh bytes "
                    "rather than inventing provenance for a reused file"
                )
        outcome = _download(
            url, path, force,
            previous_sha256=str(previous.get("sha256")) if previous.get("sha256") else None,
            previous_url=str(previous.get("source_url")) if previous.get("source_url") else None,
            max_bytes=MAX_KERNEL_BYTES[kernel_id],
        )
        outcomes.append({"kernel_id": kernel_id, "source_url": url, **outcome})
        entry: dict[str, object] = {
            "kernel_id": kernel_id,
            "relative_path": path.relative_to(project_root).as_posix(),
            "kernel_type": kernel_type,
            "sha256": str(outcome["sha256"]),
            "size_bytes": int(outcome["bytes"]),
            "source_url": url,
            "licence_credit": f"NASA/JPL NAIF kernel. {role}. Cite NAIF and preserve source attribution.",
            "retrieved_utc": str(previous["retrieved_utc"]) if outcome.get("downloaded") is False else now,
            "load_order": order,
        }
        if kernel_type == "BPC":
            # The DE421 binary PCK stores orientation for MOON_PA_DE421. The FK defines
            # MOON_ME_DE421 as a fixed transform from that parent frame; coverage must be
            # checked on the actual PCK frame class, then the transform to MOON_ME verified.
            entry["coverage_frame"] = "MOON_PA_DE421"
        entries.append(entry)
    manifest = {
        "schema_version": "1.0",
        "manifest_state": "configured",
        "frame_contract": (
            "MOON_ME, DE421-associated orientation; check the loaded PCK radii and frame chain. "
            "Kernel presence and hashes do not constitute Horizons validation."
        ),
        "kernels": entries,
    }
    validated = KernelManifest.model_validate(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp = manifest_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(validated.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    temp.replace(manifest_path)
    return {"retrieved_utc": now, "manifest": str(manifest_path), "kernels": outcomes,
            "warning": "Do not label real geometry validated until JPL Horizons comparisons and coverage checks pass."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--force", action="store_true", help="re-fetch even if local bytes already exist")
    args = parser.parse_args()
    try:
        print(json.dumps(fetch(args.root.resolve(), args.force), indent=2))
    except Exception as exc:
        parser.exit(2, f"Kernel fetch failed: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
