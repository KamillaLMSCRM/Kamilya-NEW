"""Training log service — thin layer between router and repository.

Per AGENTS.md architecture:
- Repository → typed SQL
- Service → business logic / validation
- Router → HTTP envelope

For training-log the service layer mostly validates filters (e.g. max
limit) and prepares CSV output. Heavy lifting is in repository.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.training_log.repository import (
    count_training_log,
    list_training_log,
    stream_training_log_csv,
)
from app.modules.training_log.schemas import (
    TrainingLogFilter,
    TrainingLogPage,
    TrainingLogRow,
)

logger = logging.getLogger(__name__)

# Hard caps so an attacker can't request limit=10_000_000
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


def validate_pagination(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1:
        limit = 1
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


async def get_training_log_page(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> TrainingLogPage:
    limit, offset = validate_pagination(limit, offset)
    rows = await list_training_log(db, tenant_id, f, limit=limit, offset=offset)
    total = await count_training_log(db, tenant_id, f)
    items = [TrainingLogRow.model_validate(r) for r in rows]
    return TrainingLogPage(items=items, total=total, limit=limit, offset=offset)


async def stream_training_log_as_csv(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter,
) -> AsyncIterator[bytes]:
    """Yield CSV chunks (UTF-8 BOM + header + rows in batches)."""
    # UTF-8 BOM so Excel opens it as UTF-8 by default.
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL)
    fields = [
        "user_id",
        "full_name",
        "email",
        "personnel_number",
        "department_id",
        "department_name",
        "position_id",
        "position_name",
        "course_id",
        "course_title",
        "delivery_type",
        "enrollment_status",
        "enrollment_source",
        "enrolled_at",
        "completed_at",
        "progress_percent",
        "best_score",
        "quiz_attempts_count",
        "certificate_id",
        "certificate_number",
        "certificate_issued_at",
        "kiosk_last_seen_at",
    ]
    writer.writerow(fields)
    yield b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate()

    async for batch in stream_training_log_csv(db, tenant_id, f, batch_size=500):
        for r in batch:
            writer.writerow([r.get(f) if r.get(f) is not None else "" for f in fields])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()