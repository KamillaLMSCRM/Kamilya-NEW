from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.modules.ai.evidence_engine.application import EvidenceSourceBundle
from app.modules.ai.evidence_engine.models import SourceDocument, SourceFact, SourceSection
from app.modules.methodologist_workbench import correction_context as subject
from app.modules.methodologist_workbench.correction_contract import CorrectionError
from app.modules.methodologist_workbench.document_schemas import DocumentSource
from app.modules.methodologist_workbench.plan_contract import ActorContext

TENANT = UUID("00000000-0000-0000-0000-000000000001")
ACTOR = UUID("00000000-0000-0000-0000-000000000002")
COURSE = UUID("00000000-0000-0000-0000-000000000003")
MODULE = UUID("00000000-0000-0000-0000-000000000004")
LESSON = UUID("00000000-0000-0000-0000-000000000005")
DOCUMENT = UUID("00000000-0000-0000-0000-000000000006")
DOC_SHA = "a" * 64


class _Result:
    def __init__(self, value):
        self.value = value

    def one_or_none(self):
        return self.value

    def scalars(self):
        return self

    def all(self):
        return list(self.value)


class _DB:
    def __init__(self, graph, document, policy=None, revisions=(), release=None):
        self.graph = graph
        self.document = document
        self.policy = policy
        self.revisions = list(revisions)
        self.release = release or _release()
        self.execute_calls = 0
        self.scalars_calls = 0

    async def execute(self, _query):
        self.execute_calls += 1
        return _Result(self.graph)

    async def scalars(self, _query):
        # The resolver's first scalar query loads the original documents; the
        # later scalar query loads approval revisions.
        self.scalars_calls += 1
        if self.scalars_calls % 2 == 1:
            return _Result(self.document if isinstance(self.document, list) else [self.document])
        return _Result(self.revisions)

    async def scalar(self, _query):
        return self.policy


def _actor(**changes):
    return ActorContext(
        tenant_id=changes.get("tenant_id", TENANT),
        actor_id=changes.get("actor_id", ACTOR),
        active_role=changes.get("active_role", "methodologist"),
    )


def _release(**changes):
    payload = {
        "modules": [
            {
                "id": str(MODULE),
                "lessons": [
                    {
                        "id": str(LESSON),
                        "content": "Before lesson text",
                        "published_at": None,
                    }
                ],
            }
        ],
    }
    payload.update(changes)
    return payload


def _objects(**changes):
    lesson = SimpleNamespace(
        id=LESSON,
        tenant_id=TENANT,
        module_id=MODULE,
        title="Lesson",
        content_type="text",
        content="Before lesson text",
        published_at=None,
        source_document_ids=[str(DOCUMENT)],
        source_references=[
            {
                "fact_id": "fact-1",
                "doc_id": str(DOCUMENT),
                "source_locator": f"doc_id={DOCUMENT};source_revision=document:{DOC_SHA};section=Rules",
            }
        ],
    )
    module = SimpleNamespace(id=MODULE, tenant_id=TENANT, course_id=COURSE)
    course = SimpleNamespace(
        id=COURSE,
        tenant_id=TENANT,
        status="draft",
        delivery_type="native",
        current_release_id=None,
        published_at=None,
        source_document_ids=[str(DOCUMENT)],
    )
    document = SimpleNamespace(
        id=DOCUMENT,
        tenant_id=TENANT,
        title="rules.pdf",
        version=2,
        content_sha256=DOC_SHA,
        index_revision=7,
        lifecycle_status="active",
    )
    for name, value in changes.items():
        if name == "lesson":
            lesson = SimpleNamespace(**{**vars(lesson), **value})
        elif name == "course":
            course = SimpleNamespace(**{**vars(course), **value})
        elif name == "document":
            document = SimpleNamespace(**{**vars(document), **value})
    return lesson, module, course, document


