"""Focused tests for scripts/validate_version.py.

Covers the real repository state (VERSION == API pyproject == web
package.json, changelog has [Unreleased]) plus synthetic edge cases.
Run: python -m pytest scripts/tests/test_validate_version.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate_version import validate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_FILE = "VERSION"
API_MANIFEST = "apps/api/pyproject.toml"
WEB_MANIFEST = "apps/web/package.json"


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / VERSION_FILE).write_text("0.1.0\n", encoding="utf-8")
    (repo / API_MANIFEST).parent.mkdir(parents=True)
    (repo / API_MANIFEST).write_text(
        "[tool.poetry]\nname = 'api'\nversion = '0.1.0'\n", encoding="utf-8"
    )
    (repo / WEB_MANIFEST).parent.mkdir(parents=True)
    (repo / WEB_MANIFEST).write_text(
        json.dumps({"name": "web", "version": "0.1.0"}), encoding="utf-8"
    )
    (repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- x\n", encoding="utf-8"
    )
    return repo


# --- real repository state -------------------------------------------------


def test_real_repo_versions_agree() -> None:
    assert validate(REPO_ROOT) == []


def test_real_repo_version_file_is_semver() -> None:
    text = (REPO_ROOT / VERSION_FILE).read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", text) is not None


# --- synthetic cases --------------------------------------------------------


def test_consistent_synthetic_repo_has_no_errors(tmp_path: Path) -> None:
    assert validate(make_repo(tmp_path)) == []


def test_version_file_mismatch_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / VERSION_FILE).write_text("0.2.0\n", encoding="utf-8")
    errors = validate(repo)
    assert any("version mismatch" in e for e in errors)


def test_api_manifest_mismatch_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / API_MANIFEST).write_text(
        "[tool.poetry]\nversion = '9.9.9'\n", encoding="utf-8"
    )
    assert validate(repo)


def test_web_manifest_mismatch_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / WEB_MANIFEST).write_text(
        json.dumps({"name": "web", "version": "1.2.3"}), encoding="utf-8"
    )
    assert validate(repo)


def test_missing_version_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / VERSION_FILE).unlink()
    errors = validate(repo)
    assert any("VERSION" in e for e in errors)


def test_empty_version_file(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / VERSION_FILE).write_text("", encoding="utf-8")
    errors = validate(repo)
    assert any("empty" in e for e in errors)


def test_non_semver_version_rejected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / VERSION_FILE).write_text("v0.1.0", encoding="utf-8")
    errors = validate(repo)
    assert any("semver" in e for e in errors)


def test_missing_unreleased_section_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    errors = validate(repo)
    assert any("Unreleased" in e for e in errors)
