"""Canonical SQLAlchemy model registry used by Alembic and schema gates."""

from __future__ import annotations

from importlib import import_module

MODEL_MODULES = (
    "app.models.ai_job",
    "app.models.department",
    "app.models.document",
    "app.models.enrollment",
    "app.models.course_assignment_notification",
    "app.models.generated_content",
    "app.models.kiosk_link",
    "app.models.assignment_access",
    "app.models.progress",
    "app.models.staff_import_mapping",
    "app.models.tenant_llm_usage",
    "app.models.tenant_settings",
    "app.models.tenants",
    "app.models.user_roles",
    "app.models.user_sessions",
    "app.models.users",
    "app.modules.admin.provider_keys.models",
    "app.modules.announcements.models",
    "app.modules.audit.models",
    "app.modules.candidate_assessments.models",
    "app.modules.certificates.models",
    "app.modules.cohorts.models",
    "app.modules.competencies.models",
    "app.modules.courses.models",
    "app.modules.courses.release_models",
    "app.modules.integrations.models",
    "app.modules.learner_assistant.models",
    "app.modules.learning_paths.models",
    "app.modules.learning_cycles.models",
    "app.modules.lessons.models",
    "app.modules.positions.models",
    "app.modules.positions.qualification_models",
    "app.modules.quizzes.assignment_models",
    "app.modules.quizzes.models",
    "app.modules.scorm.models",
    "app.modules.surveys.models",
    "app.modules.training_rules.models",
    "app.modules.training_evidence.models",
    "app.modules.training_procedures.models",
    "app.modules.training_retention.models",
)


def load_all_models() -> None:
    """Import every module that contributes tables to the canonical Base."""

    for module_name in MODEL_MODULES:
        import_module(module_name)
