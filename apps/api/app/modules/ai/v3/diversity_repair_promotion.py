"""Unwired promotion gate for a single owned diversity repair."""
from __future__ import annotations

from typing import Any

from app.modules.ai.v3.diversity_repair_selection import preserves_non_target
from app.modules.ai.v3.diversity_review import review_final_lesson
from app.modules.ai.v3.diversity_variant_author import author_owned_variant
from app.modules.ai.v3.engine import V3GenerationPipeline
from app.modules.ai.v3.extraction_checkpoint import ExtractionOutcomeUnknownError
from app.modules.ai.v3.stage_checkpoint import stage_once


async def staged_diversity_repair(*, lesson: Any, corpus: Any, rules: tuple[Any, ...], selected: Any,
    journal: Any, expected_document_ids: tuple[str, ...], review_group_id: str, source_sha256: str,
    route_fingerprint: str, direct_client: Any, context_rules: tuple[Any, ...],
    unresolved_dependencies: tuple[Any, ...], max_output_tokens: int = 8192,
    feedback: dict[str, Any] | None = None, typed_output: bool = False) -> tuple[Any, bool]:
    """Return the original unless every independent gate accepts; never recurse or certify coverage."""
    from app.modules.ai.v3.case_repair_gate import review_staged_case
    from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest
    from app.modules.ai.v3.service import _review_source_unit_fragments, _unbound_case_citation_ids

    if unresolved_dependencies:
        return lesson, False
    combined_rules = rules + context_rules
    if build_primary_source_manifest(corpus, combined_rules, expected_tenant_id=journal.tenant_id,
                                     expected_document_ids=expected_document_ids) is None:
        return lesson, False
    candidate = await author_owned_variant(lesson=lesson, corpus=corpus, rules=rules, selected=selected,
        journal=journal, expected_document_ids=expected_document_ids, review_group_id=review_group_id,
        source_sha256=source_sha256, route_fingerprint=route_fingerprint, direct_client=direct_client,
        max_output_tokens=max_output_tokens, context_rules=context_rules,
        **({'typed_output': True} if typed_output else {}))
    if candidate is None or not preserves_non_target(lesson, candidate, selected):
        if feedback is not None:
            feedback.update(status="rejected", reason="candidate_invalid")
        return lesson, False
    units = _review_source_unit_fragments(list(combined_rules), corpus)
    if not units or _unbound_case_citation_ids(candidate, list(combined_rules), corpus):
        if feedback is not None:
            feedback.update(status="rejected", reason="citation_unverified")
        return lesson, False

    async def invoke(messages: list[dict[str, str]], response_format: dict[str, Any] | None) -> dict[str, Any]:
        async def forbidden() -> dict[str, Any]:
            raise ExtractionOutcomeUnknownError("v3_diversity_repair_direct_only")
        return await stage_once(journal, stage="review", group_id=("batched-review:diversity-case:" if typed_output
                                else "diversity-case:") + review_group_id,
            source_sha256=source_sha256, route_fingerprint=route_fingerprint, messages=messages,
            response_format=response_format, invoke=forbidden, direct_client=direct_client,
            direct_max_output_tokens=max_output_tokens)

    pipeline: Any = V3GenerationPipeline(invoke, explanation_consistency=True, scoped_revision=typed_output)
    if typed_output:
        from app.modules.ai.v3.batched_review import BatchedReview
        cache = await BatchedReview.prime([], invoke, typed_buckets=True, typed_fallback=True)
        pipeline = cache.wrap(pipeline)
    record: dict[str, Any] = {}
    accepted, _ = await review_staged_case(candidate, selected.case_id, list(combined_rules), corpus, units, units,
                                            (), len(candidate.cases) > 1, pipeline, record)
    if feedback is not None:
        checks = record.get("answer_rechecks")
        feedback.update(status="case_accepted" if accepted else "rejected", case_review={
            "status": "accepted" if accepted else "rejected",
            "reviewed_variant_count": len(checks) if isinstance(checks, list) else 0})
    if not accepted:
        return lesson, False

    async def direct_invoke(messages: list[dict[str, str]]) -> dict[str, Any]:
        return await invoke(messages, {"type": "json_object"})

    observed = await review_final_lesson(lesson=candidate, corpus=corpus, rules=rules,
        expected_tenant_id=journal.tenant_id, expected_document_ids=expected_document_ids, journal=journal,
        group_id="diversity-post-repair:" + review_group_id, source_sha256=source_sha256,
        route_fingerprint=route_fingerprint, invoke=direct_invoke, direct_client=direct_client,
        direct_max_output_tokens=max_output_tokens, context_rules=context_rules,
        **({'typed_invoke': invoke} if typed_output else {}))
    if feedback is not None:
        import hashlib

        feedback.update(post_review={"status": observed.get("status"), "fingerprint": observed.get("fingerprint"),
            "overlaps": observed.get("overlaps", []),
            "omissions": [{"rule_id": item["rule_id"],
                "quote_sha256": hashlib.sha256(item["exact_quote"].encode("utf-8")).hexdigest()}
                for item in observed.get("omissions", [])],
            "inventory_completeness": observed.get("inventory_completeness", "unknown")})
    if observed.get("status") != "review_required" or observed.get("overlaps") or observed.get("omissions"):
        if feedback is not None:
            feedback["status"] = "rejected"
        return lesson, False
    if feedback is not None:
        feedback["status"] = "accepted_needs_review"
    return candidate, True
