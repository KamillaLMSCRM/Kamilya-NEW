"""Unwired same-session verification of the saved diversity selection."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.assessment_projection import project_lesson_questions
from app.modules.ai.v3.diversity_repair_selection import Selection, select_candidate
from app.modules.ai.v3.diversity_review import _SYSTEM, POLICY, _hash, _validate
from app.modules.ai.v3.models import RuleEntity, V3Lesson
from app.modules.ai.v3.pending_stage_journal import PendingStageJournal
from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest
from app.modules.ai.v3.stage_checkpoint import _digest, stage_plan

REPAIR_GROUP_PREFIX = "owned-diversity-repair:"
GUARD_POLICY = "v3-owned-diversity-selection-guard-v1"


@dataclass(frozen=True, repr=False)
class OwnedSelectionGuard:
    identity: str
    _check: Callable[[Any, Any, dict[str, Any]], Awaitable[bool]]
    review_group_id: str = ""

    async def __call__(self, session: Any, job: Any, plan: dict[str, Any]) -> bool:
        return await self._check(session, job, plan)

def build_owned_selection_guard(*, lesson: V3Lesson, corpus: DirectSourceCorpus,
    rules: tuple[RuleEntity, ...], journal: PendingStageJournal, expected_document_ids: tuple[str, ...],
    review_group_id: str, source_sha256: str, route_fingerprint: str, selected: Selection,
    context_rules: tuple[RuleEntity, ...] = (),
    typed_output: bool = False,
) -> OwnedSelectionGuard:
    """Build a trusted callback for the exact completed review, not a client ACL.

    Caller must pass it to the owned claim seam; it must run under the same job
    lock as the source verifier. Any stale, missing or malformed review denies.
    """
    async def guard(session: Any, _job: Any, _plan: dict[str, Any]) -> bool:
        try:
            if type(journal) is not PendingStageJournal or corpus.tenant_id != journal.tenant_id:
                return False
            manifest = build_primary_source_manifest(corpus, rules, expected_tenant_id=journal.tenant_id,
                                                      expected_document_ids=expected_document_ids)
            if manifest is None or any(doc.source_text is None for doc in corpus.documents):
                return False
            source = "\n\n".join(doc.source_text for doc in corpus.documents if doc.source_text)
            if hashlib.sha256(source.encode("utf-8")).hexdigest() != source_sha256:
                return False
            questions = [q.to_dict() for q in project_lesson_questions(lesson)]  # type: ignore[no-untyped-call]
            if not questions or len(questions) > 80:
                return False
            request: dict[str, Any] = {"policy": POLICY, "manifest_sha256": manifest.fingerprint,
                "primary_sources": [{"rule_id": rule.rule_id, "text": text}
                                    for rule, text in zip(rules, manifest.fragments, strict=True)],
                "questions": questions}
            if context_rules:
                combined = build_primary_source_manifest(corpus, rules + context_rules, expected_tenant_id=journal.tenant_id,
                                                         expected_document_ids=expected_document_ids)
                context = build_primary_source_manifest(corpus, context_rules, expected_tenant_id=journal.tenant_id,
                                                        expected_document_ids=expected_document_ids)
                if combined is None or context is None:
                    return False
                request["context_source_manifest"] = {"fingerprint": context.fingerprint,
            "purpose": "Related conditions and exceptions only; assess omissions against primary sources, never treat context as a separate primary target.",
                    "fragments": [{"rule_id": rule.rule_id, "text": fragment}
                                  for rule, fragment in zip(context_rules, context.fragments, strict=True)]}
            if len(json.dumps(request, ensure_ascii=False).encode("utf-8")) > 180_000:
                return False
            fingerprint = _hash(request)
            messages = [{"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": json.dumps({**request, "fingerprint": fingerprint}, ensure_ascii=False)}]
            from app.modules.ai.v3.auxiliary_response_contracts import diversity_review_format
            review_plan = stage_plan(journal, stage="review", group_id=review_group_id,
                source_sha256=source_sha256, route_fingerprint=route_fingerprint,
                messages=messages, response_format=diversity_review_format(fingerprint, len(questions),
                    [rule.rule_id for rule in rules]) if typed_output else {"type": "json_object"})
            signature = _digest(review_plan)
            saved = await journal.read_owned_value_in_session(session, f"v3-stage-result:{signature}", review_plan)
            if not isinstance(saved, dict):
                return False
            response = saved.get("response")
            if (not isinstance(response, dict) or saved.get("identity") != signature
                    or saved.get("response_sha256") != _digest(response)):
                return False
            checked = _validate(response, fingerprint, rules, manifest.fragments, len(questions))
            if checked is None:
                return False
            observation = {"status": "review_required", "fingerprint": fingerprint,
                           "overlaps": checked["overlaps"], "omissions": checked["omissions"]}
            current = select_candidate(lesson=lesson, corpus=corpus, rules=rules,
                expected_tenant_id=journal.tenant_id, expected_document_ids=expected_document_ids,
                observation=observation, selected_index=selected.question_index, context_rules=context_rules)
            return current == selected
        except Exception:
            return False
    identity = _digest({"policy": GUARD_POLICY, "tenant_id": journal.tenant_id, "job_id": journal.job_id,
                        "user_id": str(journal.user_id), "documents": expected_document_ids,
                        "review_group_id": review_group_id, "source_sha256": source_sha256,
                        "route_fingerprint": route_fingerprint, "case_id": selected.case_id,
                        "variant_id": selected.variant_id, "rule_id": selected.rule_id,
                        "question_index": selected.question_index, "source_quote": selected.source_quote,
                        "manifest_fingerprint": selected.manifest_fingerprint,
                        "observation_fingerprint": selected.observation_fingerprint})
    return OwnedSelectionGuard(identity=identity, _check=guard, review_group_id=review_group_id)
