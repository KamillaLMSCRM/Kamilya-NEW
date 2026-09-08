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

import argparse
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


def validate_release(repo: Path, *, expected_version: str = "") -> list[str]:
    errors = validate(repo)
    try:
        version = read_version_file(repo)
    except Exception:
        return errors

    if expected_version and version != expected_version:
        errors.append(
            f"expected version {expected_version!r} does not match VERSION={version!r}"
        )

    try:
        changelog = (repo / CHANGELOG).read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{CHANGELOG}: {exc}")
    else:
        release_heading = re.compile(
            rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
            re.MULTILINE,
        )
        match = release_heading.search(changelog)
        if match is None:
            errors.append(f"{CHANGELOG} has no dated release section for [{version}]")
        elif "## [Unreleased]" in changelog and changelog.index("## [Unreleased]") > match.start():
            errors.append(f"{CHANGELOG} [Unreleased] must precede [{version}]")

    notes_rel = f"docs/releases/v{version}.md"
    notes_path = repo / notes_rel
    if not notes_path.is_file():
        errors.append(f"release notes missing: {notes_rel}")
    else:
        notes = notes_path.read_text(encoding="utf-8")
        required_markers = (
            f"# Release Notes — {version}",
            f"**Product version:** {version}",
            f"**Git tag:** `v{version}`",
        )
        for marker in required_markers:
            if marker not in notes:
                errors.append(f"release notes missing identity marker: {marker}")
        placeholders = ("[VERSION]", "YYYY-MM-DD", "yes/no", "<full-or-short-SHA>")
        if any(placeholder in notes for placeholder in placeholders):
            errors.append(f"release notes contain an unresolved template placeholder: {notes_rel}")
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_root", nargs="?")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--expected-version", default="")
    args = parser.parse_args(argv[1:])
    repo = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parent.parent
    errors = (
        validate_release(repo, expected_version=args.expected_version)
        if args.release
        else validate(repo)
    )
    if errors:
        for err in errors:
            print(f"VERSION VALIDATION ERROR: {err}", file=sys.stderr)
        return 1
    version = read_version_file(repo)
    mode = "release" if args.release else "development"
    print(
        f"VERSION OK: {version} consistent across VERSION, "
        f"{API_MANIFEST}, {WEB_MANIFEST} ({mode})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
