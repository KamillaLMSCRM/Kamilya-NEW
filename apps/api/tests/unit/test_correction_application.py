"""Public application/read behavior, actual owners with DB/storage boundaries."""

import copy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.elements import TextClause

from app.models.document import Document
from app.models.user_roles import UserRole
from app.models.users import User
from app.modules.ai.direct_source import build_direct_source_corpus
from app.modules.ai.evidence_engine.application import (
    build_evidence_source,
    generate_evidence_course,
    to_generation_artifacts,
)
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.llm_client import AllProvidersFailedError
from app.modules.audit.models import AuditLog
from app.modules.course_approval.models import (
    CourseApprovalPolicy,
    CourseApprovalRequest,
    CourseApprovalRevision,
    WorkflowAccessCredential,
    WorkflowWorkItem,
)
from app.modules.courses.models import Course
from app.modules.lessons.models import ContentBlock, Lesson, Module
from app.modules.methodologist_workbench import correction_application as application
from app.modules.methodologist_workbench.assignment_service import WorkbenchConflict, WorkbenchNotFound
from app.modules.methodologist_workbench.correction_context import resolve_lesson_correction
from app.modules.methodologist_workbench.correction_contract import (
    CorrectionError,
    LessonCorrectionSnapshot,
    preview_lesson_correction,
)
from app.modules.methodologist_workbench.correction_models import LessonCorrectionApplication, LessonCorrectionPlan
from app.modules.methodologist_workbench.correction_proposal import CorrectionPatchAdapter
from app.modules.methodologist_workbench.correction_schemas import CorrectionProposal
from app.modules.methodologist_workbench.plan_contract import ActorContext, ConfirmationRequest
from app.modules.quizzes.models import Question, Quiz, QuizChoice

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
TENANT, ACTOR, COURSE, MODULE, LESSON, DOCUMENT = [UUID(int=i) for i in range(1, 7)]
BLOB = b"# Article A100\n\n| Article | Material |\n| --- | --- |\n| A100 | steel |\n"
BEFORE = "Article A100 is a wood cabinet."
AFTER = "Article A100 is a steel cabinet."


class Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return list(self.values)

    def scalars(self):
        return self

    def one_or_none(self):
        return next(iter(self.values), None)

    def scalar_one_or_none(self):
        return self.one_or_none()


class MemoryDB:
    """SQL-shaped DB adapter; never evidence of real transaction/RLS/FK locks."""

    def __init__(self, rows):
        self.rows = rows
        self.commits = 0
        self.rollbacks = 0
        self.statements = []
        self.now = NOW
        self.fail_on = None
        self.baseline = None
        self.busy_model = None
        self.busy_sqlstate = None

    def remember(self):
        self.baseline = {
            model: [
                (row, copy.deepcopy({c.key: getattr(row, c.key) for c in model.__mapper__.column_attrs}))
                for row in rows
            ]
            for model, rows in self.rows.items()
        }

    def filtered(self, model, statement):
        rows = self.rows.get(model, [])
        # The DB boundary fake enforces supplied ownership/id binds. Actual RLS
        # and locking are exclusively the later real Supabase DEV gate.
        params = statement.compile().params
        for name, value in params.items():
            field = name.rsplit("_", 1)[0]
            if hasattr(model, field):
                rows = (
                    [row for row in rows if getattr(row, field) in value]
                    if isinstance(value, list)
                    else [row for row in rows if getattr(row, field) == value]
                )
        return rows

    async def execute(self, statement, params=None):
        self.statements.append(statement)
        if isinstance(statement, TextClause):
            return Rows([])
        if getattr(statement, "is_update", False):
            if statement.table.name == "quizzes":
                for row in self.rows.get(Quiz, []):
                    for key, value in statement._values.items():
                        setattr(row, getattr(key, "key", str(key)), getattr(value, "value", value))
            return Rows([])
        descriptions = statement.column_descriptions
        lock = getattr(statement, "_for_update_arg", None)
        if self.busy_model is descriptions[0]["entity"] and lock is not None:
            if self.busy_model is not LessonCorrectionPlan:
                assert lock.nowait, "Approval contention must never wait in reversed owner lock order"
            origin = RuntimeError("private database parameters")
            origin.sqlstate = self.busy_sqlstate
            raise OperationalError("synthetic lock", {}, origin)
        if len(descriptions) == 3:
            return Rows([(self.rows[Lesson][0], self.rows[Module][0], self.rows[Course][0])])
        model = descriptions[0]["entity"]
        return Rows(self.filtered(model, statement))

    async def scalars(self, statement):
        result = await self.execute(statement)
        entity = statement.column_descriptions[0]["entity"]
        expression = statement.column_descriptions[0]["expr"]
        if expression is not entity:
            return Rows([getattr(row, expression.key) for row in result.values])
        return result

    async def scalar(self, statement):
        if "clock_timestamp" in str(statement):
            return self.now
        if "users.id" in str(statement) and "EXISTS" in str(statement):
            user = self.rows[User][0]
            return user.id if user.role == "methodologist" and user.is_active and user.status == "active" else None
        return (await self.scalars(statement)).one_or_none()

    def add(self, row):
        if self.fail_on is type(row):
            raise RuntimeError("synthetic persistence failure")
        self.rows.setdefault(type(row), []).append(row)

    async def flush(self):
        for row in self.rows.get(LessonCorrectionApplication, []):
            if row.applied_at is None:
                row.applied_at = self.now

    async def refresh(self, _row):
        pass

    async def commit(self):
        if self.fail_on == "before_commit":
            raise RuntimeError("synthetic commit failure")
        self.commits += 1
        self.remember()
        if self.fail_on == "lost_commit_ack":
            raise RuntimeError("synthetic lost commit acknowledgment")

    async def rollback(self):
        self.rollbacks += 1
        if self.baseline:
            self.rows.clear()
            for model, entries in self.baseline.items():
                self.rows[model] = [row for row, _ in entries]
                for row, values in entries:
                    for key, value in values.items():
                        setattr(row, key, copy.deepcopy(value))


