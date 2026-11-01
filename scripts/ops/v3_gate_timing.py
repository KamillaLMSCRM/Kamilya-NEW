"""Bounded aggregate timing for the synthetic checkpoint gate; no SQL or payloads."""

from collections import Counter
from time import monotonic
from sqlalchemy import text


class GateTiming:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.started = clock()
        self.previous = self.started
        self.operations = Counter()
        self.events = Counter()

    def operation(self, name):
        if name not in {"prepare", "save_value", "read_owned_value"}:
            raise ValueError("unknown_operation")
        self.operations[name] += 1

    def event(self, name):
        if name not in {"connect", "checkout", "reset", "statement"}:
            raise ValueError("unknown_event")
        self.events[name] += 1

    def checkpoint(self, name):
        if not isinstance(name, str) or not name.isidentifier() or len(name) > 100:
            raise ValueError("invalid_checkpoint")
        now = self.clock()
        result = {
            "checkpoint": name,
            "elapsed_seconds": round(now - self.started, 3),
            "since_previous_seconds": round(now - self.previous, 3),
            "journal_operations_partial": dict(self.operations),
            "db_events_owner_and_runtime_aggregate": dict(self.events),
            "pool_reset_scope_if_enabled": "one_reused_backend_only",
        }
        self.previous = now
        return result


def instrument_engine(engine, timing, event_api):
    """Pool + SQL event counts only; no connection URLs or SQL text retained."""
    for name in ("connect", "checkout", "reset"):

        def callback(*_args, _name=name):
            timing.event(_name)

        event_api.listen(engine.sync_engine.pool, name, callback)

    def before_cursor_execute(*_args):
        timing.event("statement")

    event_api.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    return engine


def measured_journal(base, timing):
    class MeasuredJournal(base):
        async def prepare(self, *args, **kwargs):
            timing.operation("prepare")
            return await super().prepare(*args, **kwargs)

        async def save_value(self, *args, **kwargs):
            timing.operation("save_value")
            return await super().save_value(*args, **kwargs)

        async def read_owned_value(self, *args, **kwargs):
            timing.operation("read_owned_value")
            return await super().read_owned_value(*args, **kwargs)

    return MeasuredJournal


async def verify_pool_reset(session_factory, tenant_a, tenant_b, expected_schema):
    """Require actual same-backend reuse with no transaction-local tenant leak."""
    async with session_factory() as first:
        pid = await first.scalar(text("SELECT pg_backend_pid()"))
        await first.execute(
            text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_a)}
        )
        await first.commit()
    async with session_factory() as second:
        reused_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        if reused_pid != pid:
            raise ValueError("pool_reuse_not_observed")
        if await second.scalar(text("SELECT current_schema()")) != expected_schema:
            raise ValueError("pool_schema_context_changed")
        tenant = await second.scalar(
            text("SELECT nullif(current_setting('app.tenant_id',true),'')")
        )
        if tenant is not None:
            raise ValueError("pool_tenant_context_leaked")
        await second.execute(
            text("SELECT set_current_tenant(:tenant)"), {"tenant": str(tenant_b)}
        )
        visible = await second.scalar(
            text("SELECT count(*) FROM ai_jobs WHERE tenant_id=:tenant"),
            {"tenant": tenant_a},
        )
        if visible != 0:
            raise ValueError("pool_foreign_tenant_visible")
        await second.rollback()
    async with session_factory() as third:
        if await third.scalar(text("SELECT pg_backend_pid()")) != pid:
            raise ValueError("pool_reuse_not_observed")
        tenant = await third.scalar(
            text("SELECT nullif(current_setting('app.tenant_id',true),'')")
        )
        if tenant is not None:
            raise ValueError("pool_tenant_context_leaked")
