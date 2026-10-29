import copy
from types import SimpleNamespace

import pytest

from app.modules.ai import worker_lesson_cycle as cycle


class ImmutableJournal:
    def __init__(self):
        self.values = {}
        self.plans = {}

    async def prepare(self, key, payload):
        if key in self.plans and self.plans[key] != payload:
            raise ValueError('plan_conflict')
        self.plans[key] = copy.deepcopy(payload)
        return copy.deepcopy(self.values.get(key))

    async def read_value(self, key):
        return copy.deepcopy(self.values.get(key))

    async def save_value(self, key, value):
        if key in self.values and self.values[key] != value:
            raise ValueError('assessment_checkpoint_conflict')
        self.values[key] = copy.deepcopy(value)

    def _owned_key(self, key):
        return key

    async def inventory_versions(self, base_key):
        return [dict(generation_key=key, plan_revision=f"{cycle.PLAN_POLICY}/{cycle.POLICY_VERSION}",
                     plan_payload=copy.deepcopy(plan), module_key='cycle', lesson_key='lesson',
                     assessment_status='completed' if key in self.values else 'pending',
                     assessment_payload=copy.deepcopy(self.values.get(key)))
                for key, plan in self.plans.items() if plan.get('inventory_base_key') == base_key]

    async def append_inventory_version(self, key, plan, value):
        await self.prepare(key, plan)
        await self.save_value(key, value)


def assessor(journal):
    obj = cycle.WorkerLessonAssessor.__new__(cycle.WorkerLessonAssessor)
    obj.tenant_id = 'qa-tenant'
    obj._source_plan_factory = SimpleNamespace(policy='test-policy')
    obj.learner_language_gate = True
    obj.journal = journal
    return obj


@pytest.mark.asyncio
async def test_multiple_lessons_survive_immutable_checkpoints_and_cold_resume(monkeypatch):
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    journal = ImmutableJournal()
    worker = assessor(journal)
    key, inventory = await worker._load_prompt_inventory()
    await worker._record_prompts(key=key, inventory=inventory, owner='first', previous=(), result=SimpleNamespace(questions=['one']), packet=None)
    key, inventory = await assessor(journal)._load_prompt_inventory()
    assert worker._prior_prompts(inventory, 'second') == ('one',)
    await worker._record_prompts(key=key, inventory=inventory, owner='second', previous=('one',), result=SimpleNamespace(questions=['two']), packet=None)
    _, restored = await assessor(journal)._load_prompt_inventory()
    assert worker._prior_prompts(restored, 'third') == ('one', 'two')


@pytest.mark.asyncio
async def test_stale_concurrent_writer_is_rejected(monkeypatch):
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    journal = ImmutableJournal()
    first, second = assessor(journal), assessor(journal)
    key_a, inventory_a = await first._load_prompt_inventory()
    key_b, inventory_b = await second._load_prompt_inventory()
    await first._record_prompts(key=key_a, inventory=inventory_a, owner='a', previous=(), result=SimpleNamespace(questions=['one']), packet=None)
    with pytest.raises(ValueError, match='worker_prompt_inventory_stale'):
        await second._record_prompts(key=key_b, inventory=inventory_b, owner='b', previous=(), result=SimpleNamespace(questions=['two']), packet=None)
    _, restored = await assessor(journal)._load_prompt_inventory()
    assert [row['owner'] for row in restored['packets']] == ['a']


