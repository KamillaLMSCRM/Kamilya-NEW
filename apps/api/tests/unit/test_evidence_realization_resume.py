from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from test_evidence_course_application import _EmbeddingClient, _GenerationClient, _spreadsheet_corpus

from app.modules.ai.evidence_engine.application import generate_evidence_course
from app.modules.ai.evidence_engine.models import CourseIntent, LessonDraft, QuestionDraft
from app.modules.ai.evidence_engine.semantic_assessment import BlockAssessmentResult
from app.modules.ai.generation_checkpoint import GenerationCheckpointSnapshot, GenerationPlan, PlannedLesson
from app.modules.ai.lesson_cycle import POLICY_VERSION
from app.modules.ai.source_assessment_plan import PLAN_POLICY
from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal, WorkerLessonAssessor


class RealizationJournal(WorkerCycleJournal):
    def __init__(self) -> None:
        self.tenant_id = "tenant-one"
        self.job_id = "resume-job"
        self.values: dict[str, tuple[dict, dict]] = {}

    @staticmethod
    def _digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _owned_key(self, key: str) -> str:
        return "worker-cycle:" + self._digest([self.job_id, key])

    async def prepare(self, key: str, payload: dict) -> dict | None:
        owned = self._owned_key(key)
        prior = self.values.get(owned)
        self.values[owned] = (payload, prior[1] if prior is not None else None)
        return self.values[owned][1]

    async def save_value(self, key: str, value: dict) -> None:
        owned = self._owned_key(key)
        plan = self.values.get(owned, ({}, None))[0]
        self.values[owned] = (json.loads(json.dumps(plan)), json.loads(json.dumps(value)))

    async def read_value(self, key: str) -> dict | None:
        return self.values.get(self._owned_key(key), ({}, None))[1]

    async def read_owned_value(self, key: str, expected_plan: dict) -> dict | None:
        plan, value = self.values.get(self._owned_key(key), ({}, None))
        return value if plan == expected_plan else None

    async def read_owned_realization(self, key: str, expected_plan: dict) -> dict | None:
        value = await self.read_value(key)
        if value is None:
            return None
        if value.get("realization_plan") != expected_plan:
            raise ValueError("worker_cycle_realization_plan_changed")
        return await self.read_owned_value(key, expected_plan)

class SpyAssessor:
    learner_language_gate = False

    def __init__(self, journal: RealizationJournal) -> None:
        self.journal = journal
        self.assessor_calls = 0

    def realization_identity(self, lesson: LessonDraft, facts: dict, *, intent: object) -> str:
        return "source-plan:" + lesson.lesson_id

    def realization_key(self, *, lesson_id: str, ordinal: int, source_plan_identity: str) -> str:
        return "lesson-realization:" + source_plan_identity + f":{ordinal}:{lesson_id}"

    def realization_plan(self, lesson: LessonDraft, *, ordinal: int, source_plan_identity: str,
                         source_inventory_identity: str, prefix_digest: str) -> dict:
        return {
            "kind": "lesson-realization-v2", "tenant_id": self.journal.tenant_id,
            "job_id": self.journal.job_id, "lesson_id": lesson.lesson_id, "ordinal": ordinal,
            "lesson_input_sha256": hashlib.sha256(json.dumps(asdict(lesson), sort_keys=True, default=list).encode()).hexdigest(),
            "source_plan_identity": source_plan_identity, "source_inventory_identity": source_inventory_identity,
            "policy_revision": "test", "prefix_digest": prefix_digest,
        }

    async def restore_realization(self, lesson: LessonDraft, **kwargs: object) -> dict | None:
        plan = self.realization_plan(lesson, **kwargs)
        return await self.journal.read_owned_realization(self.realization_key(
            lesson_id=lesson.lesson_id, ordinal=int(kwargs["ordinal"]), source_plan_identity=str(kwargs["source_plan_identity"])), plan)

    async def save_realization(self, lesson: LessonDraft, *, ordinal: int, source_plan_identity: str,
                               source_inventory_identity: str, prefix_digest: str, payload: dict) -> None:
        plan = self.realization_plan(lesson, ordinal=ordinal, source_plan_identity=source_plan_identity,
                                     source_inventory_identity=source_inventory_identity, prefix_digest=prefix_digest)
        assert payload["realization_plan"] == plan
        await self.journal.prepare(self.realization_key(lesson_id=lesson.lesson_id, ordinal=ordinal, source_plan_identity=source_plan_identity), plan)
        await self.journal.save_value(self.realization_key(lesson_id=lesson.lesson_id, ordinal=ordinal, source_plan_identity=source_plan_identity), payload)

    async def __call__(self, lesson: LessonDraft, facts: dict) -> BlockAssessmentResult:
        self.assessor_calls += 1
        fact = facts[lesson.fact_ids[0]]
        question = QuestionDraft(
            "q-" + lesson.lesson_id, lesson.lesson_id, "single_choice",
            f"Which documented requirement applies in {lesson.title}?", (fact.value, "An unrelated option"),
            fact.value, "The source provides the requirement.", fact.fact_id,
            evidence_fact_ids=(fact.fact_id,), source_quote=fact.value,
        )
        return BlockAssessmentResult((question,), {"lesson_id": lesson.lesson_id, "coverage": {"requires_review": True}}, 0)