def _facts(citation_locator=None, fact_id="fact-1"):
    locator = citation_locator or f"doc_id={DOCUMENT};source_revision=document:{DOC_SHA};section=Rules"
    return (SourceFact(fact_id, "Equipment", "rule", "Check it", locator),)


def _patch(monkeypatch, facts=None, sources=None):
    lesson, module, course, document = _objects()
    graph = (lesson, module, course)
    db = _DB(
        graph,
        document,
        policy=SimpleNamespace(
            id=uuid4(),
            course_id=COURSE,
            tenant_id=TENANT,
            requires_approval=True,
            review_enabled=True,
        ),
        revisions=[
            SimpleNamespace(
                id=uuid4(),
                revision_number=1,
                state="approved",
                snapshot_sha256="b" * 64,
                source_fingerprint="c" * 64,
                published_release_id=None,
            )
        ],
    )

    async def resolve_sources(*_args, **_kwargs):
        assert db.scalars_calls % 2 == 1  # document identity refresh precedes metadata reads
        return sources or (
            DocumentSource(
                document_id=DOCUMENT, title="rules.pdf", version=2, content_sha256=DOC_SHA, index_revision=7
            ),
        )

    async def build_corpus(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(subject, "resolve_document_sources", resolve_sources)
    monkeypatch.setattr(subject, "build_direct_source_corpus", build_corpus)
    bundle = SimpleNamespace(generation_facts=tuple(facts or _facts()))
    monkeypatch.setattr(subject, "build_evidence_source", lambda _corpus: bundle)

    async def build_release(*_args, **_kwargs):
        assert _kwargs["populate_existing"] is True
        return db.release

    monkeypatch.setattr(subject, "build_course_release_snapshot", build_release)
    return db, lesson, module, course, document


@pytest.mark.asyncio
async def test_resolver_returns_owned_context_and_exact_fact_hash(monkeypatch):
    db, *_ = _patch(monkeypatch)
    resolved = await subject.resolve_lesson_correction(db, _actor(), LESSON)
    assert resolved.context.tenant_id == TENANT
    assert resolved.context.course_id == COURSE
    assert resolved.context.module_id == MODULE
    assert resolved.context.lesson_id == LESSON
    assert resolved.context.sources[0].version == 2
    assert resolved.context.sources[0].index_revision == 7
    assert resolved.context.sources[0].evidence[0].locator == "fact:fact-1"
    assert resolved.excerpts[0].text == "Equipment\nrule: Check it"


@pytest.mark.asyncio
async def test_resolver_denies_foreign_actor_or_chain_before_source_work(monkeypatch):
    db, *_ = _patch(monkeypatch)
    with pytest.raises(Exception) as error:
        await subject.resolve_lesson_correction(db, _actor(tenant_id=uuid4()), LESSON)
    assert getattr(error.value, "code", str(error.value)) in {"lesson_not_found", "not_found"}

    lesson, module, course, document = _objects(lesson={"tenant_id": uuid4()})
    db = _DB((lesson, module, course), document)
    with pytest.raises(Exception) as error:
        await subject.resolve_lesson_correction(db, _actor(), LESSON)
    assert getattr(error.value, "code", str(error.value)) in {"lesson_not_found", "not_found"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lesson_changes,course_changes,expected",
    [
        ({"published_at": datetime.now(UTC)}, {}, "new_draft_required"),
        ({}, {"status": "published"}, "new_draft_required"),
        ({"content_type": "video"}, {}, "lesson_correction_unsupported"),
    ],
)
async def test_resolver_rejects_published_and_unsupported_lessons(
    monkeypatch, lesson_changes, course_changes, expected
):
    db, lesson, module, course, document = _patch(monkeypatch)
    lesson, module, course, document = _objects(lesson=lesson_changes, course=course_changes)
    db.graph, db.document = (lesson, module, course), document
    with pytest.raises(CorrectionError, match=f"^{expected}$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_fact",
    [
        _facts(fact_id="other"),
        _facts(citation_locator="wrong-locator"),
    ],
)
async def test_resolver_rejects_missing_or_changed_fact_identity(monkeypatch, bad_fact):
    db, lesson, module, course, document = _patch(monkeypatch, facts=bad_fact)
    with pytest.raises(CorrectionError, match="^lesson_source_provenance_unavailable$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["doc_id", "source_locator", "canonical_collision"])
async def test_two_owned_documents_cannot_swap_fact_provenance(monkeypatch, tamper):
    db, lesson, _module, course, document = _patch(monkeypatch)
    second_id, second_sha = UUID(int=7), "d" * 64
    second = SimpleNamespace(**{**vars(document), "id": second_id, "content_sha256": second_sha})
    lesson.source_document_ids = course.source_document_ids = [str(DOCUMENT), str(second_id)]
    db.document = [document, second]
    first_fact = _facts()[0]
    second_fact = SourceFact(
        "raw-second", "Equipment" if tamper == "canonical_collision" else "Other equipment",
        "rule", "Check it",
        f"doc_id={second_id};source_revision=document:{second_sha};section=Rules",
    )
    bundle = EvidenceSourceBundle(SourceDocument(
        source_id="two-owned-documents", title="Rules", kind="narrative",
        sections=(
            SourceSection("first", "Rules", "primary", (first_fact,)),
            SourceSection("second", "Rules", "supporting", (second_fact,)),
        ),
    ))
    facts = bundle.generation_facts
    lesson.source_references = [
        {"fact_id": fact.fact_id, "doc_id": str(doc.id), "source_locator": fact.source_locator}
        for fact, doc in zip(facts, db.document, strict=True)
    ]
    monkeypatch.setattr(subject, "build_evidence_source", lambda _corpus: bundle)

    async def sources(*_args, **_kwargs):
        return tuple(DocumentSource(
            document_id=doc.id, title=doc.title, version=doc.version,
            content_sha256=doc.content_sha256, index_revision=doc.index_revision,
        ) for doc in db.document)

    monkeypatch.setattr(subject, "resolve_document_sources", sources)
    if tamper != "canonical_collision":
        valid = await subject.resolve_lesson_correction(db, _actor(), LESSON)
        assert {item.citation.document_id for item in valid.excerpts} == {DOCUMENT, second_id}
        lesson.source_references[0][tamper] = (
            str(second_id) if tamper == "doc_id" else second_fact.source_locator
        )
    else:
        assert facts[0].fact_id == facts[1].fact_id
    with pytest.raises(CorrectionError, match="^lesson_source_provenance_unavailable$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)


@pytest.mark.asyncio
async def test_resolver_rejects_source_bounds_and_missing_source_membership(monkeypatch):
    db, lesson, module, course, document = _patch(monkeypatch)
    lesson.source_document_ids = [str(DOCUMENT)] * 6
    db.graph = (lesson, module, course)
    with pytest.raises(CorrectionError, match="^lesson_source_provenance_unavailable$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)

    lesson, module, course, document = _objects()
    lesson.source_references = [{"fact_id": "fact-1", "doc_id": str(DOCUMENT), "source_locator": "x"}]
    db.graph = (lesson, module, course)
    with pytest.raises(CorrectionError, match="^lesson_source_provenance_unavailable$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)


@pytest.mark.asyncio
async def test_course_version_changes_with_live_release_and_approval_state(monkeypatch):
    db, lesson, module, course, document = _patch(monkeypatch)
    first = await subject.resolve_lesson_correction(db, _actor(), LESSON)
    db.release["modules"][0]["lessons"][0]["content"] = "New live release text"
    with pytest.raises(CorrectionError, match="^stale$"):
        await subject.resolve_lesson_correction(db, _actor(), LESSON)

    db.release["modules"][0]["lessons"][0]["content"] = lesson.content
    db.revisions[0].state = "changes_requested"
    second = await subject.resolve_lesson_correction(db, _actor(), LESSON)
    assert second.context.course_version != first.context.course_version
