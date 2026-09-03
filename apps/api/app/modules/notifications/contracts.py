"""Public, secret-free notification contracts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

NotificationKind = Literal["course_review_assigned", "course_review_reminder", "course_review_overdue"]


@dataclass(frozen=True, slots=True)
class WorkflowNotificationIntentV1:
    tenant_id: UUID
    recipient_user_id: UUID
    source_delivery_id: UUID
    kind: NotificationKind
    course_title: str
    due_at: datetime | None
    action_path: str