@pytest.mark.asyncio
async def test_incomplete_slot_can_resume_and_malformed_chain_is_rejected(monkeypatch):
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    journal = ImmutableJournal()
    key, _ = await assessor(journal)._load_prompt_inventory()
    resume = assessor(journal)
    resumed_key, inventory = await resume._load_prompt_inventory()
    assert resumed_key == key
    await resume._record_prompts(key=key, inventory=inventory, owner='a', previous=(), result=SimpleNamespace(questions=['one']), packet=None)
    journal.values[key]['previous_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='worker_prompt_inventory_version_invalid'):
        await assessor(journal)._load_prompt_inventory()


@pytest.mark.asyncio
async def test_legacy_baseline_survives_and_owner_replay_conflict_fails(monkeypatch):
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    journal = ImmutableJournal()
    worker = assessor(journal)
    _, initial = await worker._load_prompt_inventory()
    legacy_key = next(key for key in journal.plans if ':version:' not in key)
    legacy = {**initial, 'packets': [{'owner': 'old', 'previous_question_prompts': [], 'accepted_question_prompts': ['old-prompt']}]}
    journal.values[legacy_key] = copy.deepcopy(legacy)
    key, restored = await assessor(journal)._load_prompt_inventory()
    assert worker._prior_prompts(restored, 'new') == ('old-prompt',)
    await worker._record_prompts(key=key, inventory=restored, owner='new', previous=('old-prompt',), result=SimpleNamespace(questions=['new-prompt']), packet=None)
    key, restored = await assessor(journal)._load_prompt_inventory()
    with pytest.raises(ValueError, match='worker_prompt_inventory_result_conflict'):
        await worker._record_prompts(key=key, inventory=restored, owner='new', previous=('old-prompt',), result=SimpleNamespace(questions=['different']), packet=None)

@pytest.mark.asyncio
async def test_native_assessor_two_batches_same_lesson(monkeypatch):
    from app.modules.ai.evidence_engine.models import LessonDraft, SourceFact
    from app.modules.ai.lesson_cycle import LessonCycleResult
    from app.modules.ai.source_assessment_plan import SourceAssessmentPlan
    from tests.unit.test_natural_scenario import _packet
    from tests.unit.test_worker_lesson_cycle import Model, checkpoint

    packet = _packet()
    source = packet.sources[0].original_text
    fact = SourceFact('source', 'subject', 'type', source, 'doc_id=qa;part=1')
    lesson = LessonDraft('multi', 'module', 'title', 'objective', source, ('source',), (), 1)
    async def planned(*args, **kwargs):
        return SourceAssessmentPlan(packet.targets, {'source': ('liability',)}, {}, 0, 0, admitted_target_ids=('liability',))
    async def reviewed(packets, **kwargs):
        current = packets[0]
        return [LessonCycleResult(current.tenant_id, current.identity(), current.lesson_id,
                                  'ready_for_methodologist', (), (), 0, 0.0, ())]
    monkeypatch.setattr(cycle, 'build_source_assessment_plan', planned)
    monkeypatch.setattr(cycle, '_assessment_target_batches', lambda admitted: ((admitted, admitted), ()))
    monkeypatch.setattr(cycle, 'run_lesson_cycles', reviewed)
    journal = ImmutableJournal()
    await cycle.WorkerLessonAssessor(tenant_id='qa', client=Model([]), journal=journal,
        checkpoint=checkpoint, learner_language_gate=True)(lesson, {'source': fact})
    restored_worker = cycle.WorkerLessonAssessor(tenant_id='qa', client=Model([]), journal=journal, checkpoint=checkpoint, learner_language_gate=True)
    _, restored = await restored_worker._load_prompt_inventory()
    assert len(restored['packets']) == 2


@pytest.mark.asyncio
async def test_gap_and_incomplete_version_are_rejected(monkeypatch):
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    journal = ImmutableJournal()
    worker = assessor(journal)
    key, inventory = await worker._load_prompt_inventory()
    await worker._record_prompts(key=key, inventory=inventory, owner='a', previous=(), result=SimpleNamespace(questions=['one']), packet=None)
    version = journal.plans.pop(key)
    payload = journal.values.pop(key)
    missing = key.rsplit(':', 1)[0] + ':1'
    version['index'] = 1
    journal.plans[missing] = version
    journal.values[missing] = payload
    with pytest.raises(ValueError, match='worker_prompt_inventory_version_invalid'):
        await assessor(journal)._load_prompt_inventory()
    journal.plans[key] = journal.plans.pop(missing)
    journal.plans[key]['index'] = 0
    journal.values.pop(missing)
    with pytest.raises(ValueError, match='worker_prompt_inventory_version_invalid'):
        await assessor(journal)._load_prompt_inventory()

@pytest.mark.asyncio
async def test_competing_same_slot_results_never_both_commit(monkeypatch):
    import asyncio
    monkeypatch.setattr(cycle, 'question_inventory_key', lambda packet, question: question)
    class RacingJournal(ImmutableJournal):
        def __init__(self):
            super().__init__()
            self.count = 0
            self.both_ready = asyncio.Event()
        async def append_inventory_version(self, key, plan, value):
            self.count += 1
            if self.count == 2:
                self.both_ready.set()
            await self.both_ready.wait()
            return await super().append_inventory_version(key, plan, value)
    journal = RacingJournal()
    workers = [assessor(journal), assessor(journal)]
    first, second = await workers[0]._load_prompt_inventory(), await workers[1]._load_prompt_inventory()
    outcomes = await asyncio.gather(*[
        worker._record_prompts(key=state[0], inventory=state[1], owner=owner, previous=(),
            result=SimpleNamespace(questions=[owner]), packet=None)
        for worker, state, owner in zip(workers, (first, second), ('a', 'b'), strict=True)
    ], return_exceptions=True)
    assert sum(result is None for result in outcomes) == 1
    assert sum(isinstance(result, ValueError) for result in outcomes) == 1
    _, restored = await assessor(journal)._load_prompt_inventory()
    assert len(restored['packets']) == 1
