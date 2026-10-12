from __future__ import annotations

from dataclasses import replace

import pytest
from scripts.dev.course_quality_eval.benchmark import DEFAULT_SUITE, corpus_for_case, load_suite

from app.modules.ai.evidence_engine.application import build_evidence_source, generate_evidence_course
from app.modules.ai.evidence_engine.engine import EvidenceCourseEngine
from app.modules.ai.evidence_engine.models import CourseIntent
from app.modules.ai.evidence_engine.quality import evaluate_plan_preflight


def conflict_case():
    return next(case for case in load_suite(DEFAULT_SUITE) if case["id"] == "conflict-08")


def test_explicit_unresolved_rule_priority_requires_confirmation_before_generation():
    plan = EvidenceCourseEngine().generate_from_document(build_evidence_source(corpus_for_case(conflict_case())).document)
    assert "source_rule_priority_requires_confirmation" in evaluate_plan_preflight(plan)


@pytest.mark.asyncio
async def test_conflicting_source_does_not_spend_provider_calls_or_authorize_one_key():
    class ForbiddenNetwork:
        async def ainvoke_validated(self, *_args, **_kwargs):
            pytest.fail("source conflict must be caught before an LLM call")

        async def embed_documents_with_provenance(self, *_args, **_kwargs):
            pytest.fail("source conflict must be caught before an embedding call")

    with pytest.raises(ValueError, match="source_rule_priority_requires_confirmation"):
        await generate_evidence_course(
            corpus_for_case(conflict_case()), intent=CourseIntent(),
            generation_client=ForbiddenNetwork(), embedding_client=ForbiddenNetwork(),
        )


@pytest.mark.parametrize("notice", [
    "Приоритет между разделами определён. Поэтому этот документ нельзя использовать для автоматического решения без подтверждения владельца.",
    "Приоритет между разделами не определён. Неверно утверждение «этот документ нельзя использовать для автоматического решения».",
    "Приоритет между разделами не определён. Поэтому этот документ можно использовать для автоматического решения.",
])
def test_conditions_quotes_and_positive_permissions_are_not_blindly_blocked(notice):
    plan = EvidenceCourseEngine().generate_from_document(build_evidence_source(corpus_for_case(conflict_case())).document)
    facts = tuple(replace(fact, value=notice) for fact in plan.admitted_facts)
    assert "source_rule_priority_requires_confirmation" not in evaluate_plan_preflight(replace(plan, admitted_facts=facts))