class ForbiddenGenerationClient(_GenerationClient):
    async def ainvoke_validated(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("generation client called after committed realization restore")


class _SessionContext:
    def __init__(self) -> None:
        self.enters = 0

    async def __aenter__(self) -> _SessionContext:
        self.enters += 1
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _CheckpointRepository:
    def __init__(self, plan: GenerationPlan, row: GenerationCheckpointSnapshot) -> None:
        self.plan, self.row = plan, row

    async def load_plan(self, _session: object, **_kwargs: object) -> GenerationPlan:
        return self.plan

    async def load_checkpoints(self, _session: object, **_kwargs: object) -> tuple[GenerationCheckpointSnapshot, ...]:
        return (self.row,)


class _EmptyResult:
    def first(self):
        return None


class _EmptyDatabaseSession(_SessionContext):
    async def execute(self, *_args, **_kwargs):
        return _EmptyResult()


@pytest.mark.asyncio
async def test_real_journal_cold_start_uses_native_repository_missing_plan_contract() -> None:
    session = _EmptyDatabaseSession()
    journal = WorkerCycleJournal("tenant-one", "resume-job", lambda: session)
    assert await journal.read_owned_realization("new-realization", {"kind": "lesson-realization-v1"}) is None
    assert session.enters == 1


@pytest.mark.asyncio
async def test_real_journal_reader_rejects_incomplete_checkpoint_without_second_read() -> None:
    context = _SessionContext()
    journal = WorkerCycleJournal("tenant-one", "resume-job", lambda: context)
    expected = {"kind": "lesson-realization-v1"}
    journal.repository = _CheckpointRepository(
        GenerationPlan("key", f"{PLAN_POLICY}/{POLICY_VERSION}", "resume-job", expected,
                       (PlannedLesson("cycle", "lesson", 0, 0),)),
        GenerationCheckpointSnapshot("cycle", "lesson", 0, 0, {"owned": True}, {"policy": PLAN_POLICY},
                                     {"realization_plan": expected}, "completed", "completed", "pending"),
    )
    with pytest.raises(ValueError, match="checkpoint_incomplete"):
        await journal.read_owned_realization("key", expected)
    assert context.enters == 1


@pytest.mark.asyncio
async def test_application_restores_committed_realizations_before_generation_client() -> None:
    journal = RealizationJournal()
    assessor = SpyAssessor(journal)
    first = await generate_evidence_course(
        _spreadsheet_corpus(), intent=CourseIntent(),
        generation_client=_GenerationClient(), embedding_client=_EmbeddingClient(), lesson_assessor=assessor,
    )
    assert first.result.realized_course.lessons
    assert journal.values
    prior_assessor_calls = assessor.assessor_calls

    restored_assessor = SpyAssessor(journal)
    second = await generate_evidence_course(
        _spreadsheet_corpus(), intent=CourseIntent(),
        generation_client=ForbiddenGenerationClient(), embedding_client=_EmbeddingClient(), lesson_assessor=restored_assessor,
    )
    assert [lesson.lesson_id for lesson in second.result.realized_course.lessons] == [
        lesson.lesson_id for lesson in first.result.realized_course.lessons
    ]
    assert restored_assessor.assessor_calls == 0
    assert prior_assessor_calls > 0


@pytest.mark.asyncio
async def test_application_rejects_tampered_restored_answer_instead_of_regenerating() -> None:
    journal = RealizationJournal()
    assessor = SpyAssessor(journal)
    await generate_evidence_course(
        _spreadsheet_corpus(), intent=CourseIntent(),
        generation_client=_GenerationClient(), embedding_client=_EmbeddingClient(), lesson_assessor=assessor,
    )
    first_key = next(key for key, (_plan, value) in journal.values.items() if value and value.get("assessment", {}).get("questions"))
    journal.values[first_key][1]["questions"][0]["correct_answer"] = "An unrelated option"
    with pytest.raises(ValueError, match="assessment_mismatch|question_source_binding"):
        await generate_evidence_course(
            _spreadsheet_corpus(), intent=CourseIntent(),
            generation_client=ForbiddenGenerationClient(), embedding_client=_EmbeddingClient(), lesson_assessor=SpyAssessor(journal),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["invalid_persisted_plan_payload", "generation_plan_conflict", "connection_timeout"])
async def test_real_journal_does_not_convert_other_repository_errors_into_cache_miss(error):
    from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError

    class BrokenRepository:
        async def load_plan(self, *args, **kwargs):
            raise AIGenerationCheckpointError(error)

    journal = WorkerCycleJournal("tenant-one", "resume-job", _SessionContext)
    journal.repository = BrokenRepository()
    with pytest.raises(AIGenerationCheckpointError, match=error):
        await journal.read_owned_realization("key", {})


def _owned_native_journal():
    from test_worker_lesson_cycle import Journal

    from app.modules.ai.json_evidence_equivalence import equivalent

    class OwnedJournal(Journal):
        job_id = "native-resume-job"

        async def prepare(self, key, payload):
            if key in self.inputs:
                assert equivalent(self.inputs[key], payload)
            else:
                self.inputs[key] = json.loads(json.dumps(payload))
            return deepcopy(self.rows.get(key))

        async def read_owned_value(self, key, expected_plan):
            if not equivalent(self.inputs.get(key), expected_plan):
                return None
            return deepcopy(self.rows.get(key))

        async def read_value(self, key):
            return deepcopy(self.rows.get(key))

        async def read_owned_realization(self, key, expected_plan):
            if key not in self.inputs:
                return None
            if not equivalent(self.inputs[key], expected_plan):
                raise ValueError("worker_cycle_realization_plan_changed")
            value = await self.read_owned_value(key, expected_plan)
            if value is None or not equivalent(value.get("realization_plan"), expected_plan):
                raise ValueError("worker_cycle_realization_checkpoint_incomplete")
            return value

    return OwnedJournal()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["none", "answer", "missing_cycle", "missing_plan", "audit"])
