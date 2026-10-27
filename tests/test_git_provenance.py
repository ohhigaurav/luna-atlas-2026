from __future__ import annotations

import subprocess
from pathlib import Path

from lunar_core import analysis_service


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, text=True, capture_output=True,
    )
    return result.stdout.strip()


def test_git_revision_is_recorded_only_for_exact_clean_tree(tmp_path: Path, monkeypatch) -> None:
    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.name", "Test Engineer")
    _git(tmp_path, "config", "user.email", "test-engineer@example.invalid")
    source_file = tmp_path / "science.py"
    source_file.write_text("value = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "science.py")
    _git(tmp_path, "commit", "--quiet", "-m", "baseline")
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)

    expected = _git(tmp_path, "rev-parse", "HEAD")
    assert analysis_service._git_commit() == expected

    source_file.write_text("value = 2\n", encoding="utf-8")
    assert analysis_service._git_commit() is None
