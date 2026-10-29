import asyncio
import hashlib
import logging
import uuid
from types import SimpleNamespace

import pytest

from app.modules.ai import direct_source as m


def test_observer_preserves_timeout_and_redacts(caplog):
    err = TimeoutError("secret-source-private-url")

    async def boom():
        raise err

    with caplog.at_level(logging.WARNING):
        with pytest.raises(TimeoutError) as caught:
            asyncio.run(m._observe_timeout(boom(), "source_db_tenant"))
    assert caught.value is err and "source_db_tenant" in caplog.text and "secret-source-private-url" not in caplog.text


def test_observer_does_not_log_other_errors(caplog):
    err = ValueError("secret")

    async def boom():
        raise err

    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError) as caught:
            asyncio.run(m._observe_timeout(boom(), "storage_read"))
    assert caught.value is err and not caplog.records


def test_actual_storage_seam_timeout(caplog, monkeypatch):
    import app.modules.courses.source_uncertainty as scope

    monkeypatch.setattr(scope, "qa_source_holds_enabled", lambda tenant: False)
    err = TimeoutError("secret-url")

    class Storage:
        def get_bytes(self, key):
            raise err

    doc = SimpleNamespace(
        id="doc",
        tenant_id="tenant",
        lifecycle_status="active",
        content_sha256="a" * 64,
        s3_key="private",
        size=1,
        filename="a.pdf",
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(TimeoutError) as caught:
            asyncio.run(m.build_direct_source_corpus([doc], tenant_id="tenant", storage=Storage()))
    assert (
        type(caught.value) is TimeoutError
        and str(caught.value) == "secret-url"
        and "storage_read" in caplog.text
        and "secret-url" not in caplog.text
    )




def test_actual_converter_seam_preserves_cause(caplog, monkeypatch):
    import app.modules.courses.source_uncertainty as scope

    monkeypatch.setattr(scope, "qa_source_holds_enabled", lambda tenant: False)
    err = TimeoutError("secret-conversion-url")
    blob = b"content"

    class Storage:
        def get_bytes(self, key):
            return blob

    class Converter:
        async def convert(self, path, **kwargs):
            raise err

    doc = SimpleNamespace(
        id="doc",
        tenant_id="tenant",
        lifecycle_status="active",
        content_sha256=hashlib.sha256(blob).hexdigest(),
        s3_key="private",
        size=len(blob),
        filename="a.pdf",
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(m.DirectSourceError) as caught:
            asyncio.run(
                m.build_direct_source_corpus([doc], tenant_id="tenant", storage=Storage(), converter=Converter())
            )
    assert (
        caught.value.__cause__ is err
        and "source_converter" in caplog.text
        and "secret-conversion-url" not in caplog.text
    )


def test_actual_tenant_sql_seam_identity(caplog, monkeypatch):
    import app.core.db as db

    err = TimeoutError("secret-db-url")

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            raise err

    monkeypatch.setattr(db, "async_session_factory", lambda: Session())
    with caplog.at_level(logging.WARNING):
        with pytest.raises(TimeoutError) as caught:
            asyncio.run(m.load_direct_source_corpus([str(uuid.uuid4())], tenant_id=str(uuid.uuid4())))
    assert caught.value is err and "source_db_tenant" in caplog.text and "secret-db-url" not in caplog.text


def test_actual_document_select_timeout(caplog, monkeypatch):
    import app.core.db as db

    err = TimeoutError("private query text")

    class Session:
        calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def execute(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise err
            return None

    monkeypatch.setattr(db, "async_session_factory", lambda: Session())
    with caplog.at_level(logging.WARNING):
        with pytest.raises(TimeoutError) as caught:
            asyncio.run(m.load_direct_source_corpus([str(uuid.uuid4())], tenant_id=str(uuid.uuid4())))
    assert (
        caught.value is err and "source_db_document_select" in caplog.text and "private query text" not in caplog.text
    )


def test_observer_does_not_swallow_cancel(caplog):
    async def cancelled():
        raise asyncio.CancelledError()

    with caplog.at_level(logging.WARNING):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(m._observe_timeout(cancelled(), "storage_read"))
    assert not caplog.records


def load_copy(name):
    import importlib

    return importlib.import_module("app.modules.ai." + name)


def test_pipeline_actual_initial_owner_timeout(caplog, monkeypatch):
    mod = load_copy("pipeline")
    err = TimeoutError("private sql credentials")

    async def fail(*a, **k):
        raise err

    monkeypatch.setattr(mod, "uses_current_generation_engine", lambda x: True)
    monkeypatch.setattr(mod, "_check_generation_source_job", fail)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(mod.run_generation_pipeline("job", [], tenant_id=uuid.uuid4()))
    assert (
        result.status == "failed"
        and "initial_owner_check" in caplog.text
        and "private sql credentials" not in caplog.text
    )


def test_provider_reservation_timeout_not_post(caplog, monkeypatch):
    mod = load_copy("llm_client")
    err = TimeoutError("private reservation")

    class Reservation:
        async def before_post(self):
            raise err

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise AssertionError("POST must not run")

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: Client())
    token = mod._native_post_reservation.set(Reservation())
    cfg = SimpleNamespace(
        name="fake",
        timeout=10,
        connect_timeout=3,
        trust_env=False,
        base_url="https://invalid",
        endpoint="/chat",
        api_key="secret",
    )
    try:
        with caplog.at_level(logging.WARNING):
            with pytest.raises(TimeoutError) as caught:
                asyncio.run(mod._BaseProviderClient(cfg, max_retries=0)._request({}))
        assert (
            caught.value is err and "provider_http_post" not in caplog.text and "private reservation" not in caplog.text
        )
    finally:
        mod._native_post_reservation.reset(token)


def test_provider_actual_http_post_timeout(caplog, monkeypatch):
    mod = load_copy("llm_client")
    err = TimeoutError("private provider token")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise err

    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda **kw: Client())
    cfg = SimpleNamespace(
        name="fake",
        timeout=10,
        connect_timeout=3,
        trust_env=False,
        base_url="https://invalid",
        endpoint="/chat",
        api_key="secret",
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(TimeoutError) as caught:
            asyncio.run(mod._BaseProviderClient(cfg, max_retries=0)._request({}))
    assert caught.value is err and "provider_http_post" in caplog.text and "private provider token" not in caplog.text


def test_pipeline_actual_saving_progress_timeout_label(caplog, monkeypatch):
    mod = load_copy("pipeline")
    err = TimeoutError("private-db-at-save")

    async def noop(*args, **kwargs):
        return None

    async def source(*args, **kwargs):
        return object()

    async def update(*args, **kwargs):
        if kwargs.get("stage") == "saving":
            raise err
        return None

    monkeypatch.setattr(mod, "uses_current_generation_engine", lambda x: True)
    monkeypatch.setattr(mod, "_check_generation_source_job", noop)
    monkeypatch.setattr(mod, "_update_job_db", update)
    monkeypatch.setattr(mod, "load_direct_source_corpus", source)
    monkeypatch.setattr(mod, "_run_evidence_v2_generation", noop)
    monkeypatch.setattr(mod, "_check_cancelled_async", noop)
    monkeypatch.setattr(mod, "_release_generation_reservation", noop)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(mod.run_generation_pipeline("job", [], tenant_id=uuid.uuid4()))
    assert result.status == "failed" and "saving_progress_db" in caplog.text and "private-db-at-save" not in caplog.text


def test_concurrent_authorized_jobs_correlate_and_reset(caplog, monkeypatch):
    mod = load_copy("pipeline")
    from app.modules.ai import timeout_context

    a, b = str(uuid.uuid4()), str(uuid.uuid4())

    async def check(*args, **kwargs):
        await asyncio.sleep(0)

    async def update(*args, **kwargs):
        await asyncio.sleep(0)
        raise TimeoutError("private")

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(mod, "uses_current_generation_engine", lambda x: True)
    monkeypatch.setattr(mod, "_check_generation_source_job", check)
    monkeypatch.setattr(mod, "_update_job_db", update)
    monkeypatch.setattr(mod, "_release_generation_reservation", noop)

    async def go():
        return await asyncio.gather(*(mod.run_generation_pipeline(j, [], tenant_id=uuid.uuid4()) for j in (a, b)))

    with caplog.at_level(logging.WARNING):
        asyncio.run(go())
    labels = [r.getMessage() for r in caplog.records if "generation_timeout_boundary" in r.getMessage()]
    assert len(labels) == 2 and all("stage=job_state_db" in x for x in labels)
    assert sum("job_id=" + a in x for x in labels) == 1 and sum("job_id=" + b in x for x in labels) == 1
    assert all("private" not in x for x in labels) and timeout_context.job_id.get() is None


def test_failed_authorization_does_not_attach_job_id(caplog, monkeypatch):
    mod = load_copy("pipeline")
    job = str(uuid.uuid4())

    async def fail(*args, **kwargs):
        raise TimeoutError("private")

    monkeypatch.setattr(mod, "uses_current_generation_engine", lambda x: True)
    monkeypatch.setattr(mod, "_check_generation_source_job", fail)
    with caplog.at_level(logging.WARNING):
        asyncio.run(mod.run_generation_pipeline(job, [], tenant_id=uuid.uuid4()))
    labels = [r.getMessage() for r in caplog.records if "generation_timeout_boundary" in r.getMessage()]
    assert len(labels) == 1 and "job_id=" not in labels[0] and job not in labels[0]


def test_pipeline_public_signature_unchanged():
    import inspect

    mod = load_copy("pipeline")
    signature = inspect.signature(mod.run_generation_pipeline)
    assert tuple(signature.parameters) == (
        "job_id",
        "documents",
        "target_audience",
        "num_modules",
        "lessons_per_module",
        "max_total_lessons",
        "language",
        "goals",
        "course_hours",
        "guidance",
        "course_id",
        "tenant_id",
        "user_id",
        "source_strategy",
        "combination_goal",
        "source_analysis",
        "reuse_reason",
    )
    assert inspect.iscoroutinefunction(mod.run_generation_pipeline)


def test_pipeline_cancellation_after_ownership_resets_context(caplog, monkeypatch):
    mod = load_copy("pipeline")
    from app.modules.ai import timeout_context

    async def check(*args, **kwargs):
        return None

    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(mod, "uses_current_generation_engine", lambda x: True)
    monkeypatch.setattr(mod, "_check_generation_source_job", check)
    monkeypatch.setattr(mod, "_update_job_db", cancel)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(mod.run_generation_pipeline(str(uuid.uuid4()), [], tenant_id=uuid.uuid4()))
    assert timeout_context.job_id.get() is None and not [
        r for r in caplog.records if "generation_timeout_boundary" in r.getMessage()
    ]
