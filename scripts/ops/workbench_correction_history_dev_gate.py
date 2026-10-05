#!/usr/bin/env python3
"""Exact opt-in learner history proof in an owned canonical DEV schema."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "apps/api", ROOT / "scripts/ops"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from dotenv import load_dotenv  # noqa: E402
from workbench_correction_application_dev_gate import REQUIRED_CHECKS as APPLICATION_CHECKS, run_gate  # noqa: E402
from workbench_correction_history_dev_checks import HISTORY_CHECKS, verify_history  # noqa: E402
from workbench_correction_lifecycle_dev_gate import SOURCE_FILES as LIFECYCLE_SOURCES, apply_0178  # noqa: E402
from workbench_document_dev_gate import (  # noqa: E402
    GateBlocked, assert_sanitized_evidence, canonical_config, sanitize_failure,
)

REQUIRED_CHECKS = (APPLICATION_CHECKS - {"empty_downgrade_reupgrade"}) | HISTORY_CHECKS
SOURCE_FILES = LIFECYCLE_SOURCES + (
    "scripts/ops/workbench_correction_application_dev_checks.py",
    "scripts/ops/workbench_correction_history_dev_checks.py",
    "scripts/ops/workbench_correction_history_dev_gate.py",
    "scripts/ops/workbench_correction_dev_checks.py",
    "apps/api/app/models/enrollment.py",
    "apps/api/app/models/users.py",
    "apps/api/app/modules/certificates/models.py",
    "apps/api/app/modules/quizzes/models.py",
    "apps/api/app/modules/courses/models.py",
    "apps/api/app/modules/courses/release_models.py",
    "scripts/ops/workbench_correction_dev_gate.py",
    "scripts/ops/workbench_document_dev_gate.py",
    "scripts/ops/source_actuality_dev_gate.py",
    "scripts/ops/kb_rag_isolated_dev_gate.py",
    "apps/api/alembic/versions/0176_workbench_lesson_correction_previews.py",
    "apps/api/alembic/versions/0177_workbench_lesson_correction_applications.py",
    "apps/api/app/modules/methodologist_workbench/correction_context.py",
    "apps/api/app/modules/methodologist_workbench/correction_contract.py",
    "apps/api/app/modules/methodologist_workbench/correction_proposal.py",
    "apps/api/app/modules/methodologist_workbench/correction_schemas.py",
    "apps/api/app/modules/methodologist_workbench/assignment_service.py",
    "apps/api/app/modules/methodologist_workbench/plan_contract.py",
    "apps/api/app/modules/lessons/service.py",
    "apps/api/app/modules/course_approval/service.py",
    "apps/api/app/modules/audit/service.py",
    "apps/api/app/core/auth.py",
)


def source_hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_FILES}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        common = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        if args.env_file.resolve() != (Path(common).parent / ".env").resolve():
            raise GateBlocked("noncanonical_env_file")
        output = args.evidence.resolve()
        target = (ROOT / ".release-evidence/WB-CORRECTION-HISTORY-20261006").resolve()
        if output.parent != target or output.suffix != ".json" or output.exists():
            raise GateBlocked("invalid_evidence_target")
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        frozen = source_hashes()
        result = asyncio.run(run_gate(
            config["owner_url"], config["runtime_url"], config["supabase_url"],
            f"workbench_{uuid4().hex[:12]}", extra_migration=apply_0178,
            verifier=verify_history, required_checks=REQUIRED_CHECKS,
            scope="workbench_correction_history_isolated_dev", migration="0178",
            learner_history=True,
        ))
        result["source_sha256"] = frozen
        result["source_unchanged"] = frozen == source_hashes()
        if not result["source_unchanged"]:
            result.update(status="BLOCKED", failure="source_changed_during_gate", learner_history="NOT_VERIFIED")
        assert_sanitized_evidence(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "failure": sanitize_failure(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
