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
from datetime import date, datetime
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
    TrainingLogSummary,
)

logger = logging.getLogger(__name__)

# Hard caps so an attacker can't request limit=10_000_000
MAX_LIMIT = 500
DEFAULT_LIMIT = 100

CSV_COLUMNS = {
    "ru": [
        ("full_name", "ФИО"), ("email", "Email"), ("personnel_number", "Табельный номер"),
        ("department_name", "Подразделение"), ("position_name", "Должность"),
        ("course_title", "Курс"), ("delivery_type", "Формат курса"),
        ("computed_status", "Статус"), ("enrollment_source", "Источник назначения"),
        ("enrolled_at", "Дата назначения"), ("completed_at", "Дата завершения"),
        ("progress_percent", "Прогресс, %"), ("best_score", "Лучший результат, %"),
        ("quiz_attempts_count", "Попыток теста"), ("certificate_number", "Номер сертификата"),
        ("certificate_issued_at", "Дата выдачи сертификата"),
    ],
    "kk": [
        ("full_name", "Аты-жөні"), ("email", "Email"), ("personnel_number", "Табельдік нөмір"),
        ("department_name", "Бөлімше"), ("position_name", "Лауазым"),
        ("course_title", "Курс"), ("delivery_type", "Курс форматы"),
        ("computed_status", "Мәртебе"), ("enrollment_source", "Тағайындау көзі"),
        ("enrolled_at", "Тағайындалған күні"), ("completed_at", "Аяқталған күні"),
        ("progress_percent", "Прогресс, %"), ("best_score", "Үздік нәтиже, %"),
        ("quiz_attempts_count", "Тест әрекеттері"), ("certificate_number", "Сертификат нөмірі"),
        ("certificate_issued_at", "Сертификат берілген күн"),
    ],
    "en": [
        ("full_name", "Full name"), ("email", "Email"), ("personnel_number", "Personnel number"),
        ("department_name", "Department"), ("position_name", "Position"),
        ("course_title", "Course"), ("delivery_type", "Course format"),
        ("computed_status", "Status"), ("enrollment_source", "Assignment source"),
        ("enrolled_at", "Assigned at"), ("completed_at", "Completed at"),
        ("progress_percent", "Progress, %"), ("best_score", "Best score, %"),
        ("quiz_attempts_count", "Quiz attempts"), ("certificate_number", "Certificate number"),
        ("certificate_issued_at", "Certificate issued at"),
    ],
}

CSV_VALUE_LABELS = {
    "ru": {
        "assigned": "Назначен", "in_progress": "В процессе", "completed": "Завершён",
        "native": "Курс Kamilya LMS", "scorm": "SCORM 1.2", "manual": "Вручную",
        "position": "По должности", "department": "По подразделению", "cohort": "По группе",
        "auto": "Автоматически", "instruction_replace": "По должностной инструкции",
    },
    "kk": {
        "assigned": "Тағайындалды", "in_progress": "Орындалуда", "completed": "Аяқталды",
        "native": "Kamilya LMS курсы", "scorm": "SCORM 1.2", "manual": "Қолмен",
        "position": "Лауазым бойынша", "department": "Бөлімше бойынша", "cohort": "Топ бойынша",
        "auto": "Автоматты түрде", "instruction_replace": "Лауазымдық нұсқаулық бойынша",
    },
    "en": {
        "assigned": "Assigned", "in_progress": "In progress", "completed": "Completed",
        "native": "Kamilya LMS course", "scorm": "SCORM 1.2", "manual": "Manual",
        "position": "By position", "department": "By department", "cohort": "By cohort",
        "auto": "Automatic", "instruction_replace": "By job instruction",
    },
}


def _csv_value(field: str, value, lang: str):
    if value is None:
        return ""
    if field in {"delivery_type", "computed_status", "enrollment_source"}:
        return CSV_VALUE_LABELS[lang].get(str(value), value)
    if field in {"enrolled_at", "completed_at", "certificate_issued_at"}:
        if isinstance(value, (datetime, date)):
            return value.strftime("%d.%m.%Y %H:%M" if isinstance(value, datetime) else "%d.%m.%Y")
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            return value
    # Prevent spreadsheet formula injection from names/course titles imported
    # from tenant-controlled files. Excel treats these prefixes as formulas.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


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
    lang: str = "ru",
) -> AsyncIterator[bytes]:
    """Yield a human-readable Excel-compatible CSV in the selected UI language."""
    # UTF-8 BOM so Excel opens it as UTF-8 by default.
    buf = io.StringIO()
    # Kazakhstan/Russian Excel installations use semicolon as the CSV field
    # separator because comma is the locale decimal separator. A comma-delimited
    # file opens as one unreadable column even when its UTF-8 encoding is valid.
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    lang = lang if lang in CSV_COLUMNS else "ru"
    columns = CSV_COLUMNS[lang]
    writer.writerow([label for _, label in columns])
    yield b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate()

    async for batch in stream_training_log_csv(db, tenant_id, f, batch_size=500):
        for r in batch:
            writer.writerow([_csv_value(field, r.get(field), lang) for field, _ in columns])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()


async def get_training_log_summary(
    db: AsyncSession,
    tenant_id: UUID,
    f: TrainingLogFilter | None = None,
) -> TrainingLogSummary:
    """Return status counts using the same repository status semantics as the table."""
    f = f or TrainingLogFilter()
    assigned = await count_training_log(db, tenant_id, f.model_copy(update={"status": "assigned"}))
    in_progress = await count_training_log(db, tenant_id, f.model_copy(update={"status": "in_progress"}))
    completed = await count_training_log(db, tenant_id, f.model_copy(update={"status": "completed"}))
    return TrainingLogSummary(
        total=assigned + in_progress + completed,
        assigned=assigned,
        in_progress=in_progress,
        completed=completed,
    )
