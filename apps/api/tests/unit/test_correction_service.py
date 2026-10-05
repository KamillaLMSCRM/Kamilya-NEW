"""Database-free admission and replay contracts for lesson correction previews."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.modules.editor_assistant.patch_contract import ProviderProvenance
from app.modules.methodologist_workbench import correction_service as service
from app.modules.methodologist_workbench.correction_contract import (
    LessonCorrectionContext,
    LessonCorrectionSnapshot,
)
from app.modules.methodologist_workbench.correction_schemas import (
    CorrectionPreviewRequest,
    CorrectionProposal,
)
from app.modules.methodologist_workbench.plan_contract import ActorContext

NOW = datetime(2026, 10, 5, 8, tzinfo=UTC)
TENANT, ACTOR, COURSE, MODULE, LESSON, DOCUMENT = [UUID(int=index) for index in range(1, 7)]
BEFORE = "Article A100 is a steel cabinet with roller guides 450 mm long."
AFTER = "Article A100 is a steel cabinet equipped with roller guides that are 450 mm long."
SOURCE = "Article A100\nGuides: roller, length 450 mm.\nBody: steel."


def request(*, key: UUID | None = None, instruction: str = "Clarify the lesson.") -> CorrectionPreviewRequest:
    return CorrectionPreviewRequest(request_key=key or uuid4(), lesson_id=LESSON, instruction=instruction, locale="en")


def context(*, content: str = BEFORE) -> LessonCorrectionContext:
    from hashlib import sha256

    citation_hash = sha256(SOURCE.encode()).hexdigest()
    return LessonCorrectionContext(
        tenant_id=TENANT,
        course_id=COURSE,
        module_id=MODULE,
        lesson_id=LESSON,
        course_version="course-v4",
        lesson_version="lesson-v2",
        lifecycle="draft",
        content=content,
        sources=(
            {
                "document_id": DOCUMENT,
                "version": 2,
                "content_sha256": "a" * 64,
                "index_revision": 3,
                "evidence": [{"locator": "fact:article-a100", "evidence_hash": citation_hash}],
            },
        ),
    )


def resolved(*, content: str = BEFORE):
    from hashlib import sha256

    from app.modules.methodologist_workbench.correction_proposal import CorrectionExcerpt
    from app.modules.methodologist_workbench.correction_schemas import CorrectionCitation

    citation = CorrectionCitation(
        document_id=DOCUMENT, locator="fact:article-a100", evidence_hash=sha256(SOURCE.encode()).hexdigest()
    )
    return SimpleNamespace(
        context=context(content=content), title="Cabinet guides", excerpts=(CorrectionExcerpt(citation, SOURCE),)
    )


def proposal() -> CorrectionProposal:
    from hashlib import sha256

    from app.modules.methodologist_workbench.correction_schemas import CorrectionCitation

    return CorrectionProposal(
        content=AFTER,
        citations=(
            CorrectionCitation(
                document_id=DOCUMENT, locator="fact:article-a100", evidence_hash=sha256(SOURCE.encode()).hexdigest()
            ),
        ),
        provenance=ProviderProvenance(
            "fake.test", "fake-correction-v1", "lesson-correction-v1", "correction-preview-v1"
        ),
        quality_policy="lesson-quality-v20",
    )


class Result:
    def __init__(self, value=None, row=None):
        self.value = value
        self.row = row

    def scalar_one_or_none(self):
        return self.value

    def fetchone(self):
        return self.row

    def scalar(self):
        return self.value


class Storage:
    """Small SQL-aware fake: inserts/updates are driven by SQLAlchemy statement values."""

    def __init__(self, *, budget: int | None = 100, rows=None, conflict_row=None):
        self.budget = budget
        self.rows = {} if rows is None else {row.id: row for row in rows}
        self.conflict_row = conflict_row
        self.live_actor = True
        self.commits = 0
        self.rollbacks = 0
        self.statements = []
        self.accounting_rows = {}
        self.accounting_commit_states = []
        self.budget_statements = []
        self.events = []
        self.db_clock = None
        self.fail_commit_number = None

    async def scalar(self, statement):
        text = str(statement)
        if "clock_timestamp" in text:
            return self.db_clock or service.datetime.now(UTC)
        if "monthly_llm_budget_usd_cents" in text:
            return self.budget
        if "workbench_lesson_correction_accounting" in text:
            plan_id = next((plan_id for plan_id in self.accounting_rows if str(plan_id) in text), None)
            return self.accounting_rows.get(plan_id) or next(iter(self.accounting_rows.values()), None)
        if "workbench_lesson_correction_plans" in text:
            return next(iter(self.rows.values()), None)
        if "users" in text:
            return ACTOR if self.live_actor else None
        return None

    async def execute(self, statement, parameters=None):
        self.statements.append(statement)
        table = getattr(getattr(statement, "table", None), "name", None)
        text = str(statement)
        if "tenant_llm_usage" in text:
            params = dict(parameters or getattr(statement, "params", {}) or {})
            bindparams = getattr(statement, "_bindparams", {})
            params.update({name: bind.value for name, bind in bindparams.items() if name not in params})
            self.budget_statements.append((text, params))
            if text.lstrip().upper().startswith("INSERT"):
                return Result(value=10, row=(10, 1))
            return Result(0)
        if table == "tenants" or "FROM tenants" in text:
            return Result(ACTOR)
        if getattr(statement, "is_insert", False):
            if self.conflict_row is not None:
                self.rows[self.conflict_row.id] = self.conflict_row
                self.conflict_row = None
                return Result(None)
            values = {
                getattr(key, "name", str(key).rsplit(".", 1)[-1]): getattr(value, "value", value)
                for key, value in statement._values.items()
            }
            row = SimpleNamespace(**values, proposal=None, fingerprint=None, error_code=None, finished_at=None)
            if table == "workbench_lesson_correction_accounting":
                self.accounting_rows[row.plan_id] = row
                return Result(row.plan_id)
            else:
                self.rows[row.id] = row
            return Result(row.id)
        if getattr(statement, "is_update", False):
            values = {
                getattr(key, "name", str(key).rsplit(".", 1)[-1]): getattr(value, "value", value)
                for key, value in statement._values.items()
            }
            target = self.accounting_rows if table == "workbench_lesson_correction_accounting" else self.rows
            row_id = next((value for value in target if str(value) in str(statement)), None)
            if row_id is None and target:
                row_id = next(reversed(target))
            if row_id is not None:
                for key, value in values.items():
                    setattr(target[row_id], key.rsplit(".", 1)[-1], value)
                if table == "workbench_lesson_correction_accounting" and values.get("state") == "started":
                    target[row_id].provider_boundary_at = self.db_clock or service.datetime.now(UTC)
                if table == "workbench_lesson_correction_accounting":
                    return Result(value=getattr(target[row_id], "state", None))
            return Result()
        return Result()

    async def commit(self):
        self.commits += 1
        self.events.append("commit")
        self.accounting_commit_states.append(
            tuple(
                (row.plan_id, row.state, row.tenant_id, row.actor_id, row.month_key, row.estimated_cost_cents)
                for row in self.accounting_rows.values()
            )
        )
        if self.fail_commit_number == self.commits:
            raise SQLAlchemyError("commit acknowledgement unavailable")

    async def rollback(self):
        self.rollbacks += 1
        self.events.append("rollback")


def actor() -> ActorContext:
    return ActorContext(tenant_id=TENANT, actor_id=ACTOR, active_role="methodologist")


def patch_service(monkeypatch, *, resolve=resolved, generated=proposal):
    monkeypatch.setattr(service, "_security_context", _noop)
    monkeypatch.setattr(service, "resolve_lesson_correction", _resolved(resolve))
    monkeypatch.setattr(service, "generate_correction_proposal", _generate(generated))


async def _noop(*args, **kwargs):
    return None


def _resolved(value):
    async def run(*args, **kwargs):
        return value() if callable(value) else value

    return run


def _generate(value):
    async def run(*args, **kwargs):
        return value() if callable(value) else value

    return run


@pytest.mark.asyncio
async def test_claim_and_ten_cent_charge_commit_before_provider(monkeypatch):
    db = Storage()
    provider_calls = []
    patch_service(monkeypatch)

    async def provider(_tenant):
        provider_calls.append(1)
        assert len(db.accounting_commit_states) == 2
        return object()

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert result.state == "ready"
    assert result.revision == 1
    assert len(provider_calls) == 1
    assert db.commits == 3
    assert db.statements[0].is_insert


@pytest.mark.asyncio
async def test_create_preview_commits_reserved_and_started_accounting_before_provider(monkeypatch):
    db = Storage()
    db.db_clock = NOW
    patch_service(monkeypatch)

    async def provider(_tenant):
        assert len(db.accounting_commit_states) == 2
        assert db.accounting_commit_states[0][0][1] == "reserved"
        assert db.accounting_commit_states[1][0][1] == "started"
        row = db.accounting_commit_states[1][0]
        assert row[2:] == (TENANT, ACTOR, "2026-10", 10)
        assert any(params.get("cost") == 10 for _, params in db.budget_statements)
        return object()

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert result.state == "ready"


@pytest.mark.asyncio
async def test_create_and_read_use_database_time_despite_ahead_host_clock(monkeypatch):
    db = Storage()
    db.db_clock = datetime.now(UTC)
    install_clock(monkeypatch, db.db_clock + timedelta(minutes=20))
    patch_service(monkeypatch)

    async def provider(_tenant):
        return object()

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    snapshot = LessonCorrectionSnapshot.model_validate(db.rows[result.plan_id].snapshot)
    assert snapshot.created_at == db.db_clock
    assert result.expires_at == db.db_clock + timedelta(minutes=15)
    loaded = await service.get_correction_preview(db, actor(), result.plan_id)
    assert loaded.fingerprint == result.fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "read"])
async def test_database_clock_query_failure_is_fixed_conflict_without_charge(monkeypatch, operation):
    db = Storage()
    patch_service(monkeypatch)

    async def provider(_tenant):
        return object()

    if operation == "read":
        result = await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    original_scalar = db.scalar
    events_before = list(db.events)

    async def broken_clock(statement):
        if "clock_timestamp" in str(statement):
            raise SQLAlchemyError("private database diagnostics")
        return await original_scalar(statement)

    async def forbidden_call(*args, **kwargs):
        pytest.fail("clock failure must precede charge and provider")

    monkeypatch.setattr(db, "scalar", broken_clock)
    with pytest.raises(service.WorkbenchConflict, match="^correction_clock_unavailable$"):
        if operation == "create":
            await service.create_correction_preview(db, actor(), request(), provider_resolver=forbidden_call)
        else:
            await service.get_correction_preview(db, actor(), result.plan_id)
    assert db.events == events_before


class Clock:
    values = []

    @classmethod
    def now(cls, _tz):
        return cls.values.pop(0) if len(cls.values) > 1 else cls.values[0]


def install_clock(monkeypatch, *values):
    Clock.values = list(values)
    monkeypatch.setattr(service, "datetime", Clock)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "failed", "ready"])
async def test_same_key_replay_never_recharges_or_calls_provider(monkeypatch, status):
    db = Storage()
    key = uuid4()
    body = request(key=key)
    current = datetime.now(UTC)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=7,
        actor_id=ACTOR,
        created_at=current - timedelta(minutes=1),
        expires_at=current + timedelta(minutes=14),
        context=context(),
        instruction=body.instruction,
        locale=body.locale,
    )
    row = SimpleNamespace(
        id=snapshot.plan_id,
        tenant_id=TENANT,
        actor_id=ACTOR,
        request_key=key,
        request_digest=service.request_digest(body),
        snapshot=snapshot.model_dump(mode="json"),
        status=status,
        expires_at=snapshot.expires_at,
        proposal=proposal().model_dump(mode="json") if status == "ready" else None,
        fingerprint=None,
        error_code="proposal_unavailable" if status == "failed" else None,
    )
    if status == "ready":
        from app.modules.methodologist_workbench.correction_contract import preview_lesson_correction
        from app.modules.methodologist_workbench.correction_proposal import CorrectionPatchAdapter

        row.fingerprint = preview_lesson_correction(
            snapshot,
            actor=actor(),
            current=snapshot.context,
            provider=CorrectionPatchAdapter(BEFORE, proposal()),
            now=current,
        ).fingerprint
    db.rows[row.id] = row
    patch_service(monkeypatch)
    providers = []

    async def provider(_tenant):
        providers.append(1)
        return object()

    result = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
    assert result.state == status
    assert result.revision == 7
    loaded = await service.get_correction_preview(db, actor(), snapshot.plan_id)
    assert loaded.revision == 7
    assert loaded.state == status
    assert providers == [] and db.budget_statements == []


@pytest.mark.asyncio
async def test_same_key_changed_body_is_conflict_before_provider(monkeypatch):
    db = Storage()
    key = uuid4()
    original = request(key=key)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=ACTOR,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        context=context(),
        instruction=original.instruction,
        locale=original.locale,
    )
    db.rows[snapshot.plan_id] = SimpleNamespace(
        id=snapshot.plan_id,
        tenant_id=TENANT,
        actor_id=ACTOR,
        request_key=key,
        request_digest=service.request_digest(original),
        snapshot=snapshot.model_dump(mode="json"),
        status="pending",
        expires_at=snapshot.expires_at,
        proposal=None,
        fingerprint=None,
        error_code=None,
    )
    patch_service(monkeypatch)
    with pytest.raises(service.WorkbenchConflict, match="request_key_collision"):
        await service.create_correction_preview(db, actor(), request(key=key, instruction="different"))


@pytest.mark.asyncio
async def test_insert_conflict_same_body_returns_winner_without_charge_or_provider(monkeypatch):
    key = uuid4()
    body = request(key=key)
    current = datetime.now(UTC)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=ACTOR,
        created_at=current - timedelta(minutes=1),
        expires_at=current + timedelta(minutes=14),
        context=context(),
        instruction=body.instruction,
        locale=body.locale,
    )
    winner = SimpleNamespace(
        id=snapshot.plan_id,
        tenant_id=TENANT,
        actor_id=ACTOR,
        request_key=key,
        request_digest=service.request_digest(body),
        snapshot=snapshot.model_dump(mode="json"),
        status="pending",
        expires_at=snapshot.expires_at,
        proposal=None,
        fingerprint=None,
        error_code=None,
    )
    db = Storage(conflict_row=winner)
    patch_service(monkeypatch)
    providers = []

    async def provider(_tenant):
        providers.append(1)
        return object()

    result = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
    assert result.state == "pending"
    assert providers == [] and db.budget_statements == []


@pytest.mark.asyncio
async def test_insert_conflict_changed_body_is_collision_without_charge_or_provider(monkeypatch):
    key = uuid4()
    original = request(key=key)
    winner = SimpleNamespace(
        id=uuid4(),
        tenant_id=TENANT,
        actor_id=ACTOR,
        request_key=key,
        request_digest=service.request_digest(original),
        snapshot={},
        status="pending",
        expires_at=datetime.now(UTC) + timedelta(minutes=14),
        proposal=None,
        fingerprint=None,
        error_code=None,
    )
    db = Storage(conflict_row=winner)
    patch_service(monkeypatch)
    with pytest.raises(service.WorkbenchConflict, match="request_key_collision"):
        await service.create_correction_preview(db, actor(), request(key=key, instruction="different"))


@pytest.mark.asyncio
async def test_zero_budget_denied_before_shared_helper_and_provider(monkeypatch):
    db = Storage(budget=0)
    patch_service(monkeypatch)
    provider_calls = []

    async def provider(_tenant):
        provider_calls.append(1)
        return object()

    with pytest.raises(HTTPException, match="llm_budget_exceeded"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert db.budget_statements == [] and provider_calls == []


@pytest.mark.asyncio
async def test_old_snapshot_month_is_refunded_from_immutable_ledger_month(monkeypatch):
    db = Storage()
    admission = datetime(2026, 1, 31, 23, 50, tzinfo=UTC)
    db.db_clock = admission
    patch_service(monkeypatch)

    async def provider(_tenant):
        db.db_clock = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
        return object()

    async def broken(_tenant):
        db.db_clock = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
        raise RuntimeError("provider-failure")

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=broken)
    assert result.state == "failed" and result.error_code == "proposal_unavailable"
    row = next(iter(db.accounting_rows.values()))
    assert row.month_key == "2026-01" and row.state == "refunded"


@pytest.mark.asyncio
async def test_real_live_actor_denial_happens_before_claim_or_provider(monkeypatch):
    db = Storage()
    db.live_actor = False
    patch_service(monkeypatch)
    provider_calls = []

    async def provider(_tenant):
        provider_calls.append(1)
        return object()

    with pytest.raises(service.CorrectionError, match="role_denied"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert provider_calls == [] and db.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "role_denied"])
async def test_post_provider_failure_closes_owned_pending_and_refunds_once(monkeypatch, failure):
    db = Storage()
    patch_service(monkeypatch, resolve=resolved())
    original_assert = service._assert_live_actor
    calls = 0

    async def assert_actor(database, current_actor):
        nonlocal calls
        calls += 1
        if failure == "role_denied" and calls >= 2:
            raise service.CorrectionError("role_denied")
        return await original_assert(database, current_actor)

    monkeypatch.setattr(service, "_assert_live_actor", assert_actor)
    if failure == "stale":
        sequence = iter((resolved(), resolved(content="changed")))
        monkeypatch.setattr(service, "resolve_lesson_correction", _resolved(lambda: next(sequence)))
    body = request()
    provider_calls = []

    async def provider(_tenant):
        provider_calls.append(1)
        return object()

    result = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
    assert result.state == "failed" and result.error_code == failure
    assert next(iter(db.accounting_rows.values())).state == "refunded"
    if failure == "stale":
        replay = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
        assert replay.state == "failed"
        assert next(iter(db.accounting_rows.values())).state == "refunded" and len(provider_calls) == 1


@pytest.mark.asyncio
async def test_t2_commit_ack_failure_does_not_call_provider(monkeypatch):
    db = Storage()
    db.db_clock = NOW
    db.fail_commit_number = 2
    patch_service(monkeypatch)
    providers = []

    async def provider(_tenant):
        providers.append(1)
        return object()

    with pytest.raises(SQLAlchemyError, match="commit acknowledgement unavailable"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert providers == []
    assert next(iter(db.accounting_rows.values())).state == "started"


@pytest.mark.asyncio
async def test_cancellation_remains_cancelled_when_failure_closure_cannot_refund(monkeypatch):
    db = Storage()
    db.db_clock = NOW
    patch_service(monkeypatch)

    async def provider(_tenant):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert next(iter(db.accounting_rows.values())).state == "refunded"


async def _provider():
    return object()


@pytest.mark.asyncio
async def test_provider_cancellation_closes_once_then_preserves_cancelled_error(monkeypatch):
    db = Storage()
    patch_service(monkeypatch)

    async def cancelled(_tenant):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=cancelled)
    assert next(iter(db.accounting_rows.values())).state == "refunded"


@pytest.mark.asyncio
async def test_ready_reload_detects_tampered_fingerprint_and_expiry(monkeypatch):
    db = Storage()
    patch_service(monkeypatch)
    body = request()
    current = datetime.now(UTC)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=ACTOR,
        created_at=current - timedelta(minutes=1),
        expires_at=current + timedelta(minutes=14),
        context=context(),
        instruction=body.instruction,
        locale=body.locale,
    )
    row = SimpleNamespace(
        id=snapshot.plan_id,
        tenant_id=TENANT,
        actor_id=ACTOR,
        snapshot=snapshot.model_dump(mode="json"),
        status="ready",
        expires_at=snapshot.expires_at,
        proposal=proposal().model_dump(mode="json"),
        fingerprint="f" * 64,
        error_code=None,
    )
    db.rows[row.id] = row
    with pytest.raises(service.WorkbenchConflict, match="correction_record_invalid"):
        await service.get_correction_preview(db, actor(), row.id)
    expired_snapshot = LessonCorrectionSnapshot(
        plan_id=row.id,
        revision=1,
        actor_id=ACTOR,
        created_at=current - timedelta(minutes=10),
        expires_at=current - timedelta(minutes=1),
        context=context(),
        instruction=body.instruction,
        locale=body.locale,
    )
    row.fingerprint = None
    row.expires_at = expired_snapshot.expires_at
    row.snapshot = expired_snapshot.model_dump(mode="json")
    with pytest.raises(service.CorrectionError, match="expired"):
        await service.get_correction_preview(db, actor(), row.id)


@pytest.mark.asyncio
async def test_ready_get_rejects_stale_live_context_without_provider_or_write(monkeypatch):
    db = Storage()
    patch_service(monkeypatch, resolve=resolved(content="changed"))
    body = request()
    current = datetime.now(UTC)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=ACTOR,
        created_at=current - timedelta(minutes=1),
        expires_at=current + timedelta(minutes=14),
        context=context(),
        instruction=body.instruction,
        locale=body.locale,
    )
    from app.modules.methodologist_workbench.correction_contract import preview_lesson_correction
    from app.modules.methodologist_workbench.correction_proposal import CorrectionPatchAdapter

    fingerprint = preview_lesson_correction(
        snapshot,
        actor=actor(),
        current=snapshot.context,
        provider=CorrectionPatchAdapter(BEFORE, proposal()),
        now=current,
    ).fingerprint
    row = SimpleNamespace(
        id=snapshot.plan_id,
        tenant_id=TENANT,
        actor_id=ACTOR,
        snapshot=snapshot.model_dump(mode="json"),
        status="ready",
        expires_at=snapshot.expires_at,
        proposal=proposal().model_dump(mode="json"),
        fingerprint=fingerprint,
        error_code=None,
    )
    db.rows[row.id] = row
    with pytest.raises(service.CorrectionError, match="stale"):
        await service.get_correction_preview(db, actor(), row.id)
    assert db.statements == []


@pytest.mark.asyncio
async def test_unknown_provider_error_is_sanitized_and_refunded(monkeypatch):
    db = Storage()
    patch_service(monkeypatch)

    async def broken(_tenant):
        raise RuntimeError("secret provider payload")

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=broken)
    assert result.state == "failed" and result.error_code == "proposal_unavailable"
    assert "secret" not in str(result)
    assert next(iter(db.accounting_rows.values())).state == "refunded"
