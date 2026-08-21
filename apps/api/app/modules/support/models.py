import uuid

from sqlalchemy import UUID, CheckConstraint, Column, DateTime, ForeignKey, Text, func

from app.core.db import Base


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    requester_email = Column(Text, nullable=True)
    requester_name = Column(Text, nullable=False)
    requester_role = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    subject = Column(Text, nullable=False)
    message = Column(Text, nullable=False)
    current_path = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="open", server_default="open")
    delivery_status = Column(Text, nullable=False, default="pending", server_default="pending")
    delivery_failure_category = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)

    __table_args__ = (
        CheckConstraint(
            "category IN ('access', 'technical', 'learning', 'staff', 'billing', 'other')",
            name="ck_support_requests_category",
        ),
        CheckConstraint("status IN ('open', 'closed')", name="ck_support_requests_status"),
        CheckConstraint(
            "delivery_status IN ('pending', 'sent', 'deferred', 'failed')",
            name="ck_support_requests_delivery_status",
        ),
    )
