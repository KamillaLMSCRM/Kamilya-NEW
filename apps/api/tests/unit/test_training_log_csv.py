import csv
import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.modules.training_log import service
from app.modules.training_log.schemas import TrainingLogFilter


@pytest.mark.asyncio
async def test_training_log_csv_is_excel_compatible(monkeypatch):
    async def fake_batches(*args, **kwargs):
        yield [
            {
                "full_name": "Иванов; Иван",
                "email": '=HYPERLINK("https://example.invalid")',
                "course_title": "Охрана труда, вводный курс",
                "computed_status": "in_progress",
                "requirement_state": "protected_assignment",
                "action_required": "none",
                "assignment_reason_kind": "manual",
                "assignment_reason_source_name": None,
                "assignment_reason_code": "mandatory_training.reason.manual",
                "enrolled_at": datetime(2026, 7, 21, 9, 5, tzinfo=UTC),
                "cycle_type": "course",
                "cycle_due_at": datetime(2026, 7, 28, 9, 5, tzinfo=UTC),
                "deadline_status": "overdue",
                "assignment_due_at": datetime(2026, 7, 22, 9, 5, tzinfo=UTC),
                "deadline_state": "upcoming",
                "certificate_status": "expiring",
            }
        ]

    monkeypatch.setattr(service, "stream_training_log_csv", fake_batches)
    monkeypatch.setattr(
        service,
        "enrich_training_log_rows",
        lambda _db, _tenant_id, rows: _identity_rows(rows),
    )
    chunks = [
        chunk
        async for chunk in service.stream_training_log_as_csv(
            db=object(),
            tenant_id=uuid4(),
            f=TrainingLogFilter(),
        )
    ]

    content = b"".join(chunks)
    assert content.startswith(b"\xef\xbb\xbf")

    text = content.decode("utf-8-sig")
    header = text.splitlines()[0]
    assert ";" in header
    assert len(next(csv.reader([header], delimiter=";"))) == len(service.CSV_COLUMNS["ru"])

    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert rows[0]["ФИО"] == "Иванов; Иван"
    assert rows[0]["Курс"] == "Охрана труда, вводный курс"
    assert rows[0]["Статус"] == "В процессе"
    assert rows[0]["Состояние требования"] == "Защищённое назначение"
    assert rows[0]["Основание назначения"] == "Вручную"
    assert rows[0]["Код основания"] == "mandatory_training.reason.manual"
    assert rows[0]["Email"].startswith("'=")
    assert rows[0]["Дата назначения"] == "21.07.2026 09:05"
    assert rows[0]["Тип цикла"] == "Курс"
    assert rows[0]["Срок"] == "28.07.2026 09:05"
    assert rows[0]["Статус срока"] == "Просрочено"
    assert rows[0]["Срок назначения"] == "22.07.2026 09:05"
    assert rows[0]["Состояние срока"] == "Ожидается"
    assert rows[0]["Статус сертификата"] == "Истекает"
    assert "user_id" not in rows[0]


async def _identity_rows(rows):
    return rows
