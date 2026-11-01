"""Server-only fresh QA admission and worker policy for the existing V3 engine."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.modules.ai.qa_luna_dev_route import QA_TENANT

KEY = "qa_luna_pending_journal_policy"
POLICY = "qa-luna-pending-journal-v1"


def admission_marker(*, settings: Any, tenant_id: UUID, user_id: UUID, course_id: Any,
                     source_first: bool) -> str | None:
    if tenant_id != QA_TENANT:
        return None
    enabled = getattr(settings, "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED", False)
    if enabled is False:
        return None
    if (enabled is not True or getattr(settings, "DEPLOYMENT_ENVIRONMENT", None) != "render-development"
            or getattr(settings, "AI_QA_LUNA_DEV_ENABLED", False) is not True
            or source_first or course_id is not None or not isinstance(user_id, UUID)):
        raise ValueError("qa_luna_pending_admission_unavailable")
    return POLICY


def check_worker_marker(*, settings: Any, tenant_id: UUID, user_id: UUID | None,
                        stored: Any, dispatched: Any, course_id: Any) -> bool:
    if stored is None and dispatched is None:
        return False
    if (stored != POLICY or dispatched != POLICY or tenant_id != QA_TENANT or not isinstance(user_id, UUID)
            or course_id is not None or getattr(settings, "AI_QA_LUNA_PENDING_JOURNAL_DEV_ENABLED", False) is not True
            or getattr(settings, "AI_QA_LUNA_DEV_ENABLED", False) is not True
            or getattr(settings, "DEPLOYMENT_ENVIRONMENT", None)
            not in {"render-development-worker", "vm-development-worker"}):
        raise ValueError("qa_luna_pending_worker_unavailable")
    return True
