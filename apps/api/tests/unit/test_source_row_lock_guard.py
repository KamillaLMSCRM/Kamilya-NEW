from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.source_editorial_review.service import owned_document


@pytest.mark.asyncio
@pytest.mark.parametrize('lock', [False, True])
async def test_only_source_row_lock_transactions_install_idle_cleanup_before_select(lock):
    calls = []
    doc = object()

    async def execute(statement):
        calls.append(('guard', str(statement)))

    async def scalar(statement):
        calls.append(('select', str(statement)))
        return doc

    db = SimpleNamespace(execute=AsyncMock(side_effect=execute), scalar=AsyncMock(side_effect=scalar))
    assert await owned_document(db, uuid4(), uuid4(), lock=lock) is doc
    if lock:
        assert len(calls) == 2 and calls[0] == ('guard', "SET LOCAL idle_in_transaction_session_timeout = '60s'")
        assert calls[1][0] == 'select' and 'FOR UPDATE' in calls[1][1]
    else:
        db.execute.assert_not_awaited()
        assert len(calls) == 1 and 'FOR UPDATE' not in calls[0][1]
