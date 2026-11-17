"""Large append-only custody stays exact without repeated archive reads."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.source_editorial_review import service


class Stream:
    def __init__(self, rows, error=None):
        self.rows = rows
        self.error = error
        self.close = AsyncMock()

    async def __aiter__(self):
        for row in self.rows:
            yield row
        if self.error:
            raise self.error


@pytest.mark.asyncio
@pytest.mark.parametrize('until', [None, 295])
async def test_history_stream_keeps_every_payload_in_order_and_closes_cursor(until):
    tenant, document = uuid4(), uuid4()
    rows = [SimpleNamespace(sequence=i, payload={'large': str(i) * 100_000}) for i in range(1, 296)]
    cursor = Stream(rows)
    db = SimpleNamespace(stream_scalars=AsyncMock(return_value=cursor), scalars=AsyncMock())
    assert await service.history(db, tenant, document, until) == rows
    db.scalars.assert_not_awaited()
    query, = db.stream_scalars.await_args.args
    assert query.get_execution_options()['yield_per'] == 8
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert str(tenant) in sql and str(document) in sql
    assert 'ORDER BY document_editorial_events.sequence' in sql
    assert ('document_editorial_events.sequence <= 295' in sql) is (until is not None)
    cursor.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_closes_cursor_and_does_not_return_partial_archive_on_disconnect():
    cursor = Stream([SimpleNamespace(sequence=1)], ConnectionError('synthetic disconnect'))
    db = SimpleNamespace(stream_scalars=AsyncMock(return_value=cursor))
    with pytest.raises(ConnectionError):
        await service.history(db, uuid4(), uuid4())
    cursor.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_ownership_head_fetches_only_current_metadata_in_owned_scope():
    tenant, document, event = uuid4(), uuid4(), uuid4()
    result = SimpleNamespace(one_or_none=lambda: (event, 296, 'analysis_block', 'claim'))
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    latest = await service.latest_event(db, tenant, document)
    assert (latest.id, latest.sequence, latest.kind, latest.payload) == (event, 296, 'analysis_block', {'claim_id': 'claim'})
    query, = db.execute.await_args.args
    sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={'literal_binds': True}))
    assert str(tenant) in sql and str(document) in sql and 'LIMIT 1' in sql
    assert 'ORDER BY document_editorial_events.sequence DESC' in sql
    # One extracted JSON string, never the full prepared source/custody payload.
    assert len(list(query.selected_columns)) == 4 and "->> 'claim_id'" in sql
    db.execute.return_value = SimpleNamespace(one_or_none=lambda: None)
    assert await service.latest_event(db, tenant, document) is None
