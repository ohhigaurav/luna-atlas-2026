from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_official_sites import import_catalogue  # noqa: E402


def _write_csv(path: Path, *, longitude_direction: str = "east_positive") -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "source_site_id", "name", "latitude_deg", "longitude_deg",
            "latitude_type", "longitude_direction",
        ])
        writer.writeheader()
        writer.writerow({
            "source_site_id": "cand-01", "name": "Candidate One", "latitude_deg": "-89.1",
            "longitude_deg": "143.0", "latitude_type": "planetocentric",
            "longitude_direction": longitude_direction,
        })


def test_official_site_import_preserves_source_row_and_checksums(tmp_path: Path) -> None:
    source = tmp_path / "official.csv"
    output = tmp_path / "sites.json"
    _write_csv(source)
    result = import_catalogue(source, "https://www.spaceappschallenge.org/2026/", output)
    assert result["site_count"] == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    site = payload["sites"][0]
    assert payload["catalogue_state"] == "loaded"
    assert site["site_id"] == "official-cand-01"
    assert site["origin"] == "official"
    assert "source_csv_sha256" in site["source_record"]
    assert "Candidate One" in site["source_record"]


def test_official_site_import_normalises_west_positive_longitudes_and_preserves_original(tmp_path: Path) -> None:
    source = tmp_path / "official.csv"
    output = tmp_path / "sites.json"
    _write_csv(source, longitude_direction="west_positive")
    import_catalogue(source, "https://www.spaceappschallenge.org/2026/", output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    site = payload["sites"][0]
    assert site["longitude_deg"] == pytest.approx(217.0)
    assert site["longitude_direction"] == "east_positive"
    assert "west_positive" in site["source_record"]


def test_official_site_import_rejects_http_source_url(tmp_path: Path) -> None:
    source = tmp_path / "official.csv"
    _write_csv(source)
    with pytest.raises(ValueError, match="HTTPS"):
        import_catalogue(source, "http://example.test/sites", tmp_path / "sites.json")


def test_kernel_fetcher_will_not_relabel_unmanifested_existing_bytes(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from fetch_kernels import _download  # noqa: E402

    destination = tmp_path / "naif0012.tls"
    destination.write_text("not a verified kernel", encoding="utf-8")
    with pytest.raises(FileExistsError, match="Refusing to bless existing bytes"):
        _download(
            "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls",
            destination, False,
        )


def test_kernel_fetcher_reuses_only_bytes_matching_previous_manifest(tmp_path: Path) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    from fetch_kernels import _download  # noqa: E402
    from lunar_core.provenance import sha256_file

    destination = tmp_path / "naif0012.tls"
    destination.write_text("verified test bytes", encoding="utf-8")
    url = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/lsk/naif0012.tls"
    outcome = _download(url, destination, False, previous_sha256=sha256_file(destination), previous_url=url)
    assert outcome["downloaded"] is False



def test_official_site_import_rejects_unofficial_https_source(tmp_path: Path) -> None:
    source = tmp_path / "sites.csv"
    _write_csv(source)
    with pytest.raises(ValueError, match="spaceappschallenge.org or a NASA-owned"):
        import_catalogue(source, "https://example.com/fake-official-sites.csv", tmp_path / "out.json")


def test_official_site_import_rejects_coordinate_out_of_range(tmp_path: Path) -> None:
    source = tmp_path / "sites.csv"
    output = tmp_path / "sites.json"
    _write_csv(source)
    content = source.read_text(encoding="utf-8").replace("-89.1", "-91.0")
    source.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="latitude must lie"):
        import_catalogue(source, "https://www.spaceappschallenge.org/2026/", output)
    assert not output.exists()


class _FakeResponse:
    def __init__(self, body: bytes, *, content_length: str, final_url: str | None = None) -> None:
        self._body = body
        self._read = False
        self.headers = {"Content-Length": content_length}
        self._final_url = final_url or "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/test.bin"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def geturl(self) -> str:
        return self._final_url

    def read(self, size: int = -1) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body[:size] if size >= 0 else self._body


def test_kernel_fetcher_rejects_content_length_above_limit_before_writing(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import fetch_kernels  # noqa: E402

    monkeypatch.setattr(
        fetch_kernels.urllib.request, "urlopen",
        lambda request, timeout=120: _FakeResponse(b"1234", content_length="500"),
    )
    destination = tmp_path / "kernel.bpc"
    with pytest.raises(ValueError, match="exceeds limit"):
        fetch_kernels._download(
            "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/test.bpc",
            destination, True, max_bytes=100,
        )
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []


def test_kernel_fetcher_rejects_truncated_body_and_cleans_temporary_file(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    import fetch_kernels  # noqa: E402

    monkeypatch.setattr(
        fetch_kernels.urllib.request, "urlopen",
        lambda request, timeout=120: _FakeResponse(b"short", content_length="12"),
    )
    destination = tmp_path / "kernel.bpc"
    with pytest.raises(ValueError, match="Truncated kernel download"):
        fetch_kernels._download(
            "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/test.bpc",
            destination, True, max_bytes=100,
        )
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