async def test_native_assessor_revalidates_durable_questions_with_zero_provider_calls(mutation):
    from test_worker_lesson_cycle import FACT, LESSON, Model, checkpoint, responses

    journal = _owned_native_journal()
    model = Model(responses())
    assessor = WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)
    await assessor.prepare_source_plan(LESSON, {"f1": FACT}, intent=CourseIntent())
    assessment = await assessor(LESSON, {"f1": FACT})
    assert assessment.questions and model.calls == 5
    first_calls = model.calls
    cycle_key = next(key for key in journal.rows if key.startswith("lesson-cycle:"))
    if mutation == "answer":
        journal.rows[cycle_key]["questions"][0]["correct_index"] = 1
    elif mutation == "missing_cycle":
        del journal.rows[cycle_key]
    elif mutation == "missing_plan":
        del journal.rows[next(key for key in journal.rows if key.startswith("source-plan:"))]
    elif mutation == "audit":
        assessment.audit["coverage"]["requires_review"] = False
    operation = assessor.validate_realization(LESSON, {"f1": FACT}, base_lesson=LESSON,
        intent=CourseIntent(), catalogs=(), assessment=assessment)
    if mutation == "none":
        await operation
    else:
        with pytest.raises(ValueError):
            await operation
    assert model.calls == first_calls


