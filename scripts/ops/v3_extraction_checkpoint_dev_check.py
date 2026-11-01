"""Synthetic V3 journal gate using the canonical disposable DEV schema."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
import ai_generation_realization_dev_check as base

base.SOURCE_PATHS = (
    "apps/api/app/modules/ai/direct_source.py",
    "apps/api/app/modules/ai/pipeline.py",
    "apps/api/app/modules/ai/router.py",
    "apps/api/app/modules/ai/schemas.py",
    "apps/api/app/modules/ai/llm_client.py",
    "apps/api/app/modules/ai/v3/adapter.py",
    "apps/api/app/modules/ai/v3/engine.py",
    "apps/api/app/modules/ai/v3/service.py",
    "apps/api/app/modules/ai/v3/validator.py",
    "apps/api/app/modules/ai/v3/prompts.py",
    "apps/api/app/modules/ai/v3/models.py",
    "apps/api/app/modules/ai/v3/extraction_checkpoint.py",
    "apps/api/app/modules/ai/v3/stage_checkpoint.py",
    "apps/api/app/modules/ai/v3/option_repair.py",
    "apps/api/app/modules/ai/v3/explanation_repair.py",
    "apps/api/app/modules/ai/v3/citation_review.py",
    "apps/api/app/modules/ai/v3/citation_expansion.py",
    "apps/api/app/modules/ai/v3/case_repair_gate.py",
    "apps/api/app/modules/ai/v3/reference_coverage.py",
    "apps/api/app/modules/ai/v3/source_units.py",
    "apps/api/app/modules/ai/v3/partitioned_extraction.py",
    "apps/api/app/modules/ai/v3/source_reference_decisions.py",
    "apps/api/app/modules/ai/worker_lesson_cycle.py",
    "apps/api/app/modules/ai/generation_checkpoint.py",
    "apps/api/app/modules/ai/delivery_ownership.py",
    "apps/api/app/modules/quizzes/models.py",
    "apps/api/app/modules/quizzes/router.py",
    "apps/api/app/modules/quizzes/schemas.py",
    "apps/api/app/modules/quizzes/service.py",
    "apps/api/app/modules/courses/release_service.py",
    "apps/api/app/modules/course_approval/service.py",
    "apps/api/alembic/versions/0184_question_source_quote.py",
    "apps/web/src/app/courses/quiz/[quizId]/preview/page.tsx",
    "apps/web/src/i18n/locales/ru.json",
    "apps/web/src/i18n/locales/en.json",
    "apps/web/src/i18n/locales/kk.json",
    "scripts/ops/ai_generation_checkpoint_dev_check.py",
    "scripts/ops/ai_generation_realization_dev_check.py",
    "scripts/ops/v3_extraction_checkpoint_dev_check.py",
)


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, resume_job: str, checks: list[str]) -> None:
    target_checks = checks
    class ProgressChecks(list[str]):
        def append(self, item: str) -> None:
            target_checks.append(item)
            print(json.dumps({"checkpoint": item}), flush=True)

    progress = ProgressChecks()
    print(json.dumps({"checkpoint": "exercise_started"}), flush=True)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import configure_mappers
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import ai_generation_checkpoint_dev_check as canonical

    from app.models.registry import load_all_models
    from app.modules.ai.delivery_ownership import DeliveryOwnershipLostError, delivery_id
    from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai import pipeline
    from app.modules.ai.evidence_engine.models import CourseIntent
    from app.modules.ai.schemas import SourceReferenceDecisionInput
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError, extract_once
    from app.modules.ai.v3.partitioned_extraction import extract_partitioned_rule_model
    from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, admit_reference_decisions
    from app.modules.ai.v3.models import (DocumentRuleModel, RuleEntity, V3Course, V3Lesson,
                                          V3Option, V3QuestionVariant, V3ScenarioCase)
    from app.modules.ai.v3.explanation_repair import repair_order_dependent_explanations
    from app.modules.ai.v3.citation_review import build_citation_review_items, review_displayed_citations
    from app.modules.ai.v3.validator import has_order_dependent_feedback
    from app.modules.ai.v3.service import (_build_curriculum_groups, _cases_outside_primary_rule_scope,
                                           _lesson_objective_section,
                                           _source_atomic_blocks, _validate_question_entailment,
                                           generate_v3_course_from_corpus)
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    checks = progress
    from app.modules.ai.v3.engine import V3GenerationPipeline

    order_variant = V3QuestionVariant(variant_id="order-v1", branch_context="", scenario_premise="Ситуация",
        prompt="Что делать?", correct_option=V3Option(text="Проверить документ", is_correct=True),
        distractor_pool=(V3Option(text="Отказать", is_correct=False), V3Option(text="Пропустить", is_correct=False),
                         V3Option(text="Передать другому", is_correct=False)),
        explanation="Первый дистрактор неверен.", source_quote="Нужно проверить документ.")
    order_case = V3ScenarioCase(case_id="order-c1", rule_id="r1", learning_objective="Проверка", variants=(order_variant,))
    order_lesson = V3Lesson(lesson_id="order-l1", title="Проверка", module_title="Модуль", content="Правило",
                            covered_rule_ids=("r1",), cases=(order_case,), questions=())

    async def order_model(_messages: Any, _format: Any) -> dict[str, Any]:
        return {"repairs": [{"variant_id": "order-v1", "explanation": "Документ необходимо проверить."}]}

    order_fixed, changed = await repair_order_dependent_explanations(order_lesson, {"r1": ["Нужно проверить документ."]}, order_model)
    assert changed and not has_order_dependent_feedback(order_fixed.cases[0].variants[0].explanation), "order_repair_missing"
    assert order_fixed.cases[0].variants[0].correct_option == order_variant.correct_option, "order_repair_changed_answer"
    assert order_fixed.cases[0].variants[0].distractor_pool == order_variant.distractor_pool, "order_repair_changed_options"
    checks.append("order_independent_explanation")

    citation_source = "Нужно проверить документ."
    citation_doc = DirectSourceDocument(doc_id="citation-doc", title="test", filename="test", category="general",
        source_revision="rev", chunks=(), source_text=citation_source)
    citation_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(citation_doc,),
        total_chars=len(citation_source), total_chunks=0)
    citation_rule = RuleEntity(rule_id="r1", section="s", title="t", statement="x", doc_id="citation-doc",
        source_revision="rev", source_start=0, source_end=len(citation_source), source_quote=citation_source)
    citation_items, citation_issues = build_citation_review_items(order_fixed, [citation_rule], citation_corpus)
    assert len(citation_items) == 1 and not citation_issues, "citation_source_binding_failed"

    async def citation_model(messages: Any, _format: Any) -> dict[str, Any]:
        items = json.loads(messages[1]["content"])["items"]
        return {"items": [{"id": item["id"], "verdict": "PARTIAL", "unsupported": ["missing"],
                            "summary": "incomplete"} for item in items]}

    citation_result = await review_displayed_citations(citation_items, citation_model)
    assert citation_result[citation_items[0]["id"]]["verdict"] == "PARTIAL", "citation_partial_lost"
    checks.append("citation_source_and_partial_contract")

    objective_prompts: list[str] = []

    async def objective_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
        objective_prompts.append(messages[0]["content"])
        return {"verdict": "SUPPORTED"}

    objective_engine = V3GenerationPipeline(objective_model)
    await objective_engine.review_answer("scenario", "question", "answer", ["source"])
    await objective_engine.review_answer("scenario", "question", "answer", ["source"], lesson_claims=True)
    assert "формулировка учебной цели" not in objective_prompts[0], "objective_generic_prompt_changed"
    assert "формулировка учебной цели" in objective_prompts[1], "objective_prompt_missing"
    assert _lesson_objective_section("## Цель урока\nОбучение"), "objective_heading_missing"
    assert not _lesson_objective_section("## Порядок\nНорма"), "objective_heading_overmatched"
    checks.append("lesson_objective_prompt_scope")

    # The temporary schema is created and destroyed by the canonical gate;
    # do not touch the shared questions table or public migration version.
    migration = canonical.load_module("question_quote_migration", ROOT / "apps/api/alembic/versions/0184_question_source_quote.py")
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{schema}".questions (id integer PRIMARY KEY)'))
        for direction in ("upgrade", "downgrade", "upgrade"):
            def apply_migration(sync, step=direction):
                context = MigrationContext.configure(sync, opts={"version_table_schema": schema})
                with Operations.context(context):
                    getattr(migration, step)()
            await conn.run_sync(apply_migration)
            exists = (await conn.execute(text("SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                "WHERE table_schema=:schema AND table_name='questions' AND column_name='source_quote')"),
                {"schema": schema})).scalar_one()
            assert exists is (direction == "upgrade"), "question_quote_migration_shape"
        await conn.execute(text(f'INSERT INTO "{schema}".questions (id, source_quote) VALUES (1, :quote)'),
                           {"quote": "Synthetic source quote"})
        value = (await conn.execute(text(f'SELECT source_quote FROM "{schema}".questions WHERE id=1'))).scalar_one()
        assert value == "Synthetic source quote", "question_quote_readback_failed"
    checks.append("question_quote_migration_readback")

    base_rules = [RuleEntity(rule_id=f"intro-{i}", section="s", title="i", statement="i") for i in range(4)]
    linked = [RuleEntity(rule_id=name, section="s", title=name, statement=name, doc_id="doc-a",
                         source_revision="rev-a", source_start=10, source_end=20) for name in ("condition", "outcome")]
    all_rules = base_rules + linked + [RuleEntity(rule_id="other", section="s", title="o", statement="o")]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="s", document_sha256="a" * 64,
                                                         rules=tuple(all_rules)))
    owners = [group for group in groups if any(rule.rule_id in {"condition", "outcome"} for rule in group.primary_rules)]
    assert len(owners) == 1 and len(owners[0].primary_rules) >= 2, "source_unit_split"
    foreign = RuleEntity(rule_id="foreign", section="s", title="f", statement="f", doc_id="doc-b",
                         source_revision="rev-a", source_start=10, source_end=20)
    assert len(_source_atomic_blocks([linked[0], foreign])) == 2, "cross_document_source_merge"
    scoped_lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
        "lessons": [{"lesson_id": "l", "cases": [{"case_id": "outside", "rule_id": "foreign", "variants": []}]}]}).lessons[0]
    assert _cases_outside_primary_rule_scope(scoped_lesson, linked) == [("outside", "foreign")], "case_scope_signal_missing"
    checks.append("source_unit_atomic_scope")

    from app.modules.ai.v3.service import _verify_rule_quote_grounding
    stale_chunk = DirectSourceChunk(chunk_id="old", doc_id="owned", doc_name="source", title="source", headings=(),
                                    text="Stale inaccurate clause.", source_revision="rev", chunk_index=0)
    canonical_doc = DirectSourceDocument(doc_id="owned", title="source", filename="s", category="general",
                                         source_revision="rev", chunks=(stale_chunk,), source_text="Current accurate clause.")
    canonical_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(canonical_doc,), total_chars=24, total_chunks=1)
    stale_rule = RuleEntity(rule_id="r", section="s", title="t", statement="s", source_quote="Stale inaccurate clause.",
                            doc_id="owned", source_revision="rev")
    assert not _verify_rule_quote_grounding(stale_rule, canonical_corpus)[0], "stale_quote_falsely_certified"
    full_source = "First target. Neighbor clause."
    owned_chunk = DirectSourceChunk(chunk_id="current", doc_id="owned", doc_name="source", title="source", headings=(),
                                    text=full_source, source_revision="rev", chunk_index=0)
    owned_doc = DirectSourceDocument(doc_id="owned", title="source", filename="s", category="general",
                                     source_revision="rev", chunks=(owned_chunk,), source_text=full_source)
    owned_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(owned_doc,), total_chars=len(full_source), total_chunks=1)
    wrong_unit = RuleEntity(rule_id="r", section="s", title="t", statement="s", source_quote="Neighbor clause.",
                            doc_id="owned", source_revision="rev", source_start=0, source_end=len("First target."))
    assert not _verify_rule_quote_grounding(wrong_unit, owned_corpus)[0], "neighbor_quote_falsely_certified"
    checks.append("canonical_quote_guard")
    large_rows = [RuleEntity(rule_id=f"row-{index}", section="s", title=f"row {index}", statement="Synthetic",
                             doc_id="doc-a", source_revision="rev-a", source_family="table-large",
                             source_topic=f"topic-{index}", source_start=index * 1000, source_end=index * 1000 + 900)
                  for index in range(100)]
    large_rows.append(RuleEntity(rule_id="shared-note", section="s", title="note", statement="Synthetic note",
        doc_id="doc-a", source_revision="rev-a", source_family="table-large", source_start=100000, source_end=100100))
    large_groups = _build_curriculum_groups(DocumentRuleModel(document_title="large", document_sha256="a" * 64,
                                                               rules=tuple(large_rows)))
    assert len(large_groups) > 1 and sum(len(g.primary_rules) for g in large_groups) == len(large_rows), "large_table_lost_or_unsplit"
    assert all(any(rule.rule_id == "shared-note" for rule in g.primary_rules + g.context_neighbor_rules
                   + g.context_prerequisite_rules) for g in large_groups), "large_table_note_lost"
    assert all(len(g.context_neighbor_rules) <= 13 and g.unresolved_dependencies for g in large_groups), "large_table_context_unbounded"
    checks.append("large_table_split_scope")

    from app.modules.ai.v3.service import _lesson_claim_table_parts
    claim_table = "## Synthetic table\n| Condition | Action |\n|---|---|\n" + "".join(
        f"| Condition {i} | Action {i} |\n" for i in range(1, 8))
    claim_table_parts = _lesson_claim_table_parts(claim_table)
    assert len(claim_table_parts) == 3 and "".join(part for part, _ in claim_table_parts) == claim_table, "claim_table_text_lost"
    assert all("| Condition | Action |" in context for _, context in claim_table_parts[1:]), "claim_table_header_lost"
    assert all(sum(f"Condition {i}" in part for part, _ in claim_table_parts) == 1 for i in range(1, 8)), "claim_table_row_lost"
    checks.append("claim_table_row_context")

    from app.modules.ai.v3.service import _lesson_claim_subparts
    claim_examples = "## Examples\n" + "".join(f"### Example {i}\nAction {i}.\n" for i in range(1, 6))
    example_parts = _lesson_claim_subparts(claim_examples)
    assert len(example_parts) == 2 and "".join(part for part, _ in example_parts) == claim_examples, "claim_examples_text_lost"
    assert example_parts[1][1] == "## Examples", "claim_examples_parent_lost"
    checks.append("claim_subsection_context")

    load_all_models()
    configure_mappers()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    journal = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    identity = {"tenant_id": str(tenant_a), "job_id": job_a, "document_id": "synthetic-doc",
                "source_revision": "synthetic-revision", "source_sha256": "a" * 64,
                "unit_sha256": "b" * 64, "context_sha256": "c" * 64,
                "prompt_sha256": "d" * 64, "route_fingerprint": "e" * 64,
                "unit_start": "0", "unit_end": "10"}
    calls: list[int] = []

    async def invoke() -> dict[str, Any]:
        calls.append(1)
        return {"rules": [{"rule_id": "synthetic-rule", "statement": "synthetic", "source_quote": "synthetic"}]}

    token = delivery_id.set(job_a)
    try:
        first = await extract_once(journal, identity, invoke)
        cold = WorkerCycleJournal(str(tenant_a), job_a, sessions)
        assert await extract_once(cold, identity, invoke) == first and len(calls) == 1, "cold_replay"
        checks.append("cold_replay")

        async def timeout() -> dict[str, Any]:
            calls.append(2)
            raise TimeoutError("synthetic")

        other = identity | {"unit_sha256": "f" * 64}
        try:
            await extract_once(cold, other, timeout)
        except TimeoutError:
            pass
        else:
            raise AssertionError("timeout_not_observed")
        try:
            await extract_once(cold, other, timeout)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("unknown_retried")
        assert calls == [1, 2], "provider_called_again"
        checks.append("unknown_not_retried")

        started, release = asyncio.Event(), asyncio.Event()
        concurrent_calls: list[int] = []

        async def slow() -> dict[str, Any]:
            concurrent_calls.append(1)
            started.set()
            await release.wait()
            return {"rules": [{"rule_id": "race", "statement": "synthetic", "source_quote": "synthetic"}]}

        race_identity = identity | {"unit_sha256": "2" * 64}
        first_task = asyncio.create_task(extract_once(journal, race_identity, slow))
        try:
            await asyncio.wait_for(started.wait(), timeout=30)
            try:
                await extract_once(cold, race_identity, slow)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("concurrent_request_started")
        finally:
            release.set()
            await asyncio.wait_for(first_task, timeout=30)
        assert concurrent_calls == [1], "concurrent_provider_called_twice"
        checks.append("concurrent_single_call")

        source = "First synthetic obligation.\n\nSecond synthetic obligation."
        chunk = DirectSourceChunk(chunk_id="synthetic-chunk", doc_id="synthetic-doc", doc_name="synthetic",
                                  title="synthetic", headings=(), text=source, source_revision="synthetic-revision", chunk_index=0)
        document = DirectSourceDocument(doc_id="synthetic-doc", title="synthetic", filename="synthetic",
                                        category="general", source_revision="synthetic-revision", chunks=(chunk,), source_text=source)
        corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(document,), total_chars=len(source), total_chunks=1)
        part_calls: list[str] = []

        async def extract(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            part_calls.append(target)
            return {"rules": [{"rule_id": target, "statement": target, "source_quote": target}]}

        model, warnings = await extract_partitioned_rule_model(corpus, journal, "e" * 64, extract)
        reloaded, _ = await extract_partitioned_rule_model(corpus, cold, "e" * 64, extract)
        assert len(model.rules) == 2 and model == reloaded and len(part_calls) == 2, "partition_replay"
        assert warnings, "dependency_warning_missing"
        checks.append("partition_replay")

        table_text = "1. Conditions:\n\n| Type | Value |\n| --- | --- |\n| A | 1 |\n| B | 2 |\n\n*\\*Footnote applies to both.\n"
        table_document = DirectSourceDocument(doc_id="synthetic-table-doc", title="synthetic table", filename="s",
            category="general", source_revision="synthetic-table-revision", chunks=(), source_text=table_text)
        table_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(table_document,),
                                         total_chars=len(table_text), total_chunks=0)
        table_calls: list[int] = []

        async def table_extract(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
            table_calls.append(1)
            return {"rules": [{"rule_id": f"table-rule-{len(table_calls)}", "statement": target,
                               "source_quote": target}]}

        table_model, _ = await extract_partitioned_rule_model(table_corpus, journal, "3" * 64, table_extract)
        prior_calls = len(table_calls)
        table_replay, _ = await extract_partitioned_rule_model(table_corpus, cold, "3" * 64, table_extract)
        assert table_model == table_replay and len(table_calls) == prior_calls >= 3, "table_family_replay_failed"
        assert len({rule.source_family for rule in table_model.rules}) == 1 and table_model.rules[0].source_family, "table_family_detached"
        checks.append("table_leadin_note_replay")

        formatting_text = "Do not issue<br>without **approval**."
        formatting_document = DirectSourceDocument(doc_id="format-doc", title="format", filename="s", category="general",
            source_revision="format-rev", chunks=(), source_text=formatting_text)
        formatting_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(formatting_document,),
                                               total_chars=len(formatting_text), total_chunks=0)
        formatting_calls: list[int] = []

        async def formatting_extract(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            formatting_calls.append(1)
            return {"rules": [{"rule_id": "format", "statement": "condition", "source_quote": "Do not issue without approval."}]}

        formatting_model, formatting_warnings = await extract_partitioned_rule_model(formatting_corpus, journal, "4" * 64, formatting_extract)
        formatting_replay, _ = await extract_partitioned_rule_model(formatting_corpus, cold, "4" * 64, formatting_extract)
        assert formatting_model == formatting_replay and formatting_calls == [1], "formatting_replay_failed"
        assert formatting_model.rules[0].source_quote == formatting_text, "formatting_quote_not_bound"
        assert any("SHA256=" in warning for warning in formatting_warnings), "formatting_review_signal_missing"
        checks.append("rendered_rule_quote_replay")

        stage_calls: list[int] = []

        async def lesson() -> dict[str, Any]:
            stage_calls.append(1)
            return {"title": "Synthetic lesson", "content": "Synthetic content"}

        stage_args = {"stage": "lesson", "group_id": "synthetic-group", "source_sha256": "a" * 64,
                      "route_fingerprint": "e" * 64, "messages": [{"role": "user", "content": "synthetic"}],
                      "response_format": {"type": "json_object"}, "invoke": lesson}
        lesson_first = await stage_once(journal, **stage_args)
        assert await stage_once(cold, **stage_args) == lesson_first and len(stage_calls) == 1, "stage_replay"
        checks.append("stage_replay")

        async def repair() -> dict[str, Any]:
            stage_calls.append(3)
            return {"repairs": [{"variant_id": "synthetic"}]}

        repair_args = stage_args | {"stage": "repair", "invoke": repair}
        repair_first = await stage_once(journal, **repair_args)
        assert await stage_once(cold, **repair_args) == repair_first and stage_calls == [1, 3], "repair_replay"
        checks.append("repair_stage_replay")

        from app.modules.ai.v3.option_repair import repair_options
        partial_lesson = V3Course.from_dict({"course_id": "partial", "title": "partial", "document_sha256": "a" * 64,
            "lessons": [{"lesson_id": "partial", "title": "partial", "content": "source", "cases": [
                {"case_id": "c", "rule_id": "r", "variants": [
                    {"variant_id": variant, "prompt": "question", "correct_option": {"text": "right"},
                     "source_quote": "source", "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}
                    for variant in ("v1", "v2")]}]}]}).lessons[0]
        partial_calls: list[int] = []

        async def partial_provider() -> dict[str, Any]:
            partial_calls.append(1)
            return {"repairs": [{"variant_id": "v1", "correct": "right", "explanation": "checked",
                                 "distractors": [{"text": text, "category": "procedural_confusion"}
                                                 for text in ("a", "b", "c")]}]}

        async def partial_run(active_journal: Any) -> Any:
            async def invoke(messages: Any, response_format: Any) -> dict[str, Any]:
                return await stage_once(active_journal, stage="repair", group_id="partial-test", source_sha256="a" * 64,
                                        route_fingerprint="2" * 64, messages=messages, response_format=response_format,
                                        invoke=partial_provider)
            return await repair_options(partial_lesson, ["synthetic structural issue"], ["source"], invoke,
                                        accept_partial=lambda _: True)

        partial_first = await partial_run(journal)
        partial_replay = await partial_run(cold)
        assert partial_first == partial_replay and len(partial_calls) == 1, "partial_repair_replay_failed"
        assert partial_first.cases[0].variants[1] == partial_lesson.cases[0].variants[1], "partial_variant_lost"
        checks.append("partial_repair_replay")

        started, release = asyncio.Event(), asyncio.Event()

        async def slow_stage() -> dict[str, Any]:
            stage_calls.append(2)
            started.set()
            await release.wait()
            return {"verdict": "PASS"}

        stage_race = stage_args | {"stage": "review", "invoke": slow_stage}
        task = asyncio.create_task(stage_once(journal, **stage_race))
        try:
            await asyncio.wait_for(started.wait(), timeout=30)
            try:
                await stage_once(cold, **stage_race)
            except ExtractionOutcomeUnknownError:
                pass
            else:
                raise AssertionError("concurrent_stage_started")
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=30)
        assert stage_calls == [1, 3, 2], "concurrent_stage_called_twice"
        checks.append("concurrent_stage_single_call")

        lesson_claim_calls: list[str] = []
        pipeline_calls: list[str] = []

        async def pipeline_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            system = messages[0]["content"]
            if "Фактические утверждения текста урока" in messages[1]["content"]:
                lesson_claim_calls.append("review")
                return {"verdict": "SUPPORTED", "claims": [{"claim": "source", "status": "SUPPORTED", "reason": "source"}],
                        "summary": "Synthetic lesson claims checked."}
            if "Карту регламента" in system:
                target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
                pipeline_calls.append("extract")
                return {"rules": [{"rule_id": target, "section": "Synthetic section", "title": target,
                                   "statement": target, "source_quote": target}]}
            if "независимый контролер" in system:
                pipeline_calls.append("review")
                raise TimeoutError("synthetic review outcome unknown")
            pipeline_calls.append("lesson")
            return {"lesson_id": "synthetic-lesson", "title": "Synthetic", "module_title": "Synthetic",
                    "content": source, "cases": []}

        async def generate_with(active_journal: Any, allow_unreviewed: bool = False) -> Any:
            return await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=pipeline_model,
                extraction_journal=active_journal, route_fingerprint="f" * 64,
                allow_unreviewed_on_unknown=allow_unreviewed)

        try:
            await generate_with(journal)
        except TimeoutError:
            pass
        else:
            raise AssertionError("pipeline_timeout_not_observed")
        assert pipeline_calls == ["extract", "extract", "lesson", "review"], "pipeline_first_call_sequence"
        try:
            await generate_with(cold)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("pipeline_unknown_review_retried")
        assert pipeline_calls == ["extract", "extract", "lesson", "review"], "pipeline_duplicate_calls"
        checks.append("pipeline_review_timeout_resume")
        partial = await generate_with(cold, True)
        assert pipeline_calls == ["extract", "extract", "lesson", "review"], "qa_unknown_retried"
        assert partial.diagnostics["requires_source_review"], "qa_unknown_not_held"
        assert "неизвест" in " ".join(partial.diagnostics["violations"]).lower(), "qa_unknown_not_visible"
        checks.append("qa_unknown_review_no_retry_hold")

        semantic_calls: list[str] = []

        async def semantic_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            system = messages[0]["content"]
            if "Фактические утверждения текста урока" in messages[1]["content"]:
                lesson_claim_calls.append("review")
                return {"verdict": "SUPPORTED", "claims": [{"claim": "source", "status": "SUPPORTED", "reason": "source"}],
                        "summary": "Synthetic lesson claims checked."}
            if "Карту регламента" in system:
                target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
                semantic_calls.append("extract")
                return {"rules": [{"rule_id": target, "section": "Synthetic section", "title": target,
                                   "statement": target, "source_quote": target}]}
            if "Проверь каждое фактическое утверждение" in system:
                semantic_calls.append("answer")
                assert "First synthetic obligation." in messages[1]["content"], "answer_source_missing"
                options = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
                return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": "CONTRADICTED",
                                     "claims": [{"claim": "synthetic", "status": "CONTRADICTED", "reason": "source"}],
                                     "summary": "Synthetic answer contradicts source."} for item in options]}
            if "независимый контролер" in system:
                semantic_calls.append("review")
                return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                        "summary": "Synthetic review passed.", "defects": []}
            semantic_calls.append("lesson")
            return {"lesson_id": "synthetic-lesson-2", "title": "Synthetic", "module_title": "Synthetic",
                    "content": source, "cases": [{"case_id": "synthetic-case", "rule_id": "First synthetic obligation.",
                        "variants": [{"variant_id": "synthetic-question", "prompt": "Synthetic question?",
                                      "correct_option": {"text": "Synthetic wrong answer"},
                                      "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}]}]}

        async def check_semantics(active_journal: Any) -> Any:
            return await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=semantic_model,
                                                        extraction_journal=active_journal, route_fingerprint="d" * 64)

        semantic_result = await check_semantics(journal)
        assert "ожидался SUPPORTED, получен CONTRADICTED" in " ".join(semantic_result.diagnostics["violations"]), "answer_defect_lost"
        assert semantic_result.diagnostics["requires_source_review"], "answer_false_pass"
        before_replay = list(semantic_calls)
        await check_semantics(cold)
        assert semantic_calls == before_replay and "answer" in semantic_calls, "semantic_replay_failed"
        checks.append("pipeline_answer_contradiction_replay")

        statuses = ("SUPPORTED", "CONTRADICTED", "CONTRADICTED", "CONTRADICTED")
        incomplete_review = {"options": [{"index": i, "verdict": status,
            "claims": [{"claim": "action", "status": status, "reason": "source"}], "summary": "checked",
            "omitted_required_elements": ["required actor"] if i == 0 else []}
            for i, status in enumerate(statuses)]}
        assert not _validate_question_entailment(incomplete_review, [True, False, False, False])[0], "omission_accepted"
        incomplete_review["options"][0]["omitted_required_elements"] = []
        assert _validate_question_entailment(incomplete_review, [True, False, False, False])[0], "complete_rejected"
        checks.append("question_completeness_contract")

        from app.modules.ai.v3.option_repair import repair_distractor_feedback

        feedback_lesson = V3Course.from_dict({"course_id": "c", "title": "t", "lessons": [
            {"lesson_id": "l", "cases": [{"case_id": "c", "variants": [{"variant_id": "v",
                "correct_option": {"text": "right"}, "distractor_pool": [
                    {"text": "unclear"}, {"text": "false"}, {"text": "other"}]}]}]}]}).lessons[0]
        variant = feedback_lesson.cases[0].variants[0]
        selected = next(i for i, option in enumerate(variant.assemble_question(seed=111).options)
                        if option.text == "unclear")
        feedback_calls: list[int] = []

        async def feedback_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            feedback_calls.append(1)
            sent = json.loads(messages[1]["content"])
            return {"repairs": [{"index": sent["feedback"][0]["index"], "replacement": "incorrect"}]}

        async def feedback_run(active_journal: Any) -> Any:
            async def checkpointed(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
                return await stage_once(active_journal, stage="repair", group_id="feedback-case",
                    source_sha256="a" * 64, route_fingerprint="f" * 64, messages=messages,
                    response_format=response_format, invoke=lambda: feedback_model(messages, response_format))
            return await repair_distractor_feedback(feedback_lesson, "v",
                [{"index": selected, "verdict": "UNCERTAIN", "summary": "unsupported condition"}],
                ["source"], checkpointed)

        feedback_first = await feedback_run(journal)
        feedback_replay = await feedback_run(cold)
        assert feedback_first == feedback_replay and feedback_calls == [1], "distractor_feedback_replay_failed"
        assert feedback_first.cases[0].variants[0].correct_option == variant.correct_option, "correct_answer_changed"
        checks.append("distractor_feedback_replay")

        repair_flow_calls: list[str] = []
        compatibility_ambiguous = False
        semantic_ambiguity = False
        unsafe_repair = False

        async def repair_flow_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            system = messages[0]["content"]
            if "Фактические утверждения текста урока" in messages[1]["content"]:
                lesson_claim_calls.append("review")
                return {"verdict": "SUPPORTED", "claims": [{"claim": "source", "status": "SUPPORTED", "reason": "source"}],
                        "summary": "Synthetic lesson claims checked."}
            if "Карту регламента" in system:
                target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
                repair_flow_calls.append("extract")
                return {"rules": [{"rule_id": target, "section": "Synthetic section", "title": target,
                                   "statement": target, "source_quote": target}]}
            if "Для каждого вопроса замени только три неверных варианта" in system:
                repair_flow_calls.append("repair")
                submitted = json.loads(messages[1]["content"])["questions"]
                wrong = ("wrong", "other synthetic false action xxxxxxxxxxxx",
                         "false synthetic improper action xxxxxxxxx")
                return {"repairs": [{"variant_id": item["variant_id"],
                    "distractors": [{"text": text, "category": "procedural_confusion"} for text in wrong]}
                    for item in submitted]}
            if "Исправь только варианты" in system:
                repair_flow_calls.append("repair")
                submitted = json.loads(messages[1]["content"].split("ИСХОДНЫЕ ВАРИАНТЫ:\n", 1)[1])
                ids = [item["variant_id"] for item in submitted]
                wrong = (("fixed", "other synthetic false action xxxxxxxxxxxx", "false synthetic improper action xxxxxxxxx")
                         if semantic_ambiguity and len(ids) == 1 else
                         ("wrong", "other synthetic false action xxxxxxxxxxxx", "false synthetic improper action xxxxxxxxx"))
                return {"repairs": [{"variant_id": v, "correct": ("newer" if unsafe_repair and semantic_ambiguity and len(ids) == 1 else "very long synthetic correct answer"), "explanation": "Synthetic rationale",
                                     "distractors": [{"text": text, "category": "procedural_confusion"}
                                                     for text in wrong]}
                                    for v in ids]}
            if "Проверь каждое фактическое утверждение" in system:
                repair_flow_calls.append("options")
                options = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
                return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "very long synthetic correct answer" else "CONTRADICTED"),
                                     "claims": [{"claim": "synthetic", "status": status, "reason": "source"}],
                                     "summary": "Synthetic option checked."} for item in options]}
            if "Проверь совместимость описанного" in system:
                repair_flow_calls.append("compatibility")
                options = json.loads(messages[1]["content"].split("ВАРИАНТЫ:\n", 1)[1])
                return {"options": [{"omitted_required_elements": [], "index": item["index"], "verdict": (status := "SUPPORTED" if item["text"] == "very long synthetic correct answer" else ("UNCERTAIN" if compatibility_ambiguous and item["text"] == "wrong" else "CONTRADICTED")),
                                     "claims": [{"claim": "synthetic", "status": status, "reason": "source"}],
                                     "summary": "Synthetic option checked."} for item in options]}
            if "Сравни каждый ответ с источником и вопросом" in system:
                repair_flow_calls.append("completeness")
                payload = json.loads(messages[1]["content"])
                assert len(payload["answers"]) == 1 and "is_correct" not in messages[1]["content"], "completeness_input_invalid"
                return {"answers": [{"index": 0, "omissions": []}]}
            if "показанная цитата" in system:
                repair_flow_calls.append("citation")
                payload = json.loads(messages[1]["content"])
                return {"items": [{"id": item["id"], "verdict": "COMPLETE", "unsupported": [],
                                   "summary": "Synthetic citation checked."} for item in payload["items"]]}
            if "независимый контролер" in system:
                repair_flow_calls.append("review")
                defects = ([{"scope": "question", "question_id": "c1", "issue": "Ambiguous distractor"}]
                           if semantic_ambiguity and '"case_id":"c1"' in messages[1]["content"]
                           and '"wrong"' in messages[1]["content"] else [])
                return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                        "summary": "Synthetic review passed.", "defects": defects}
            repair_flow_calls.append("lesson")
            assert "ТОЧНЫЕ ИСХОДНЫЕ ФРАГМЕНТЫ ОСНОВНОЙ ТЕМЫ" in messages[1]["content"], "lesson_missing_primary_source"
            assert "First synthetic obligation." in messages[1]["content"] and "Second synthetic obligation." in messages[1]["content"], "lesson_source_incomplete"
            return {"lesson_id": "synthetic-repair-lesson", "title": "Synthetic", "module_title": "Synthetic",
                    "content": source, "cases": [{"case_id": f"c{i}", "rule_id": rule,
                        "variants": [{"variant_id": f"v{i}", "prompt": "Synthetic question?",
                                      "correct_option": {"text": "very long synthetic correct answer"},
                                      "source_quote": rule,
                                      "distractor_pool": [{"text": "a"}, {"text": "b"}, {"text": "c"}]}]}
                        for i, rule in ((1, "First synthetic obligation."), (2, "Second synthetic obligation."))]}

        async def check_repair_flow(active_journal: Any, fingerprint: str = "c" * 64) -> Any:
            return await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=repair_flow_model,
                                                        extraction_journal=active_journal, route_fingerprint=fingerprint)

        claims_before_repair = len(lesson_claim_calls)
        repair_result = await check_repair_flow(journal)
        assert len(lesson_claim_calls) == claims_before_repair + 1, "lesson_claim_review_missing"
        assert (repair_flow_calls.count("repair") == 1 and repair_flow_calls.count("options") == 2
                and repair_flow_calls.count("compatibility") == 2), "repair_flow_missing"
        assert "completeness" in repair_flow_calls, "completeness_stage_missing"
        assert any("отредактированы" in warning for warning in repair_result.content.source_warnings), "repair_signal_missing"
        repair_before = list(repair_flow_calls)
        await check_repair_flow(cold)
        assert repair_flow_calls == repair_before, "repair_flow_replayed_provider"
        checks.append("pipeline_option_repair_replay")
        checks.append("lesson_exact_source_context")
        assert len(lesson_claim_calls) == claims_before_repair + 1, "lesson_claim_review_replayed"
        checks.append("lesson_claim_review_replay")

        compatibility_ambiguous = True
        ambiguous_result = await check_repair_flow(journal, "e" * 64)
        assert "проверка совместимости" in " ".join(ambiguous_result.diagnostics["violations"]), "compatibility_defect_lost"
        assert ambiguous_result.diagnostics["requires_source_review"], "compatibility_false_pass"
        ambiguous_before = list(repair_flow_calls)
        await check_repair_flow(cold, "e" * 64)
        assert repair_flow_calls == ambiguous_before, "compatibility_replayed_provider"
        checks.append("pipeline_compatibility_ambiguity_replay")

        compatibility_ambiguous = False
        semantic_ambiguity = True
        semantic_repaired = await check_repair_flow(journal, "9" * 64)
        repairs = semantic_repaired.diagnostics["validation_report"]["semantic_repairs"]
        assert len(repairs) == 1 and repairs[0]["case_id"] == "c1", "semantic_repair_missing"
        assert repairs[0]["original_review"]["defects"] and not repairs[0]["recheck"]["defects"], "semantic_recheck_missing"
        semantic_before = list(repair_flow_calls)
        await check_repair_flow(cold, "9" * 64)
        assert repair_flow_calls == semantic_before, "semantic_repair_replayed_provider"
        checks.append("pipeline_semantic_repair_replay")

        unsafe_repair = True
        rejected_result = await check_repair_flow(journal, "8" * 64)
        rejected = rejected_result.diagnostics["validation_report"]["semantic_repairs"]
        assert len(rejected) == 1 and rejected[0]["rejected"] == "v3_semantic_repair_changed_correct_answer", "unsafe_repair_not_recorded"
        assert rejected[0]["original_review"]["defects"], "unsafe_repair_original_review_lost"
        assert rejected_result.diagnostics["requires_source_review"], "unsafe_repair_not_held"
        rejected_before = list(repair_flow_calls)
        await check_repair_flow(cold, "8" * 64)
        assert repair_flow_calls == rejected_before, "unsafe_repair_replayed_provider"
        checks.append("unsafe_repair_rejected_replay")
        unsafe_repair = False

        decision_calls: list[str] = []
        decision = SourceReferenceDecision(
            tenant_id=str(tenant_a), document_id="synthetic-doc", source_revision="synthetic-revision",
            converted_text_sha256=hashlib.sha256(source.encode()).hexdigest(),
            reference_start=0, reference_end=5, reference_exact="First",
            target_start=source.index("Second"), target_end=source.index("Second") + 6,
            target_exact="Second", authority="owner_chat")

        async def decision_model(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            system = messages[0]["content"]
            if "Фактические утверждения текста урока" in messages[1]["content"]:
                lesson_claim_calls.append("review")
                return {"verdict": "SUPPORTED", "claims": [{"claim": "source", "status": "SUPPORTED", "reason": "source"}],
                        "summary": "Synthetic lesson claims checked."}
            if "Карту регламента" in system:
                target = messages[1]["content"].split("ЦЕЛЕВОЙ ФРАГМЕНТ:", 1)[1].strip()
                decision_calls.append("extract")
                return {"rules": [{"rule_id": target, "statement": target, "source_quote": target}]}
            if "независимый контролер" in system:
                decision_calls.append("review")
                assert "Second" in messages[1]["content"], "decision_review_context_missing"
                return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5, "didactic_score": 5,
                        "summary": "Synthetic review passed.", "defects": []}
            decision_calls.append("lesson")
            assert "УТОЧНЕНИЯ ССЫЛОК" in messages[1]["content"], "decision_lesson_context_missing"
            return {"lesson_id": "synthetic-decision", "title": "Synthetic", "module_title": "Synthetic",
                    "content": source, "cases": []}

        async def check_decision(active_journal: Any) -> Any:
            return await generate_v3_course_from_corpus(corpus, intent=CourseIntent(), generation_client=decision_model,
                extraction_journal=active_journal, route_fingerprint="b" * 64, reference_decisions=(decision,))

        decision_result = await check_decision(journal)
        assert decision_result.diagnostics["requires_source_review"], "decision_review_hold_missing"
        decision_before = list(decision_calls)
        await check_decision(cold)
        assert decision_calls == decision_before, "decision_replayed_provider"
        checks.append("pipeline_source_decision_replay")

        link_text = "Порядок: см. п. 2.\n2. Подписать билет и внести отметку."
        link_ref = "см. п. 2"
        link_target = "Подписать билет и внести отметку."
        link_chunk = DirectSourceChunk(chunk_id="link-chunk", doc_id="link-doc", doc_name="synthetic",
            title="synthetic", headings=(), text=link_text, source_revision="link-rev", chunk_index=0)
        link_doc = DirectSourceDocument(doc_id="link-doc", title="synthetic", filename="synthetic", category="general",
            source_revision="link-rev", chunks=(link_chunk,), source_text=link_text)
        link_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(link_doc,), total_chars=len(link_text), total_chunks=1)
        ref_start, target_start = link_text.index(link_ref), link_text.index(link_target)
        link_decision = SourceReferenceDecision(tenant_id=str(tenant_a), document_id="link-doc", source_revision="link-rev",
            converted_text_sha256=hashlib.sha256(link_text.encode()).hexdigest(), reference_start=ref_start,
            reference_end=ref_start+len(link_ref), reference_exact=link_ref, target_start=target_start,
            target_end=target_start+len(link_target), target_exact=link_target, authority="owner_chat")
        common = {"doc_id": "link-doc", "source_revision": "link-rev", "source_start": 0, "source_end": len(link_text)}
        referring = RuleEntity(rule_id="ref", section="ref", title="ref", statement="См. п. 2",
                               source_quote="Порядок: см. п. 2.", **common)
        destination = RuleEntity(rule_id="target", section="target", title="target", statement=link_target,
                                 source_quote=link_target, **common)
        link_model = DocumentRuleModel(document_title="synthetic", document_sha256="a" * 64,
                                       rules=(referring, destination))
        link_group = next(group for group in _build_curriculum_groups(link_model, corpus=link_corpus,
                          reference_decisions=(link_decision,)) if referring in group.primary_rules)
        assert not link_group.unresolved_dependencies and destination in link_group.context_prerequisite_rules, "confirmed_link_lost"
        checks.append("confirmed_reference_link")

        duplicated_ref = RuleEntity(rule_id="ref", section="ref", title="ref", statement="См. п. 2",
                                    conditions=("Дополнительно см. п. 2",),
                                    source_quote="Порядок: см. п. 2.", **common)
        duplicated_model = DocumentRuleModel(document_title="synthetic", document_sha256="a" * 64,
                                             rules=(duplicated_ref, destination))
        duplicate_group = next(group for group in _build_curriculum_groups(duplicated_model, corpus=link_corpus,
                               reference_decisions=(link_decision,)) if duplicated_ref in group.primary_rules)
        assert any("пункт '2'" in issue for issue in duplicate_group.unresolved_dependencies), "cross_field_reference_false_resolution"
        assert destination in duplicate_group.context_prerequisite_rules, "confirmed_source_edge_lost"
        checks.append("confirmed_reference_cross_field_hold")

        numbered_destination = RuleEntity(rule_id="target", section="target", title="пункт 2", statement=link_target,
                                          source_quote=link_target, **common)
        numbered_model = DocumentRuleModel(document_title="synthetic", document_sha256="a" * 64,
                                           rules=(duplicated_ref, numbered_destination))
        numbered_group = next(group for group in _build_curriculum_groups(numbered_model, corpus=link_corpus,
                              reference_decisions=(link_decision,)) if duplicated_ref in group.primary_rules)
        assert numbered_destination in numbered_group.context_prerequisite_rules, "numbered_source_edge_lost"
        assert any("пункт '2'" in issue for issue in numbered_group.unresolved_dependencies), "numbered_reference_false_resolution"
        checks.append("confirmed_source_edge_with_unbound_model_occurrences")

        synthetic_document_id = str(uuid4())
        async with sessions() as session:
            await session.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_a)})
            actor = (await session.execute(text("SELECT user_id FROM ai_jobs WHERE id=:id"), {"id": job_a})).scalar_one()
            submitted = SourceReferenceDecisionInput(document_id=synthetic_document_id,
                source_revision="document:" + "a" * 64, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest(),
                reference_start=0, reference_end=5, reference_exact="First",
                target_start=source.index("Second"), target_end=source.index("Second") + 6,
                target_exact="Second", confirmed=True)
            records = admit_reference_decisions([submitted], str(tenant_a), str(actor), [synthetic_document_id])
            params = {"documents": [synthetic_document_id], "reference_decisions": records}
            await session.execute(text("UPDATE ai_jobs SET params=CAST(:params AS json) WHERE id=:id"),
                                  {"params": json.dumps(params), "id": job_a})
            await session.commit()
        previous_factory = pipeline.async_session_factory
        pipeline.async_session_factory = sessions
        try:
            loaded = await pipeline._load_owned_reference_decisions(job_a, tenant_a, actor, [synthetic_document_id])
            assert len(loaded) == 1 and loaded[0].approved_by == str(actor), "owned_decision_not_loaded"
            try:
                await pipeline._load_owned_reference_decisions(job_a, tenant_a, uuid4(), [synthetic_document_id])
            except pipeline.GenerationJobOwnerMismatchError:
                pass
            else:
                raise AssertionError("foreign_decision_actor_accepted")
        finally:
            pipeline.async_session_factory = previous_factory
        checks.append("owned_job_decision_readback")

        for bad in (identity | {"tenant_id": str(tenant_b)}, identity | {"job_id": resume_job}):
            try:
                await extract_once(cold, bad, invoke)
            except ValueError:
                pass
            else:
                raise AssertionError("foreign_identity_accepted")
        checks.append("foreign_identity_denied")
    finally:
        delivery_id.reset(token)

    token = delivery_id.set("foreign-delivery")
    try:
        try:
            await extract_once(journal, identity | {"unit_sha256": "1" * 64}, invoke)
        except DeliveryOwnershipLostError:
            pass
        else:
            raise AssertionError("stale_delivery_accepted")
        checks.append("stale_delivery_denied")
    finally:
        delivery_id.reset(token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-public-revision")
    parser.add_argument("--custody", type=Path)
    parser.add_argument("--pooled", action="store_true", help="Use bounded reusable connections in the synthetic DEV gate")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "OFFLINE_PREFLIGHT", "source_sha256": base.source_digest()}))
        return 0
    try:
        if args.custody is None or not args.custody.parent.is_dir() or args.custody.is_symlink():
            raise ValueError("custody_invalid")
        if not args.custody.resolve().is_relative_to((ROOT / ".release-evidence").resolve(strict=True)):
            raise ValueError("custody_outside_evidence")
        base.exercise = exercise
        import ai_generation_checkpoint_dev_check as canonical

        original_engine_factory = canonical.create_async_engine

        def pooled_engine(*engine_args: Any, **engine_kwargs: Any) -> Any:
            engine_kwargs.pop("poolclass", None)
            engine_kwargs.update(pool_size=2, max_overflow=0, pool_timeout=20, pool_pre_ping=True)
            return original_engine_factory(*engine_args, **engine_kwargs)

        if args.pooled:
            canonical.create_async_engine = pooled_engine
        try:
            result = asyncio.run(asyncio.wait_for(base.execute(env_file=base.canonical_env_file(),
                revision=args.expected_public_revision, expected_source=args.expected_source_sha256,
                custody_path=args.custody), timeout=1200))
        finally:
            canonical.create_async_engine = original_engine_factory
        required = {"cold_replay", "unknown_not_retried", "concurrent_single_call", "partition_replay",
                    "foreign_identity_denied", "stale_delivery_denied", "stage_replay", "concurrent_stage_single_call",
                    "pipeline_review_timeout_resume", "pipeline_answer_contradiction_replay", "repair_stage_replay",
                    "pipeline_option_repair_replay", "pipeline_compatibility_ambiguity_replay",
                    "pipeline_source_decision_replay", "owned_job_decision_readback", "pipeline_semantic_repair_replay",
                    "question_quote_migration_readback", "qa_unknown_review_no_retry_hold", "source_unit_atomic_scope",
                    "partial_repair_replay", "table_leadin_note_replay", "large_table_split_scope", "canonical_quote_guard", "rendered_rule_quote_replay", "lesson_exact_source_context", "lesson_claim_review_replay", "unsafe_repair_rejected_replay", "claim_table_row_context", "claim_subsection_context", "question_completeness_contract", "distractor_feedback_replay", "lesson_objective_prompt_scope", "confirmed_reference_link", "confirmed_reference_cross_field_hold", "confirmed_source_edge_with_unbound_model_occurrences", "order_independent_explanation", "citation_source_and_partial_contract"}
        flags = {name: result.get(name) is True for name in ("passed", "cleanup", "shared_migration_head_unchanged", "source_unchanged")}
        ok = all(flags.values()) and required.issubset(set(result.get("checks", [])))
        print(json.dumps({"status": "PASS" if ok else "BLOCKED", **flags, "checks": sorted(required & set(result.get("checks", []))),
                          "error_class": result.get("error_type"), "failed_check": result.get("failed_check"),
                          "source_sha256": result.get("source_sha256"), "connection_mode": "pooled" if args.pooled else "fresh"}))
        return 0 if ok else 1
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error_class": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
