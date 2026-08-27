#!/usr/bin/env python3
"""Fail-closed validator and impact resolver for critical user journeys."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "docs" / "critical-journeys" / "ai-course-generation.json"


class ContractError(RuntimeError):
    """Sanitized critical-journey contract failure."""


@dataclass(frozen=True, slots=True)
class Journey:
    journey_id: str
    title: str
    trigger_paths: tuple[str, ...]
    required_tests: tuple[str, ...]
    runtime_gates: tuple[str, ...]
    invariants: tuple[str, ...]


def _string_tuple(value: Any, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{field}_required")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ContractError(f"{field}_invalid")
        normalized.append(item.strip().replace("\\", "/"))
    if len(normalized) != len(set(normalized)):
        raise ContractError(f"{field}_duplicate")
    return tuple(normalized)


def _repo_file(reference: str) -> Path:
    path = reference.split("::", 1)[0]
    candidate = (REPO_ROOT / path).resolve()
    try:
        candidate.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise ContractError("contract_path_outside_repository") from exc
    return candidate


def load_contract(path: Path = DEFAULT_CONTRACT) -> tuple[Journey, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("critical_journey_contract_unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ContractError("critical_journey_schema_version_invalid")
    raw_journeys = payload.get("journeys")
    if not isinstance(raw_journeys, list) or not raw_journeys:
        raise ContractError("critical_journeys_required")

    journeys: list[Journey] = []
    seen_ids: set[str] = set()
    for raw in raw_journeys:
        if not isinstance(raw, dict):
            raise ContractError("critical_journey_invalid")
        journey_id = raw.get("id")
        title = raw.get("title")
        if not isinstance(journey_id, str) or not journey_id.strip():
            raise ContractError("critical_journey_id_required")
        if journey_id in seen_ids:
            raise ContractError("critical_journey_id_duplicate")
        if not isinstance(title, str) or not title.strip():
            raise ContractError("critical_journey_title_required")
        seen_ids.add(journey_id)
        journey = Journey(
            journey_id=journey_id,
            title=title.strip(),
            trigger_paths=_string_tuple(raw.get("trigger_paths"), field="trigger_paths"),
            required_tests=_string_tuple(raw.get("required_tests"), field="required_tests"),
            runtime_gates=_string_tuple(raw.get("runtime_gates"), field="runtime_gates"),
            invariants=_string_tuple(raw.get("invariants"), field="invariants"),
        )
        for selector in journey.required_tests:
            if "::" not in selector or not _repo_file(selector).is_file():
                raise ContractError("required_test_selector_missing")
        for gate in journey.runtime_gates:
            if not _repo_file(gate).is_file():
                raise ContractError("runtime_gate_missing")
        journeys.append(journey)
    return tuple(journeys)


def impacted_journeys(
    journeys: Iterable[Journey],
    changed_files: Iterable[str],
) -> tuple[Journey, ...]:
    normalized_files = tuple(
        path.strip().replace("\\", "/").removeprefix("./")
        for path in changed_files
        if path.strip()
    )
    return tuple(
        journey
        for journey in journeys
        if any(
            fnmatch.fnmatchcase(changed_file, pattern)
            for changed_file in normalized_files
            for pattern in journey.trigger_paths
        )
    )


def pytest_selectors(journeys: Iterable[Journey], pytest_root: Path) -> tuple[str, ...]:
    root = pytest_root.resolve()
    selectors: list[str] = []
    for journey in journeys:
        for selector in journey.required_tests:
            path_text, node = selector.split("::", 1)
            relative = os.path.relpath((REPO_ROOT / path_text).resolve(), root).replace("\\", "/")
            normalized = f"{relative}::{node}"
            if normalized not in selectors:
                selectors.append(normalized)
    return tuple(selectors)


def run(
    *,
    all_journeys: bool,
    changed_files: Iterable[str],
    contract_path: Path,
    pytest_root: Path,
    emit_pytest_args: Path | None,
) -> dict[str, Any]:
    journeys = load_contract(contract_path)
    selected = journeys if all_journeys else impacted_journeys(journeys, changed_files)
    selectors = pytest_selectors(selected, pytest_root)
    if emit_pytest_args is not None:
        emit_pytest_args.write_text("".join(f"{selector}\n" for selector in selectors), encoding="utf-8")
    return {
        "status": "READY" if selected else "NOT_APPLICABLE",
        "evidence_label": "GIT-DERIVED",
        "journeys": [journey.journey_id for journey in selected],
        "required_tests": len(selectors),
        "runtime_gates": sorted({gate for journey in selected for gate in journey.runtime_gates}),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", dest="all_journeys")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--pytest-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--emit-pytest-args", type=Path)
    args = parser.parse_args()
    if not args.all_journeys and not args.changed_file:
        print(json.dumps({"status": "BLOCKED", "error_class": "changed_files_required"}, sort_keys=True))
        return 1
    try:
        result = run(
            all_journeys=args.all_journeys,
            changed_files=args.changed_file,
            contract_path=args.contract,
            pytest_root=(REPO_ROOT / args.pytest_root if not args.pytest_root.is_absolute() else args.pytest_root),
            emit_pytest_args=args.emit_pytest_args,
        )
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
