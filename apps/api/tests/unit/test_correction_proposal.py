"""Deterministic lesson-correction proposal adapter contracts."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

import pytest

from app.modules.ai.llm_client import ValidatedLLMResult
from app.modules.editor_assistant.patch_contract import (
    PatchApplicabilityStatus,
    PatchOperationType,
    ValidationStatus,
)
from app.modules.methodologist_workbench.correction_contract import (
    CorrectionError,
    CorrectionEvidence,
    LessonCorrectionContext,
    LessonCorrectionSnapshot,
    preview_lesson_correction,
)
from app.modules.methodologist_workbench.correction_proposal import (
    CorrectionExcerpt,
    CorrectionPatchAdapter,
    generate_correction_proposal,
)
from app.modules.methodologist_workbench.correction_schemas import CorrectionCitation
from app.modules.methodologist_workbench.plan_contract import ActorContext

NOW = datetime(2026, 10, 5, 8, tzinfo=UTC)
TENANT, ACTOR, COURSE, MODULE, LESSON, DOCUMENT, PLAN = [UUID(int=index) for index in range(1, 8)]
BEFORE = "Article A100 is a steel cabinet with roller guides 450 mm long."
AFTER = "Article A100 is a steel cabinet equipped with roller guides that are 450 mm long."
SOURCE_TEXT = "Article A100\nGuides: roller, length 450 mm.\nBody: steel."


def digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def make_snapshot(*, locale: str = "en", content: str = BEFORE) -> LessonCorrectionSnapshot:
    citation = CorrectionCitation(document_id=DOCUMENT, locator="fact:article-a100", evidence_hash=digest(SOURCE_TEXT))
    context = LessonCorrectionContext(
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
                "evidence": [{"locator": citation.locator, "evidence_hash": citation.evidence_hash}],
            },
        ),
    )
    return LessonCorrectionSnapshot(
        plan_id=PLAN,
        revision=1,
        actor_id=ACTOR,
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
        context=context,
        instruction="Clarify the lesson while preserving the source facts.",
        locale=locale,
    )


class DeterministicLLM:
    def __init__(self, raw: str):
        self.raw = raw
        self.calls = 0
        self.messages: list[dict[str, str]] = []

    async def ainvoke_validated(self, messages, parser):
        self.calls += 1
        self.messages = messages
        return ValidatedLLMResult("fake.test", "fake-correction-v1", parser(self.raw))


def excerpts(*, text: str = SOURCE_TEXT) -> tuple[CorrectionExcerpt, ...]:
    citation = CorrectionCitation(document_id=DOCUMENT, locator="fact:article-a100", evidence_hash=digest(text))
    return (CorrectionExcerpt(citation, text),)


@pytest.mark.asyncio
@pytest.mark.parametrize("locale", ["ru", "kk", "en"])
async def test_valid_locales_admit_exact_source_and_actual_provenance(locale):
    llm = DeterministicLLM('{"action":"propose","content":"' + AFTER + '","evidence":[0]}')
    proposal = await generate_correction_proposal(
        make_snapshot(locale=locale), title="Cabinet guides", excerpts=excerpts(), llm=llm
    )

    assert llm.calls == 1
    assert proposal.content == AFTER
    assert proposal.citations[0].document_id == DOCUMENT
    assert proposal.citations[0].locator == "fact:article-a100"
    assert proposal.citations[0].evidence_hash == digest(SOURCE_TEXT)
    assert proposal.provenance.provider == "fake.test"
    assert proposal.provenance.model_id == "fake-correction-v1"
    assert proposal.provenance.prompt_version == "lesson-correction-v1"
    assert proposal.provenance.generator_version == "correction-preview-v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: CorrectionExcerpt(item.citation.model_copy(update={"evidence_hash": "b" * 64}), item.text),
        lambda item: CorrectionExcerpt(item.citation, item.text + " outside"),
    ],
)
async def test_evidence_text_and_hash_must_match_before_provider_call(mutate):
    llm = DeterministicLLM('{"action":"propose","content":"' + AFTER + '","evidence":[0]}')
    item = mutate(excerpts()[0])
    with pytest.raises(CorrectionError, match="^invalid_source_evidence$"):
        await generate_correction_proposal(make_snapshot(), title="Cabinet guides", excerpts=(item,), llm=llm)
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_source_and_prompt_bounds_are_checked_before_provider_call():
    oversized = "x" * 24_001
    citation = CorrectionCitation(document_id=DOCUMENT, locator="fact:large", evidence_hash=digest(oversized))
    source = (
        make_snapshot()
        .context.sources[0]
        .model_copy(
            update={"evidence": (CorrectionEvidence(locator=citation.locator, evidence_hash=citation.evidence_hash),)}
        )
    )
    snapshot = make_snapshot().model_copy(
        update={"context": make_snapshot().context.model_copy(update={"sources": (source,)})}
    )
    llm = DeterministicLLM('{"action":"propose","content":"' + AFTER + '","evidence":[0]}')
    with pytest.raises(CorrectionError, match="^correction_context_too_large$"):
        await generate_correction_proposal(
            snapshot, title="Cabinet guides", excerpts=(CorrectionExcerpt(citation, oversized),), llm=llm
        )
    assert llm.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        '{"action":"propose","content":"' + AFTER + '","evidence":[0,0]}',
        '{"action":"propose","content":"' + AFTER + '","evidence":[1]}',
        '{"action":"propose","content":"' + AFTER + '","evidence":[true]}',
        '{"action":"propose","content":"' + AFTER + '","evidence":[0],"authority":true}',
        '{"action":"propose","content":"' + AFTER + '","evidence":[0],"evidence":[0]}',
    ],
)
async def test_strict_json_rejects_duplicate_extra_boolean_and_invented_ordinals(raw):
    llm = DeterministicLLM(raw)
    with pytest.raises(CorrectionError, match="^proposal_unavailable$"):
        await generate_correction_proposal(make_snapshot(), title="Cabinet guides", excerpts=excerpts(), llm=llm)
    assert llm.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,code",
    [
        ('{"action":"propose","content":"' + BEFORE + '","evidence":[0]}', "proposal_unavailable"),
        ('{"action":"clarification","code":"instruction_unclear"}', "instruction_unclear"),
        ('{"action":"clarification","code":"invented_code"}', "proposal_unavailable"),
    ],
)
async def test_unchanged_content_and_closed_clarification_are_refused(raw, code):
    llm = DeterministicLLM(raw)
    with pytest.raises(CorrectionError, match=f"^{code}$"):
        await generate_correction_proposal(make_snapshot(), title="Cabinet guides", excerpts=excerpts(), llm=llm)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "This lesson is useful for everyone.",
        "Article A100 causes customers to choose this cabinet because it is superior.",
        "Article A100 is a steel cabinet with roller guides 451 mm long.",
    ],
)
async def test_quality_rejects_thin_unsupported_or_wrong_numeric_output(content):
    llm = DeterministicLLM('{"action":"propose","content":' + repr(content).replace("'", '"') + ',"evidence":[0]}')
    with pytest.raises(CorrectionError, match="^proposal_unavailable$"):
        await generate_correction_proposal(make_snapshot(), title="Cabinet guides", excerpts=excerpts(), llm=llm)


@pytest.mark.asyncio
async def test_quality_policy_and_patch_adapter_bridge_to_foundation_preview():
    snapshot = make_snapshot()
    llm = DeterministicLLM('{"action":"propose","content":"' + AFTER + '","evidence":[0]}')
    proposal = await generate_correction_proposal(snapshot, title="Cabinet guides", excerpts=excerpts(), llm=llm)
    preview = preview_lesson_correction(
        snapshot,
        actor=ActorContext(tenant_id=TENANT, actor_id=ACTOR, active_role="methodologist"),
        current=snapshot.context,
        provider=CorrectionPatchAdapter(snapshot.context.content, proposal),
        now=NOW,
    )

    operation = preview.patch.operations[0]
    assert operation.operation == PatchOperationType.REPLACE
    assert operation.field_path == "lesson.content"
    assert operation.before_value == BEFORE
    assert operation.after_value == AFTER
    assert preview.patch.validation_report.status == ValidationStatus.PASS
    assert preview.patch.applicability_status == PatchApplicabilityStatus.APPLICABLE
    assert preview.patch.provider_provenance == proposal.provenance
    assert preview.patch.source_evidence[0].locator == "fact:article-a100"
