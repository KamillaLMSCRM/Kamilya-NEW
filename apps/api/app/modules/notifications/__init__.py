"""Tenant-scoped notification inbox projection."""

from .contracts import WorkflowNotificationIntentV1
from .service import materialize_notification

__all__ = ["WorkflowNotificationIntentV1", "materialize_notification"]
