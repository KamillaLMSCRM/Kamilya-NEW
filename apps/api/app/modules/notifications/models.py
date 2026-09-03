from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.db import Base


class NotificationInboxItem(Base):
    __tablename__ = "notification_inbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    recipient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_delivery_id = Column(UUID(as_uuid=True), ForeignKey("workflow_deliveries.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(40), nullable=False)
    context = Column(JSONB, nullable=False, default=dict, server_default="{}")
    action_path = Column(Text, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source_delivery_id", name="uq_notification_inbox_source_delivery"),
        CheckConstraint("kind IN ('course_review_assigned','course_review_reminder','course_review_overdue')", name="ck_notification_inbox_kind"),
        CheckConstraint(
            "jsonb_typeof(context) = 'object' "
            "AND context ? 'course_title' "
            "AND jsonb_typeof(context->'course_title') = 'string' "
            "AND length(context->>'course_title') BETWEEN 1 AND 500 "
            "AND context ? 'due_at' "
            "AND (context->'due_at' = 'null'::jsonb OR jsonb_typeof(context->'due_at') = 'string') "
            "AND context - ARRAY['course_title','due_at']::text[] = '{}'::jsonb",
            name="ck_notification_inbox_safe_context",
        ),
        CheckConstraint(
            "action_path ~ '^(/course-review-requests/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|/admin/course-approvals\\?courseId=[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$'",
            name="ck_notification_inbox_safe_action",
        ),
    )
