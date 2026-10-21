import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
from app.modules.ai.worker_lesson_cycle import WorkerLessonAssessor, create_dev_lesson_assessor

RULE = "Обращение рассматривается не более 15 рабочих дней."
FACT = SourceFact("f1", "Обращение", "Срок", RULE, "doc_id=d1;part=1")
LESSON = LessonDraft("l1", "m", "Обращения", "Выбрать срок", RULE, ("f1",), (), 1)


class Journal:
    def __init__(self):
        self.rows = {}
        self.inputs = {}

    async def prepare(self, key, payload):
        assert self.inputs.setdefault(key, payload) == payload
        return deepcopy(self.rows.get(key))

    async def save_value(self, key, value):
        assert key in self.inputs
        self.rows[key] = json.loads(json.dumps(value))


class Model:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    async def ainvoke_validated(self, messages, parser, **kwargs):
        self.calls += 1
        return SimpleNamespace(value=parser(json.dumps(next(self.values))), attempt_count=1)


def responses():
    return [
        {"targets": [{"id": "term", "description": "Предельный срок", "source_refs": ["F1"],
                      "context": [], "question_format": "", "answer_components": []}],
         "dispositions": [{"ref": "F1", "target_ids": ["term"], "excluded": ""}]},
        {"admit": True, "target_ids": ["term"], "source_refs": ["F1"], "errors": [], "omissions": []},
        {"questions": [{"id": "q1", "target_ids": ["term"], "text": "Какой предельный срок рассмотрения обращения?",
                        "options": ["15 рабочих дней", "30 рабочих дней", "45 рабочих дней"]}]},
        {"reviews": [{"question_id": "q1", "educational": True, "lesson_answerable": True,
                      "unambiguous": True, "explanation_supported": True, "target_ids": ["term"],
                      "explanation": "Предельный срок — 15 рабочих дней.", "lesson_ref": "L1",
                      "options": [{"index": i, "relation": "supported" if i == 0 else "contradicted",
                                   "source_ref": "S1P1"} for i in range(3)]}]},
        {"audits": [{"question_id": "q1", "admit": True, "reason": "Maximum is explicit.",
                     "target_proofs": [{"target_id": "term", "question_part": "answer", "source_ref": "S1P1"}]}]},
    ]


async def checkpoint():
    pass


@pytest.mark.parametrize("environment,flag,enabled", [
    ("render-development", True, True), ("render-development-worker", True, True),
    ("kz-production", True, False), ("production", True, False), ("local", True, False),
    ("render-development-worker", False, False),
])
def test_only_exact_dev_runtime_can_select_new_pipeline(environment, flag, enabled):
    result = create_dev_lesson_assessor(settings=SimpleNamespace(DEPLOYMENT_ENVIRONMENT=environment,
        APP_ENV="production", AI_LESSON_CYCLE_DEV_ENABLED=flag, AI_LESSON_CYCLE_DEV_TENANTS=["qa"]), tenant_id="qa", job_id="job",
        client=Model([]), session_factory=None, checkpoint=checkpoint)
    assert (result is not None) == enabled


def test_other_dev_tenants_keep_the_existing_pipeline():
    result = create_dev_lesson_assessor(settings=SimpleNamespace(DEPLOYMENT_ENVIRONMENT="render-development-worker",
        AI_LESSON_CYCLE_DEV_ENABLED=True, AI_LESSON_CYCLE_DEV_TENANTS=["qa"]), tenant_id="another", job_id="job",
        client=Model([]), session_factory=None, checkpoint=checkpoint)
    assert result is None


@pytest.mark.asyncio
async def test_worker_automatically_plans_reviews_saves_and_restores_without_more_model_calls():
    journal = Journal()
    model = Model(responses())
    result = await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert result.questions[0].correct_answer == "15 рабочих дней"
    assert result.audit["coverage"]["requires_review"] is False
    assert model.calls == 5
    restored_model = Model([])
    restored = await WorkerLessonAssessor(tenant_id="qa", client=restored_model, journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert restored.questions == result.questions
    assert restored_model.calls == 0


@pytest.mark.asyncio
async def test_worker_does_not_advance_after_storage_failure():
    class BrokenJournal(Journal):
        async def save_value(self, key, value):
            raise OSError("storage unavailable")

    model = Model(responses())
    with pytest.raises(OSError):
        await WorkerLessonAssessor(tenant_id="qa", client=model, journal=BrokenJournal(), checkpoint=checkpoint)(LESSON, {"f1": FACT})
    assert model.calls == 2


@pytest.mark.asyncio
async def test_worker_rejects_cross_tenant_terminal_checkpoint_on_restart():
    journal = Journal()
    await WorkerLessonAssessor(tenant_id="qa", client=Model(responses()), journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})
    for key, value in journal.rows.items():
        if key.startswith("lesson-cycle:"):
            value["tenant_id"] = "another-tenant"
    with pytest.raises(ValueError, match="checkpoint_identity_mismatch"):
        await WorkerLessonAssessor(tenant_id="qa", client=Model([]), journal=journal, checkpoint=checkpoint)(LESSON, {"f1": FACT})


@pytest.mark.asyncio
async def test_worker_propagates_cancellation_before_any_provider_or_storage_work():
    import asyncio

    async def cancelled():
        raise asyncio.CancelledError()

    model = Model([])
    journal = Journal()
    with pytest.raises(asyncio.CancelledError):
        await WorkerLessonAssessor(tenant_id="qa", client=model, journal=journal, checkpoint=cancelled)(LESSON, {"f1": FACT})
    assert model.calls == 0 and not journal.rows and not journal.inputs