async def fixture(monkeypatch):
    from app.core import storage

    class BlobStorage:
        def get_bytes(self, key):
            assert key == "synthetic.md"
            return BLOB

    monkeypatch.setattr(storage, "get_storage", lambda: BlobStorage())
    document = Document(
        id=DOCUMENT,
        tenant_id=TENANT,
        uploaded_by=ACTOR,
        title="Synthetic",
        filename="synthetic.md",
        content_type="text/markdown",
        size=len(BLOB),
        s3_key="synthetic.md",
        source_family_id=DOCUMENT,
        version=1,
        index_revision=1,
        index_status="ready",
        content_sha256=sha256(BLOB).hexdigest(),
        lifecycle_status="active",
        category="general",
    )
    facts = build_evidence_source(await build_direct_source_corpus([document], tenant_id=TENANT)).generation_facts
    course = Course(
        id=COURSE,
        tenant_id=TENANT,
        title="Synthetic",
        description="",
        status="draft",
        delivery_type="native",
        source_document_ids=[str(DOCUMENT)],
        source_strategy="single_topic",
        source_analysis={},
        review_status="approved",
        reviewed_by=ACTOR,
        reviewed_at=NOW,
        review_comment="old",
        current_release_id=None,
    )
    lesson = Lesson(
        id=LESSON,
        tenant_id=TENANT,
        module_id=MODULE,
        title="Article A100",
        content_type="text",
        content=BEFORE,
        order_index=0,
        source_document_ids=[str(DOCUMENT)],
        source_validation_status="verified",
        source_references=[
            {"doc_id": str(DOCUMENT), "fact_id": fact.fact_id, "source_locator": fact.source_locator} for fact in facts
        ],
    )
    db = MemoryDB(
        {
            User: [User(id=ACTOR, tenant_id=TENANT, role="methodologist", status="active", is_active=True)],
            UserRole: [],
            Document: [document],
            Course: [course],
            Module: [
                Module(id=MODULE, tenant_id=TENANT, course_id=COURSE, title="Module", description="", order_index=0)
            ],
            Lesson: [lesson],
            ContentBlock: [],
            Question: [],
            QuizChoice: [],
            Quiz: [
                Quiz(
                    id=uuid4(),
                    lesson_id=LESSON,
                    tenant_id=TENANT,
                    title="Quiz",
                    pass_score=80,
                    attempt_limit=3,
                    deferral_days=7,
                    review_status="approved",
                    reviewed_by=ACTOR,
                    reviewed_at=NOW,
                )
            ],
            CourseApprovalPolicy: [],
            CourseApprovalRevision: [],
        }
    )
    actor = ActorContext(tenant_id=TENANT, actor_id=ACTOR, active_role="methodologist")
    resolved = await resolve_lesson_correction(db, actor, LESSON)
    snapshot = LessonCorrectionSnapshot(
        plan_id=uuid4(),
        revision=1,
        actor_id=ACTOR,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        context=resolved.context,
        instruction="Fix material",
        locale="en",
    )
    proposal = CorrectionProposal(
        content=AFTER,
        citations=tuple(item.citation for item in resolved.excerpts),
        provenance={
            "provider": "fake.test",
            "model_id": "fake-v1",
            "prompt_version": "correction-v1",
            "generator_version": "correction-v1",
        },
    )
    preview = preview_lesson_correction(
        snapshot, actor=actor, current=resolved.context, provider=CorrectionPatchAdapter(BEFORE, proposal), now=NOW
    )
    db.rows[LessonCorrectionPlan] = [
        LessonCorrectionPlan(
            id=snapshot.plan_id,
            tenant_id=TENANT,
            actor_id=ACTOR,
            request_key=uuid4(),
            request_digest="a" * 64,
            snapshot=snapshot.model_dump(mode="json"),
            status="ready",
            proposal=proposal.model_dump(mode="json"),
            fingerprint=preview.fingerprint,
            expires_at=snapshot.expires_at,
        )
    ]
    db.remember()
    return db, actor, ConfirmationRequest(plan_id=snapshot.plan_id, revision=1, fingerprint=preview.fingerprint)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [None, "fact_id", "source_locator", "doc_id", "source_revision"])
