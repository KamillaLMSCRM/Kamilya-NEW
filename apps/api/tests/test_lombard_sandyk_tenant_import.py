from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "tenant_migrations" / "import_lombard_sandyk.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("import_lombard_sandyk", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_course_package_requires_exactly_two_courses(tmp_path: Path) -> None:
    module = _load_script_module()
    path = tmp_path / "package.json"
    path.write_text(
        json.dumps({"schema_version": 1, "courses": [{"snapshot": {}}]}),
        encoding="utf-8",
    )

    try:
        module._load_package(path)
    except ValueError as exc:
        assert "exactly two courses" in str(exc)
    else:
        raise AssertionError("invalid package was accepted")


def test_course_kinds_cover_rules_and_job_instruction() -> None:
    module = _load_script_module()

    assert module._course_kind("Правила предоставления микрокредитов") == "microcredit_rules"
    assert (
        module._course_kind("Вводный курс для эксперта-оценщика")
        == "expert_appraiser_instruction"
    )


def test_import_scope_excludes_historical_results_and_credentials() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    for forbidden_model in (
        "QuizAttempt(",
        "Certificate(",
        "TrainingEvidenceEvent(",
        "Enrollment(",
        "UserInvitation(",
        "AssignmentAccessCredential(",
    ):
        assert forbidden_model not in source
    assert 'role="student"' not in source  # learner creation stays in the canonical staff-import service
    assert "commit_changes=False" in source
    assert "apply_rules=False" in source
    assert source.count("await db.commit()") == 1
    assert "pg_advisory_xact_lock" in source
    assert "source_document_ids=mapped_course_document_ids" in source
    assert '"document_links_pending": False' in source
    assert "if counts != EXPECTED_COUNTS" in source
    assert "document_id = uuid5(tenant_id" in source
    assert '"source_document_id"' in source
    assert '"target_document_id"' in source
    assert '"rollback_storage_cleanup_required"' in source


def test_expected_initial_tenant_counts_are_explicit() -> None:
    module = _load_script_module()

    assert module.EXPECTED_COUNTS == {
        "users": 13,
        "students": 12,
        "departments": 2,
        "positions": 4,
        "documents": 2,
        "courses": 2,
        "content_releases": 2,
        "modules": 7,
        "lessons": 18,
        "content_blocks": 0,
        "quizzes": 18,
        "questions": 78,
        "quiz_choices": 312,
        "position_course_rules": 6,
        "enrollments": 22,
    }
