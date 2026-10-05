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
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
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
        self.events = []
        self.db_clock = None

    async def scalar(self, statement):
        text = str(statement)
        if "clock_timestamp" in text:
            return self.db_clock or service.datetime.now(UTC)
        if "monthly_llm_budget_usd_cents" in text:
            return self.budget
        if "workbench_lesson_correction_plans" in text:
            return next(iter(self.rows.values()), None)
        if "users" in text:
            return ACTOR if self.live_actor else None
        return None

    async def execute(self, statement):
        self.statements.append(statement)
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
            self.rows[row.id] = row
            return Result(row.id)
        if getattr(statement, "is_update", False):
            values = {
                getattr(key, "name", str(key).rsplit(".", 1)[-1]): getattr(value, "value", value)
                for key, value in statement._values.items()
            }
            row_id = next((value for value in self.rows if str(value) in str(statement)), None)
            if row_id is None and self.rows:
                row_id = next(reversed(self.rows))
            if row_id is not None:
                for key, value in values.items():
                    setattr(self.rows[row_id], key.rsplit(".", 1)[-1], value)
            return Result()
        return Result()

    async def commit(self):
        self.commits += 1
        self.events.append("commit")

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
    charges = []
    provider_calls = []
    patch_service(monkeypatch)

    async def charge(*args, **kwargs):
        charges.append((args, kwargs))
        db.events.append("charge")

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def provider(_tenant):
        provider_calls.append(1)
        assert db.events == ["charge", "commit"]
        return object()

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert result.state == "ready"
    assert result.revision == 1
    assert len(charges) == 1 and len(provider_calls) == 1
    assert charges[0][1] == {"operation": "lesson_correction_preview", "estimated_cost_cents": 10}
    assert charges[0][0][1] == str(TENANT)
    assert db.commits == 2
    assert db.statements[0].is_insert


@pytest.mark.asyncio
async def test_create_and_read_use_database_time_despite_ahead_host_clock(monkeypatch):
    db = Storage()
    db.db_clock = datetime.now(UTC)
    install_clock(monkeypatch, db.db_clock + timedelta(minutes=20))
    patch_service(monkeypatch)
    monkeypatch.setattr(service, "check_and_charge_llm_budget", _noop)

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
    monkeypatch.setattr(service, "check_and_charge_llm_budget", _noop)

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
    monkeypatch.setattr(service, "check_and_charge_llm_budget", forbidden_call)
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
    charges, providers = [], []

    async def charge(*args, **kwargs):
        charges.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def provider(_tenant):
        providers.append(1)
        return object()

    result = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
    assert result.state == status
    assert result.revision == 7
    loaded = await service.get_correction_preview(db, actor(), snapshot.plan_id)
    assert loaded.revision == 7
    assert loaded.state == status
    assert charges == [] and providers == []


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
    charges, providers = [], []

    async def charge(*args, **kwargs):
        charges.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def provider(_tenant):
        providers.append(1)
        return object()

    result = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
    assert result.state == "pending"
    assert charges == [] and providers == []


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
    helper_calls, provider_calls = [], []

    async def charge(*args, **kwargs):
        helper_calls.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def provider(_tenant):
        provider_calls.append(1)
        return object()

    with pytest.raises(HTTPException, match="llm_budget_exceeded"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert helper_calls == [] and provider_calls == []


@pytest.mark.asyncio
async def test_admission_month_mismatch_rolls_back_before_provider(monkeypatch):
    db = Storage()
    admission = datetime(2026, 1, 31, 23, 50, tzinfo=UTC)
    after_charge = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
    install_clock(monkeypatch, admission, admission, after_charge)
    patch_service(monkeypatch)
    charges, providers = [], []

    async def charge(*args, **kwargs):
        charges.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def provider(_tenant):
        providers.append(1)
        return object()

    with pytest.raises(service.WorkbenchConflict, match="correction_accounting_pending"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert charges == [1] and providers == []
    assert db.rollbacks >= 1


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
    charges, refunds = [], []

    async def charge(*args, **kwargs):
        charges.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "refund_llm_budget", refund)
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
    assert len(charges) == 1 and len(refunds) == 1
    if failure == "stale":
        replay = await service.create_correction_preview(db, actor(), body, provider_resolver=provider)
        assert replay.state == "failed"
        assert len(refunds) == 1 and len(charges) == 1 and len(provider_calls) == 1


@pytest.mark.asyncio
async def test_failure_from_old_admission_month_stays_pending_without_refund(monkeypatch):
    db = Storage()
    admission = datetime(2026, 1, 31, 23, 50, tzinfo=UTC)
    rollover = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
    install_clock(monkeypatch, admission, admission, admission, rollover)
    patch_service(monkeypatch)
    refunds, providers = [], []

    async def charge(*args, **kwargs):
        return None

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(service, "refund_llm_budget", refund)

    async def provider(_tenant):
        providers.append(1)
        raise RuntimeError("provider-failure")

    with pytest.raises(service.WorkbenchConflict, match="correction_accounting_pending"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert providers == [1] and refunds == [] and db.commits == 1 and db.rollbacks >= 1


@pytest.mark.asyncio
async def test_rollover_during_refund_rolls_back_without_commit(monkeypatch):
    db = Storage()
    admission = datetime(2026, 1, 31, 23, 50, tzinfo=UTC)
    rollover = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
    install_clock(monkeypatch, admission, admission, admission, admission, rollover)
    patch_service(monkeypatch)
    refunds = []

    async def charge(*args, **kwargs):
        return None

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(service, "refund_llm_budget", refund)

    async def provider(_tenant):
        raise RuntimeError("provider-failure")

    with pytest.raises(service.WorkbenchConflict, match="correction_accounting_pending"):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert refunds == [1] and db.commits == 1 and db.rollbacks >= 2


@pytest.mark.asyncio
async def test_cancellation_remains_cancelled_when_failure_closure_cannot_refund(monkeypatch):
    db = Storage()
    admission = datetime(2026, 1, 31, 23, 50, tzinfo=UTC)
    rollover = datetime(2026, 2, 1, 0, 1, tzinfo=UTC)
    install_clock(monkeypatch, admission, admission, admission, rollover)
    patch_service(monkeypatch)
    refunds = []

    async def charge(*args, **kwargs):
        return None

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)
    monkeypatch.setattr(service, "refund_llm_budget", refund)

    async def provider(_tenant):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=provider)
    assert refunds == [] and db.rollbacks >= 1


async def _provider():
    return object()


@pytest.mark.asyncio
async def test_provider_cancellation_closes_once_then_preserves_cancelled_error(monkeypatch):
    db = Storage()
    patch_service(monkeypatch)

    async def charge(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)
    refunds = []

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "refund_llm_budget", refund)

    async def cancelled(_tenant):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await service.create_correction_preview(db, actor(), request(), provider_resolver=cancelled)
    assert len(refunds) == 1


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

    async def charge(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "check_and_charge_llm_budget", charge)
    refunds = []

    async def refund(*args, **kwargs):
        refunds.append(1)

    monkeypatch.setattr(service, "refund_llm_budget", refund)

    async def broken(_tenant):
        raise RuntimeError("secret provider payload")

    result = await service.create_correction_preview(db, actor(), request(), provider_resolver=broken)
    assert result.state == "failed" and result.error_code == "proposal_unavailable"
    assert "secret" not in str(result)
    assert len(refunds) == 1