def _single_rule_corpus():
    from test_evidence_course_application import _narrative_corpus
    from test_worker_lesson_cycle import RULE

    original = _narrative_corpus()
    document = original.documents[0]
    chunk = replace(document.chunks[0], text=RULE, headings=("Обращения",))
    return replace(original, documents=(replace(document, chunks=(chunk,)),), total_chars=len(RULE))


@pytest.mark.asyncio
@pytest.mark.parametrize("language_gate", [False, True])
@pytest.mark.parametrize("rewrite_title", [False, True])
async def test_application_native_assessor_json_roundtrip_retains_body_and_questions_without_calls(language_gate, rewrite_title):
    from test_evidence_course_application import _positive_prose_language_call, _surface_review_response
    from test_worker_lesson_cycle import RULE, Model, checkpoint, responses

    from app.modules.ai.llm_client import ValidatedLLMResult

    class NativeClient(_GenerationClient):
        def __init__(self):
            values = responses()
            if language_gate:
                values[0]["targets"][0]["answer_components"] = [{"ref": "F1", "terms": [RULE]}]
            self.model = Model(values, auto_language=language_gate)
            self.author_calls = 0

        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if language_gate and request.get("task") in {"lesson_assessment_author", "lesson_assessment_repair"}:
                # An explicit empty author result is a held target, not a fake
                # positive teaching/semantic judgment. Native restore must retain it.
                return ValidatedLLMResult(provider="fixture", model_id="fixture",
                    value=parser('{"questions":[]}'), attempt_count=1, failure_reasons=())
            if request.get("task") == "lesson_prose_language_review":
                return _positive_prose_language_call(request, parser)
            if request.get("task") == "lesson_surface_semantic_review":
                return ValidatedLLMResult(provider="fixture", model_id="fixture",
                    value=parser(json.dumps(_surface_review_response(request))),
                    attempt_count=1, failure_reasons=())
            if "lesson_title" in request and "facts" in request:
                self.author_calls += 1
                def author_parser(raw):
                    payload = json.loads(raw)
                    if rewrite_title:
                        payload.update(title="Рассмотрение обращений", objective="Применить установленный срок")
                    return parser(json.dumps(payload))

                return await super().ainvoke_validated(messages, author_parser, **kwargs)
            return await self.model.ainvoke_validated(messages, parser, **kwargs)

    journal, client = _owned_native_journal(), NativeClient()
    assessor = WorkerLessonAssessor(tenant_id="qa", client=client, journal=journal,
        checkpoint=checkpoint, learner_language_gate=language_gate)
    first = await generate_evidence_course(_single_rule_corpus(), intent=CourseIntent(),
        generation_client=client, embedding_client=_EmbeddingClient(), lesson_assessor=assessor)
    if not language_gate:
        assert first.result.realized_assessment.questions
    assert client.model.calls == (2 if language_gate else 5)
    assert client.author_calls == 1
    before = deepcopy(journal.rows)
    # Simulate the actual JSON/JSONB wire for both plans and completed values.
    journal.rows = json.loads(json.dumps(journal.rows))
    journal.inputs = json.loads(json.dumps(journal.inputs))
    no_provider = ForbiddenGenerationClient()
    restored = await generate_evidence_course(_single_rule_corpus(), intent=CourseIntent(),
        generation_client=no_provider, embedding_client=_EmbeddingClient(),
        lesson_assessor=WorkerLessonAssessor(tenant_id="qa", client=no_provider,
            journal=journal, checkpoint=checkpoint, learner_language_gate=language_gate))
    assert restored.result.realized_course == first.result.realized_course
    assert restored.result.realized_assessment == first.result.realized_assessment
    assert journal.rows == before
    assert not restored.result.publishability.publishable  # Fixture lacks complete material accounting.
    assert restored.result.chat_attempt_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["none", "catalog", "surface_receipt", "surface_status", "missing_surface", "negative_attempts"])
