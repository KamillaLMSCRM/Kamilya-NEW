from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _release_gate():
    path = REPO_ROOT / "scripts" / "ci" / "release-contract-gate.py"
    spec = importlib.util.spec_from_file_location("release_contract_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_registry_populates_canonical_metadata():
    from app.core.db import Base
    from app.models.registry import MODEL_MODULES, load_all_models

    load_all_models()

    model_modules = set()
    for path in (REPO_ROOT / "apps" / "api" / "app").rglob("*.py"):
        if "__tablename__" not in path.read_text(encoding="utf-8"):
            continue
        module_path = path.relative_to(REPO_ROOT / "apps" / "api").with_suffix("")
        model_modules.add(".".join(module_path.parts))

    assert set(MODEL_MODULES) == model_modules

    expected = {
        "ai_jobs",
        "courses",
        "departments",
        "documents",
        "enrollments",
        "lessons",
        "modules",
        "quizzes",
        "scorm_packages",
        "tenants",
        "users",
    }
    assert expected <= set(Base.metadata.tables)


def test_release_contract_has_one_migration_owner_and_all_worker_tasks():
    gate = _release_gate()

    assert "migration ownership OK" in gate.check_migration_owner()
    celery_result = gate.check_celery_contract()
    assert "ai.regenerate_lesson" in celery_result
    assert "ai.regenerate_module" in celery_result
    assert "errors journal OK" in gate.check_errors_journal()