async def test_real_generation_artifact_resolves_exact_correction_provenance(monkeypatch, tamper):
    """Exercise generation -> persistence artifact -> correction, without a provider."""
    db, actor, _ = await fixture(monkeypatch)
    from app.core import storage

    source = (
        b"# Warehouse receiving rules\n\n"
        b"If the invoice lists 12 boxes but only 10 arrive, record a shortage of 2 boxes.\n\n"
        b"Complete the shortage report within 20 minutes of discovery.\n\n"
        b"Isolate a damaged box and notify the shift supervisor. Only the supervisor decides whether to use it."
    )

    class GeneratedStorage:
        def get_bytes(self, key):
            assert key == "synthetic.md"
            return source

    monkeypatch.setattr(storage, "get_storage", lambda: GeneratedStorage())
    document = db.rows[Document][0]
    document.content_sha256 = sha256(source).hexdigest()
    document.size = len(source)
    document.category = "training_material"

    class UnavailableProvider:
        async def ainvoke_validated(self, *_args, **_kwargs):
            raise AllProvidersFailedError("synthetic generation unavailable")

        async def embed_documents_with_provenance(self, *_args, **_kwargs):
            raise AllProvidersFailedError("synthetic embedding unavailable")

    corpus = await build_direct_source_corpus(db.rows[Document], tenant_id=TENANT)
    output = await generate_evidence_course(
        corpus,
        intent=CourseIntent(),
        generation_client=UnavailableProvider(),
        embedding_client=UnavailableProvider(),
        max_lessons=1,
    )
    artifact = to_generation_artifacts(output).content.modules[0].lessons[0]
    lesson = db.rows[Lesson][0]
    lesson.content = artifact.content
    lesson.source_references = copy.deepcopy(artifact.source_references)
    assert lesson.source_references
    assert all(ref["fact_id"].startswith("fact-") for ref in lesson.source_references)
    if tamper == "source_revision":
        lesson.source_references[0]["source_locator"] = lesson.source_references[0]["source_locator"].replace(
            sha256(source).hexdigest(), "0" * 64
        )
    elif tamper:
        lesson.source_references[0][tamper] = str(uuid4()) if tamper == "doc_id" else "forged"
    if tamper:
        with pytest.raises(CorrectionError, match="^lesson_source_provenance_unavailable$"):
            await resolve_lesson_correction(db, actor, LESSON)
    else:
        resolved = await resolve_lesson_correction(db, actor, LESSON)
        assert {item.citation.locator for item in resolved.excerpts} == {
            f"fact:{ref['fact_id']}" for ref in lesson.source_references
        }
        assert all(item.citation.document_id == DOCUMENT for item in resolved.excerpts)
    assert db.commits == 0


