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
                "enrolled_at": datetime(2026, 7, 21, 9, 5, tzinfo=UTC),
                "cycle_type": "course",
                "cycle_due_at": datetime(2026, 7, 28, 9, 5, tzinfo=UTC),
                "deadline_status": "overdue",
            }
        ]

    monkeypatch.setattr(service, "stream_training_log_csv", fake_batches)
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
    assert rows[0]["Email"].startswith("'=")
    assert rows[0]["Дата назначения"] == "21.07.2026 09:05"
    assert rows[0]["Тип цикла"] == "Курс"
    assert rows[0]["Срок"] == "28.07.2026 09:05"
    assert rows[0]["Статус срока"] == "Просрочено"
    assert "user_id" not in rows[0]
