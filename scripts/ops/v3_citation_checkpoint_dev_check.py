"""Focused source-bound citation expansion replay in a disposable DEV schema."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "ops"))
import ai_generation_realization_dev_check as base  # noqa: E402
import v3_extraction_checkpoint_dev_check as full_gate  # noqa: E402

base.SOURCE_PATHS = (*full_gate.base.SOURCE_PATHS, "scripts/ops/v3_citation_checkpoint_dev_check.py",
    "scripts/ops/kb_rag_isolated_dev_gate.py", "apps/api/alembic/versions/0158_ai_generation_checkpoints.py",
    "apps/api/alembic/versions/0159_ai_generation_omitted_lessons.py")


async def exercise(owner: Any, runtime: Any, schema: str, tenant_a: Any, tenant_b: Any,
                   job_a: str, resume_job: str, checks: list[str]) -> None:
    del owner, schema
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.orm import configure_mappers
    from app.models.registry import load_all_models
    from app.modules.ai.delivery_ownership import delivery_id
    from app.modules.ai.generation_checkpoint import AIGenerationCheckpointError
    from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
    from app.modules.ai.v3.citation_expansion import (citation_question_fingerprint, propose_rule_quote_expansion,
                                                     stage_citation_candidate)
    from app.modules.ai.v3.citation_review import build_citation_review_items, review_displayed_citations
    from app.modules.ai.v3.case_repair_gate import review_staged_case
    from app.modules.ai.v3.engine import V3GenerationPipeline
    from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
    from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase
    from app.modules.ai.v3.service import _build_curriculum_groups
    from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision
    from app.modules.ai.v3.stage_checkpoint import stage_once
    from app.modules.ai.worker_lesson_cycle import WorkerCycleJournal

    load_all_models()
    configure_mappers()
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    journal = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    cold = WorkerCycleJournal(str(tenant_a), job_a, sessions)
    plans: dict[str, dict[str, Any]] = {}

    class CaptureJournal:
        tenant_id = journal.tenant_id
        job_id = journal.job_id

        async def prepare(self, key: str, plan: dict[str, Any]) -> Any:
            plans[key] = plan
            return await journal.prepare(key, plan)

        async def save_value(self, key: str, value: dict[str, Any]) -> None:
            await journal.save_value(key, value)

        async def read_owned_value(self, key: str, plan: dict[str, Any]) -> Any:
            return await journal.read_owned_value(key, plan)

    capture = CaptureJournal()
    source = "Sign the ticket. Record it in the system."
    doc = DirectSourceDocument(doc_id="synthetic-doc", title="synthetic", filename="synthetic", category="general",
                               source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(doc,), total_chars=len(source), total_chunks=0)
    ref_source = "Порядок: см. п. 2.\n2. Подписать билет."
    ref_doc = DirectSourceDocument(doc_id="ref-doc", title="synthetic", filename="synthetic", category="general",
                                  source_revision="ref-rev", chunks=(), source_text=ref_source)
    ref_corpus = DirectSourceCorpus(tenant_id=str(tenant_a), documents=(ref_doc,), total_chars=len(ref_source), total_chunks=0)
    ref_text, target_text = "см. п. 2", "Подписать билет."
    ref_start, target_start = ref_source.index(ref_text), ref_source.index(target_text)
    decision = SourceReferenceDecision(tenant_id=str(tenant_a), document_id=ref_doc.doc_id, source_revision="ref-rev",
        converted_text_sha256=hashlib.sha256(ref_source.encode()).hexdigest(), reference_start=ref_start,
        reference_end=ref_start+len(ref_text), reference_exact=ref_text, target_start=target_start,
        target_end=target_start+len(target_text), target_exact=target_text, authority="owner_chat")
    ref_rule = RuleEntity(rule_id="r", section="s", title="t", statement="Порядок действий", doc_id=ref_doc.doc_id,
        source_revision="ref-rev", source_start=0, source_end=len(ref_source), source_quote="Порядок:")
    model = DocumentRuleModel(document_title="synthetic", document_sha256="a" * 64, rules=(ref_rule,))
    groups = _build_curriculum_groups(model, corpus=ref_corpus, reference_decisions=(decision,))
    warnings = [warning for group in groups for warning in group.unresolved_dependencies]
    assert any("Подтвержденная ссылка" in warning for warning in warnings), "unmatched_reference_hold_missing"
    assert all(ref_text not in warning for warning in warnings), "unmatched_reference_text_leaked"
    checks.append("unmatched_confirmed_reference_hold")
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", doc_id=doc.doc_id,
                      source_revision=doc.source_revision, source_start=0, source_end=len(source), source_quote=source)
    v = V3QuestionVariant(variant_id="v", branch_context="Branch A", scenario_premise="Applicant present",
        prompt="What is required?", correct_option=V3Option(text="Sign and record", is_correct=True),
        distractor_pool=(V3Option(text="Sign only", is_correct=False), V3Option(text="Record only", is_correct=False),
                         V3Option(text="Do neither", is_correct=False)), explanation="Both steps are required.",
        source_quote="Sign the ticket.")
    case = V3ScenarioCase(case_id="c", rule_id="r", learning_objective="Procedure", variants=(v,))
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="", covered_rule_ids=("r",),
                      cases=(case,), questions=(v.assemble_question(seed=42),))
    initial_items, issues = build_citation_review_items(lesson, [rule], corpus)
    assert len(initial_items) == 1 and not issues, "citation_binding_failed"
    original = initial_items[0]
    candidate = propose_rule_quote_expansion(corpus, rule, v.source_quote)
    fingerprint = citation_question_fingerprint(lesson, original["id"])
    assert candidate and fingerprint, "candidate_missing"
    staged = stage_citation_candidate(lesson, rule, corpus, original, candidate, fingerprint)
    assert staged is not None, "candidate_staging_failed"
    candidate_items, issues = build_citation_review_items(staged, [rule], corpus)
    assert len(candidate_items) == 1 and not issues, "candidate_binding_failed"
    calls: list[str] = []

    async def run_review(active: Any, items: list[dict[str, str]], *, unknown: bool = False) -> dict[str, Any]:
        async def invoke(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
            async def physical() -> dict[str, Any]:
                calls.append("unknown" if unknown else "ok")
                if unknown:
                    raise TimeoutError("synthetic unknown")
                verdict = "PARTIAL" if items[0]["displayed_quote"] == v.source_quote else "COMPLETE"
                return {"items": [{"id": items[0]["id"], "verdict": verdict,
                                   "unsupported": ["recording"] if verdict == "PARTIAL" else [], "summary": "checked"}]}
            return await stage_once(active, stage="review", group_id="citation-unknown" if unknown else "citation-repair",
                source_sha256="a" * 64, route_fingerprint="e" * 64, messages=messages,
                response_format=response_format, invoke=physical)
        return await review_displayed_citations(items, invoke)

    token = delivery_id.set(job_a)
    try:
        first = await run_review(capture, initial_items)
        second = await run_review(capture, candidate_items)
        assert first[original["id"]]["verdict"] == "PARTIAL" and second[original["id"]]["verdict"] == "COMPLETE"
        assert await run_review(cold, initial_items) == first and await run_review(cold, candidate_items) == second
        assert calls == ["ok", "ok"], "citation_replayed_provider"
        assert lesson.cases[0].variants[0].source_quote == v.source_quote, "original_mutated"
        assert staged.cases[0].variants[0].source_quote == source, "candidate_not_staged"
        checks.append("citation_partial_to_complete_and_cold_replay")
        result_keys = [key for key in plans if key.startswith("v3-stage-result:")]
        assert len(result_keys) == 2, "citation_result_identity_missing"
        foreign_tenant = WorkerCycleJournal(str(tenant_b), job_a, sessions)
        foreign_job = WorkerCycleJournal(str(tenant_a), resume_job, sessions)
        for key in result_keys:
            for foreign in (foreign_tenant, foreign_job):
                try:
                    value = await foreign.read_owned_value(key, plans[key])
                except AIGenerationCheckpointError as error:
                    assert str(error) == "generation_plan_not_found", "citation_foreign_denial_changed"
                else:
                    assert value is None, "citation_foreign_read"
        checks.append("citation_cross_tenant_and_job_denied")
        try:
            await run_review(journal, candidate_items, unknown=True)
        except TimeoutError:
            pass
        else:
            raise AssertionError("citation_timeout_missing")
        try:
            await run_review(cold, candidate_items, unknown=True)
        except ExtractionOutcomeUnknownError:
            pass
        else:
            raise AssertionError("citation_unknown_retried")
        assert calls == ["ok", "ok", "unknown"] and lesson.cases[0].variants[0].source_quote == v.source_quote
        checks.append("citation_unknown_no_retry_original_preserved")

        semantic_calls: list[str] = []

        async def case_review(active: Any) -> tuple[bool, dict[str, Any]]:
            async def invoke(messages: list[dict[str, str]], response_format: Any) -> dict[str, Any]:
                async def physical() -> dict[str, Any]:
                    system, user = messages[0]["content"], messages[1]["content"]
                    if "независимый контролер" in system:
                        semantic_calls.append("critic")
                        return {"verdict": "PASS", "factual_score": 5, "alignment_score": 5,
                                "didactic_score": 5, "summary": "Synthetic review passed.", "defects": []}
                    assert "Branch A" in user, "candidate_branch_context_missing"
                    compatibility = "Проверь совместимость" in system
                    semantic_calls.append("compatibility" if compatibility else "options")
                    items = json.loads(user.split("ВАРИАНТЫ:\n", 1)[1])
                    return {"options": [{"index": item["index"], "verdict": status,
                        "claims": [{"claim": "test", "status": status, "reason": "test"}],
                        "summary": "checked", "omitted_required_elements": []}
                        for item in items for status in ["UNCERTAIN" if compatibility and item["text"] == "Sign and record"
                            else "SUPPORTED" if item["text"] == "Sign and record" else "CONTRADICTED"]]}
                return await stage_once(active, stage="review", group_id="case-candidate", source_sha256="a" * 64,
                    route_fingerprint="e" * 64, messages=messages, response_format=response_format, invoke=physical)
            record: dict[str, Any] = {"original_review": {"defects": ["initial"]}, "recheck": None}
            accepted, cached = await review_staged_case(staged, "c", [rule], corpus, [source], [source], (), False,
                                                        V3GenerationPipeline(invoke), record)
            assert not cached, "failed_candidate_cached"
            return accepted, record

        accepted, record = await case_review(journal)
        assert not accepted and record["rejected"] == "candidate_compatibility_failed", "candidate_not_held"
        assert record["original_review"]["defects"] and record["recheck"], "case_findings_lost"
        prior = list(semantic_calls)
        accepted_cold, cold_record = await case_review(cold)
        assert not accepted_cold and cold_record == record and semantic_calls == prior, "case_review_replayed"
        assert semantic_calls == ["critic", "options", "compatibility"], "case_review_sequence_changed"
        assert lesson.cases[0].variants[0].source_quote == v.source_quote, "original_case_changed"
        checks.append("case_repair_held_with_branch_and_cold_replay")
    finally:
        delivery_id.reset(token)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-public-revision")
    parser.add_argument("--custody", type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "OFFLINE_PREFLIGHT", "source_sha256": base.source_digest()}))
        return 0
    if args.custody is None or not args.custody.resolve().is_relative_to((ROOT / ".release-evidence").resolve(strict=True)):
        raise ValueError("custody_invalid")
    base.exercise = exercise
    import ai_generation_checkpoint_dev_check as canonical
    from sqlalchemy.ext.asyncio import create_async_engine

    original_factory = canonical.create_async_engine
    def pooled_factory(url: str, **kwargs: Any) -> Any:
        kwargs.pop("poolclass", None)
        return create_async_engine(url, pool_size=1, max_overflow=0, **kwargs)
    canonical.create_async_engine = pooled_factory
    try:
        result = asyncio.run(asyncio.wait_for(base.execute(env_file=base.canonical_env_file(),
            revision=args.expected_public_revision, expected_source=args.expected_source_sha256,
            custody_path=args.custody), timeout=600))
    finally:
        canonical.create_async_engine = original_factory
    required = {"citation_partial_to_complete_and_cold_replay", "citation_unknown_no_retry_original_preserved",
                "citation_cross_tenant_and_job_denied", "case_repair_held_with_branch_and_cold_replay",
                "unmatched_confirmed_reference_hold"}
    flags = {key: result.get(key) is True for key in ("passed", "cleanup", "shared_migration_head_unchanged", "source_unchanged")}
    ok = all(flags.values()) and required.issubset(set(result.get("checks", [])))
    print(json.dumps({"status": "PASS" if ok else "BLOCKED", **flags,
                      "checks": sorted(required & set(result.get("checks", []))),
                      "error_class": result.get("error_type"), "failed_check": result.get("failed_check")}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
