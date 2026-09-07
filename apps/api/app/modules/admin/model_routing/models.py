"""Singleton persistence model for the global generation route."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, SmallInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class GenerationModelRouting(Base):
    __tablename__ = "generation_model_routing"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_generation_model_routing_singleton"),
        CheckConstraint("revision >= 1", name="ck_generation_model_routing_revision"),
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    ordered_model_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default="now()",
        onupdate=lambda: datetime.now(UTC),
    )
