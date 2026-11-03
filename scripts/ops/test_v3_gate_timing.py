import asyncio
from types import SimpleNamespace

import pytest

from v3_gate_timing import (
    GateTiming,
    instrument_engine,
    measured_journal,
    verify_pool_reset,
)


def test_aggregate_events_and_stage_timing_do_not_include_sensitive_arguments():
    samples = iter([1.0, 3.5, 7.0])
    timing = GateTiming(clock=lambda: next(samples))
    timing.operation("prepare")
    timing.event("connect")
    first = timing.checkpoint("first_step")
    timing.event("statement")
    second = timing.checkpoint("second_step")
    assert first["since_previous_seconds"] == 2.5 and first["db_events_owner_and_runtime_aggregate"] == {
        "connect": 1
    }
    assert second["since_previous_seconds"] == 3.5 and second["elapsed_seconds"] == 6.0
    assert second["journal_operations_partial"] == {"prepare": 1}
    assert second["pool_reset_scope_if_enabled"] == "one_reused_backend_only"
    with pytest.raises(ValueError):
        timing.checkpoint("raw sql or secret")


def test_engine_listeners_count_only_event_names():
    listeners = {}
    event_api = SimpleNamespace(
        listen=lambda target, event, callback: listeners.update({event: callback})
    )
    timing = GateTiming()
    engine = SimpleNamespace(sync_engine=SimpleNamespace(pool=object()))
    assert instrument_engine(engine, timing, event_api) is engine
    for callback in listeners.values():
        callback("secret SQL", "secret credentials")
    assert dict(timing.events) == {
        "connect": 1,
        "checkout": 1,
        "reset": 1,
        "statement": 1,
    }


def test_journal_wrapper_counts_real_methods_without_storing_arguments():
    class Journal:
        async def prepare(self, *_args):
            return "prepared"

        async def save_value(self, *_args):
            return None

        async def read_owned_value(self, *_args):
            return {"value": "private"}

    async def exercise():
        timing = GateTiming()
        journal = measured_journal(Journal, timing)()
        assert await journal.prepare("private") == "prepared"
        await journal.save_value("secret")
        await journal.read_owned_value("secret")
        assert dict(timing.operations) == {
            "prepare": 1,
            "save_value": 1,
            "read_owned_value": 1,
        }

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "pid,schema,tenant,visible,expected",
    [
        (7, "owned", None, 0, None),
        (8, "owned", None, 0, "pool_reuse_not_observed"),
        (7, "public", None, 0, "pool_schema_context_changed"),
        (7, "owned", "leaked", 0, "pool_tenant_context_leaked"),
        (7, "owned", None, 1, "pool_foreign_tenant_visible"),
    ],
)
def test_pool_reset_checks_same_backend_empty_context_and_foreign_isolation(
    pid, schema, tenant, visible, expected
):
    class Session:
        def __init__(self, first):
            self.first = first

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def scalar(self, statement, *_args):
            sql = str(statement)
            if "pg_backend_pid" in sql:
                return 7 if self.first else pid
            if "current_schema" in sql:
                return schema
            if "current_setting" in sql:
                return tenant
            return visible

        async def execute(self, *_args):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

    iterator = iter([Session(True), Session(False), Session(False)])
    if expected:
        with pytest.raises(ValueError, match=expected):
            asyncio.run(
                verify_pool_reset(
                    lambda: next(iterator), "tenant-a", "tenant-b", "owned"
                )
            )
    else:
        asyncio.run(
            verify_pool_reset(lambda: next(iterator), "tenant-a", "tenant-b", "owned")
        )