async def test_application_rederives_surface_and_teaching_catalog_after_json_restore(mutation):
    from test_evidence_course_application import _positive_prose_language_call, _surface_review_response

    from app.modules.ai.llm_client import ValidatedLLMResult

    class SurfaceClient(_GenerationClient):
        async def ainvoke_validated(self, messages, parser, **kwargs):
            request = json.loads(messages[-1]["content"])
            if request.get("task") == "lesson_prose_language_review":
                return _positive_prose_language_call(request, parser)
            if request.get("task") == "lesson_surface_semantic_review":
                return ValidatedLLMResult(provider="fixture", model_id="fixture",
                    value=parser(json.dumps(_surface_review_response(request))),
                    attempt_count=1, failure_reasons=())
            return await super().ainvoke_validated(messages, parser, **kwargs)

    class SurfaceAssessor(SpyAssessor):
        learner_language_gate = True

    journal = RealizationJournal()
    first = await generate_evidence_course(_single_rule_corpus(), intent=CourseIntent(),
        generation_client=SurfaceClient(), embedding_client=_EmbeddingClient(),
        lesson_assessor=SurfaceAssessor(journal))
    value = next(value for _, value in journal.values.values())
    assert value["teaching_catalog"]["entries"]
    if mutation == "catalog":
        value["teaching_catalog"]["entries"][0]["body"] += " Changed."
    elif mutation == "surface_receipt":
        value["surface_state"]["result"]["block_receipts"][0]["source_sha256"] = "0" * 64
    elif mutation == "surface_status":
        value["surface_review"]["surface_ready"] = False
    elif mutation == "missing_surface":
        value["surface_review"] = None
    elif mutation == "negative_attempts":
        value["assessment"]["attempt_count"] = -1
    operation = generate_evidence_course(_single_rule_corpus(), intent=CourseIntent(),
        generation_client=ForbiddenGenerationClient(), embedding_client=_EmbeddingClient(),
        lesson_assessor=SurfaceAssessor(journal))
    if mutation == "none":
        second = await operation
        assert second.result.realized_course == first.result.realized_course
        assert second.result.realized_assessment == first.result.realized_assessment
    else:
        with pytest.raises(ValueError, match="catalog_changed|checkpoint_invalid|surface_status_changed|surface_review_missing|attempt_count_invalid"):
            await operation


@pytest.mark.asyncio
async def test_crash_after_committed_first_lesson_restores_prefix_and_authors_only_remaining_lessons():
    class CrashAfterCommit(SpyAssessor):
        async def save_realization(self, *args, **kwargs):
            await super().save_realization(*args, **kwargs)
            raise RuntimeError("synthetic crash after commit")

    class CountingClient(_GenerationClient):
        def __init__(self):
            self.titles = []

        async def ainvoke_validated(self, messages, parser, **kwargs):
            self.titles.append(json.loads(messages[-1]["content"])["lesson_title"])
            return await super().ainvoke_validated(messages, parser, **kwargs)

    journal = RealizationJournal()
    with pytest.raises(RuntimeError, match="synthetic crash"):
        await generate_evidence_course(_spreadsheet_corpus(), intent=CourseIntent(),
            generation_client=_GenerationClient(), embedding_client=_EmbeddingClient(),
            lesson_assessor=CrashAfterCommit(journal))
    committed = next(value for _, value in journal.values.values())
    client = CountingClient()
    final = await generate_evidence_course(_spreadsheet_corpus(), intent=CourseIntent(),
        generation_client=client, embedding_client=_EmbeddingClient(), lesson_assessor=SpyAssessor(journal))
    assert len(final.result.realized_course.lessons) > 1
    assert final.result.realized_course.lessons[0].content == committed["lesson"]["content"]
    assert len(client.titles) == len(final.result.realized_course.lessons) - 1
    assert committed["lesson"]["title"] not in client.titles


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["fact_ids", "supporting_fact_ids"])
async def test_prepared_source_ownership_change_stops_before_additional_inference(field):
    from test_worker_lesson_cycle import FACT, LESSON, Model, checkpoint, responses

    model = Model(responses())
    facts = {"f1": FACT, "f2": replace(FACT, fact_id="f2")}
    assessor = WorkerLessonAssessor(tenant_id="qa", client=model,
        journal=_owned_native_journal(), checkpoint=checkpoint)
    await assessor.prepare_source_plan(LESSON, facts, intent=CourseIntent())
    calls = model.calls
    with pytest.raises(ValueError, match="prepared_source_ownership_changed"):
        await assessor(replace(LESSON, **{field: ("f2",)}), facts)
    assert model.calls == calls