@pytest.mark.asyncio
async def test_apply_then_read_returns_exact_receipt_and_review_states(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    result = await application.apply_correction_preview(db, actor, confirmation)
    loaded = await application.get_correction_application(db, actor, confirmation.plan_id)
    assert loaded == result
    assert result.state == "applied"
    assert result.before_sha256 == sha256(BEFORE.encode()).hexdigest()
    assert result.after_sha256 == sha256(AFTER.encode()).hexdigest()
    assert result.applied_at == NOW
    assert db.rows[Lesson][0].content == AFTER
    assert db.rows[Lesson][0].source_validation_status == "needs_review"
    assert db.rows[Quiz][0].review_status == "needs_review"
    assert db.rows[Course][0].review_status == "pending"
    assert db.rows[Course][0].reviewed_by is None
    assert db.rows[Course][0].review_comment is None
    assert len(db.rows[AuditLog]) == 1
    assert BEFORE not in str(db.rows[AuditLog][0].details) and AFTER not in str(db.rows[AuditLog][0].details)
    assert db.commits == 1


@pytest.mark.asyncio
async def test_exact_replay_after_expiry_and_manual_change_returns_original_receipt(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    first = await application.apply_correction_preview(db, actor, confirmation)
    db.now += timedelta(days=2)
    db.rows[Lesson][0].content = "Later authorized manual edit"
    db.rows[Course][0].review_status = "approved"
    replay = await application.apply_correction_preview(db, actor, confirmation)
    assert replay == first
    assert await application.get_correction_application(db, actor, confirmation.plan_id) == first
    assert db.rows[Lesson][0].content == "Later authorized manual edit"
    assert db.rows[Course][0].review_status == "approved"
    assert len(db.rows[LessonCorrectionApplication]) == len(db.rows[AuditLog]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["fingerprint", "revision"])
async def test_changed_confirmation_cannot_replay_or_write(monkeypatch, change):
    db, actor, confirmation = await fixture(monkeypatch)
    first = await application.apply_correction_preview(db, actor, confirmation)
    bad = confirmation.model_copy(update={change: "b" * 64 if change == "fingerprint" else 2})
    with pytest.raises(WorkbenchConflict):
        await application.apply_correction_preview(db, actor, bad)
    assert await application.get_correction_application(db, actor, confirmation.plan_id) == first
    assert len(db.rows[LessonCorrectionApplication]) == len(db.rows[AuditLog]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_model", [AuditLog, LessonCorrectionApplication])
async def test_audit_or_receipt_failure_rolls_back_all_writes(monkeypatch, failure_model):
    db, actor, confirmation = await fixture(monkeypatch)
    db.fail_on = failure_model
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == BEFORE
    assert db.rows[Lesson][0].source_validation_status == "verified"
    assert db.rows[Quiz][0].review_status == "approved"
    assert db.rows[Course][0].review_status == "approved"
    assert not db.rows.get(AuditLog) and not db.rows.get(LessonCorrectionApplication)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code", [("expired", "expired"), ("lesson", "stale"), ("published", "new_draft_required")]
)
async def test_expired_changed_or_published_context_refuses_before_writes(monkeypatch, change, code):
    db, actor, confirmation = await fixture(monkeypatch)
    if change == "expired":
        db.now += timedelta(minutes=15)
    elif change == "lesson":
        db.rows[Lesson][0].content = "Changed before apply"
    else:
        db.rows[Course][0].status = "published"
    db.remember()
    before = db.rows[Lesson][0].content
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == before
    assert not db.rows.get(AuditLog) and not db.rows.get(LessonCorrectionApplication)
    assert db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["sibling", "foreign", "revoked"])
async def test_unowned_or_revoked_actor_never_writes_or_reads_receipt(monkeypatch, identity):
    db, actor, confirmation = await fixture(monkeypatch)
    if identity == "revoked":
        db.rows[User][0].role = "student"
    else:
        actor = actor.model_copy(update={"actor_id": uuid4()} if identity == "sibling" else {"tenant_id": uuid4()})
    db.remember()
    with pytest.raises((WorkbenchNotFound, CorrectionError)):
        await application.apply_correction_preview(db, actor, confirmation)
    with pytest.raises((WorkbenchNotFound, CorrectionError)):
        await application.get_correction_application(db, actor, confirmation.plan_id)
    assert db.rows[Lesson][0].content == BEFORE
    assert not db.rows.get(LessonCorrectionApplication) and not db.rows.get(AuditLog)


@pytest.mark.asyncio
async def test_application_read_without_receipt_is_not_found(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    with pytest.raises(WorkbenchNotFound, match="application_not_found"):
        await application.get_correction_application(db, actor, confirmation.plan_id)


@pytest.mark.asyncio
async def test_busy_application_has_safe_conflict_and_no_partial_write(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    db.busy_model = LessonCorrectionPlan
    db.busy_sqlstate = "55P03"
    with pytest.raises(WorkbenchConflict, match="^correction_application_busy$"):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == BEFORE
    assert not db.rows.get(LessonCorrectionApplication) and not db.rows.get(AuditLog)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "failed"])
async def test_unready_preview_never_applies(monkeypatch, state):
    db, actor, confirmation = await fixture(monkeypatch)
    db.rows[LessonCorrectionPlan][0].status = state
    db.remember()
    with pytest.raises(WorkbenchConflict, match="correction_preview_not_ready"):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == BEFORE
    assert not db.rows.get(AuditLog) and not db.rows.get(LessonCorrectionApplication)
    assert db.commits == 0


@pytest.mark.asyncio
async def test_changed_stored_proposal_cannot_apply_old_seal(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    db.rows[LessonCorrectionPlan][0].proposal["content"] = "Article A100 is a plastic cabinet."
    db.remember()
    with pytest.raises(CorrectionError):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == BEFORE
    assert not db.rows.get(AuditLog) and not db.rows.get(LessonCorrectionApplication)
    assert db.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "busy_model", [CourseApprovalRevision, CourseApprovalRequest, WorkflowWorkItem, WorkflowAccessCredential]
)
async def test_approval_contention_refuses_without_waiting_or_writes(monkeypatch, busy_model):
    db, actor, confirmation = await fixture(monkeypatch)
    db.busy_model = busy_model
    with pytest.raises(OperationalError):
        await application.apply_correction_preview(db, actor, confirmation)
    assert db.rows[Lesson][0].content == BEFORE
    assert db.rows[Course][0].review_status == "approved"
    assert not db.rows.get(AuditLog) and not db.rows.get(LessonCorrectionApplication)
    assert db.commits == 0 and db.rollbacks == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_case", ["before_commit", "lost_commit_ack"])
async def test_commit_failure_has_no_false_success_and_recovers_only_durable_receipt(monkeypatch, commit_case):
    db, actor, confirmation = await fixture(monkeypatch)
    db.fail_on = commit_case
    with pytest.raises(RuntimeError):
        await application.apply_correction_preview(db, actor, confirmation)
    if commit_case == "before_commit":
        assert db.rows[Lesson][0].content == BEFORE
        assert not db.rows.get(LessonCorrectionApplication)
    else:
        recovered = await application.get_correction_application(db, actor, confirmation.plan_id)
        assert recovered.after_sha256 == sha256(AFTER.encode()).hexdigest()
        db.fail_on = None
        assert await application.apply_correction_preview(db, actor, confirmation) == recovered
        assert len(db.rows[AuditLog]) == len(db.rows[LessonCorrectionApplication]) == 1


@pytest.mark.asyncio
async def test_application_supersedes_approval_artifacts_without_erasing_history(monkeypatch):
    db, actor, confirmation = await fixture(monkeypatch)
    revision_id, request_id, item_id, credential_id = [uuid4() for _ in range(4)]
    revision = CourseApprovalRevision(
        id=revision_id,
        tenant_id=TENANT,
        course_id=COURSE,
        revision_number=1,
        state="approved",
        snapshot={"historic": "immutable"},
        snapshot_sha256="b" * 64,
        source_fingerprint="c" * 64,
    )
    db.rows[CourseApprovalRevision] = [revision]
    db.rows[CourseApprovalRequest] = [
        CourseApprovalRequest(
            id=request_id,
            tenant_id=TENANT,
            revision_id=revision_id,
            requested_by=ACTOR,
            delivery_mode="personal_link",
            outcome="approved",
        )
    ]
    db.rows[WorkflowWorkItem] = [
        WorkflowWorkItem(
            id=item_id, tenant_id=TENANT, review_revision_id=revision_id, outcome="approved", access_state="active"
        )
    ]
    db.rows[WorkflowAccessCredential] = [
        WorkflowAccessCredential(id=credential_id, tenant_id=TENANT, work_item_id=item_id, revoked_at=None)
    ]
    # A distinct newly reviewed preview must include this approval pre-state.
    resolved = await resolve_lesson_correction(db, actor, LESSON)
    row = db.rows[LessonCorrectionPlan][0]
    snapshot = LessonCorrectionSnapshot.model_validate(row.snapshot).model_copy(update={"context": resolved.context})
    proposal = CorrectionProposal.model_validate(row.proposal)
    preview = preview_lesson_correction(
        snapshot, actor=actor, current=resolved.context, provider=CorrectionPatchAdapter(BEFORE, proposal), now=NOW
    )
    row.snapshot, row.fingerprint = snapshot.model_dump(mode="json"), preview.fingerprint
    confirmation = confirmation.model_copy(update={"fingerprint": preview.fingerprint})
    db.remember()
    await application.apply_correction_preview(db, actor, confirmation)
    assert revision.state == "superseded"
    assert revision.snapshot == {"historic": "immutable"}
    assert db.rows[CourseApprovalRequest][0].outcome == "superseded"
    assert db.rows[WorkflowWorkItem][0].outcome == "superseded"
    assert db.rows[WorkflowWorkItem][0].access_state == "revoked"
    assert db.rows[WorkflowAccessCredential][0].revoked_at is not None
    assert sum(row.action == "workbench.lesson_correction_applied" for row in db.rows[AuditLog]) == 1
    assert db.commits == 1
