#!/usr/bin/env python3
"""Deterministic product version-consistency validator.

Asserts that the canonical VERSION file, the backend manifest
(apps/api/pyproject.toml) and the frontend manifest (apps/web/package.json)
all declare the same version, and that CHANGELOG.md contains an
[Unreleased] section.

Exit codes: 0 = consistent, 1 = any mismatch or structural problem.

Usage:
    python scripts/validate_version.py [repo_root]

Default repo_root is the parent of this script's directory.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

VERSION_FILE = "VERSION"
API_MANIFEST = "apps/api/pyproject.toml"
WEB_MANIFEST = "apps/web/package.json"
CHANGELOG = "CHANGELOG.md"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def read_version_file(repo: Path) -> str:
    raw = (repo / VERSION_FILE).read_text(encoding="utf-8").strip()
    if not raw:
        raise ValueError(f"{VERSION_FILE} is empty")
    if not SEMVER_RE.match(raw):
        raise ValueError(f"{VERSION_FILE} value {raw!r} is not X.Y.Z semver")
    return raw


def read_api_version(repo: Path) -> str:
    data = tomllib.loads((repo / API_MANIFEST).read_text(encoding="utf-8"))
    version = data.get("tool", {}).get("poetry", {}).get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{API_MANIFEST} has no [tool.poetry] version")
    return version


def read_web_version(repo: Path) -> str:
    data = json.loads((repo / WEB_MANIFEST).read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError(f"{WEB_MANIFEST} has no version field")
    return version


def check_changelog(repo: Path) -> None:
    text = (repo / CHANGELOG).read_text(encoding="utf-8")
    if "## [Unreleased]" not in text:
        raise ValueError(f"{CHANGELOG} has no '## [Unreleased]' section")


def validate(repo: Path) -> list[str]:
    errors: list[str] = []
    versions: dict[str, str] = {}
    for label, path, reader in (
        (VERSION_FILE, VERSION_FILE, read_version_file),
        (API_MANIFEST, API_MANIFEST, read_api_version),
        (WEB_MANIFEST, WEB_MANIFEST, read_web_version),
    ):
        try:
            versions[label] = reader(repo)
        except Exception as exc:  # deterministic report, non-zero exit
            errors.append(f"{path}: {exc}")
    if len(set(versions.values())) > 1:
        errors.append(
            "version mismatch: "
            + ", ".join(f"{k}={v}" for k, v in versions.items())
        )
    try:
        check_changelog(repo)
    except Exception as exc:
        errors.append(str(exc))
    return errors


def main(argv: list[str]) -> int:
    repo = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    errors = validate(repo)
    if errors:
        for err in errors:
            print(f"VERSION VALIDATION ERROR: {err}", file=sys.stderr)
        return 1
    version = read_version_file(repo)
    print(f"VERSION OK: {version} consistent across VERSION, {API_MANIFEST}, {WEB_MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
