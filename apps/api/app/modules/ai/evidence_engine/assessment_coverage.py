"""Conservative source-topic coverage, not a per-lesson question quota.

Only a reviewed question's primary tested fact supplies coverage, except when
the same sufficiently specific correct answer occurs verbatim in another topic
of the same source revision. Incidental citations cannot make a neighboring
topic appear tested. Successful empty author output can omit an introductory
block; an unavailable author cannot do so.
"""
from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import parse_qsl

from .models import QuestionDraft, SourceFact

_REPEATED_ANSWER_MIN_LENGTH = 24


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def _source_scope(fact: SourceFact) -> tuple[str, str]:
    locator = dict(parse_qsl(fact.source_locator.replace(";", "&")))
    return locator.get("doc_id", fact.fact_id), locator.get("source_revision", "")


def _topic(fact: SourceFact) -> str:
    locator = dict(parse_qsl(fact.source_locator.replace(";", "&")))
    parts = (locator.get("doc_id", fact.fact_id), locator.get("source_revision", ""),
             locator.get("section", fact.fact_id), fact.subject)
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:20]


def assess_topic_coverage(
    facts: dict[str, SourceFact], questions: list[QuestionDraft],
    block_outcomes: list[dict[str, Any]],
    *,
    audited_omitted_fact_ids: set[str] | None = None,
) -> dict[str, Any]:
    audited_omissions = set(audited_omitted_fact_ids or ())
    required: dict[str, set[str]] = {}
    seen: set[str] = set()
    invalid = ((not block_outcomes and bool(facts))
               or not audited_omissions.issubset(facts))
    for block in block_outcomes:
        ids = block.get("fact_ids", [])
        outcome = block.get("outcome")
        candidates = block.get("candidates")
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(fid, str) or fid not in facts for fid in ids)
                or outcome not in {
                    "accepted",
                    "no_assessable_questions",
                    "rejected",
                    "unavailable",
                    "density_omitted",
                    "quality_omitted",
                }
                or type(candidates) is not int or candidates < 0):
            invalid = True
            continue
        seen.update(ids)
        if (
            outcome in {"no_assessable_questions", "density_omitted"}
            and candidates == 0
        ) or outcome == "quality_omitted":
            continue
        for fid in ids:
            # A bounded author/review/repair cycle may prove one axis unsafe
            # while another axis from the same semantic block remains useful.
            # That explicit omission is not a silent coverage loss: it is the
            # no-padding policy applied at axis granularity. Provider/contract
            # failures are never included here and therefore still block.
            if fid in audited_omissions:
                continue
            required.setdefault(_topic(facts[fid]), set()).add(fid)
    if set(facts) - seen:
        invalid = True
    covered: set[str] = set()
    for question in questions:
        if not question.semantic_reviewed or question.fact_id not in facts:
            continue
        primary = facts[question.fact_id]
        covered.add(_topic(primary))
        answer = _norm(question.correct_answer)
        if (len(answer) < _REPEATED_ANSWER_MIN_LENGTH
                or answer not in _norm(primary.value)):
            continue
        scope = _source_scope(primary)
        covered.update(
            _topic(fact)
            for fact in facts.values()
            if _source_scope(fact) == scope and answer in _norm(fact.value)
        )
    missing = sorted(set(required) - covered)
    return {
        "policy": "source-topic-coverage-v2", "requires_review": bool(missing) or invalid,
        "audit_incomplete": invalid, "required_topic_count": len(required),
        "covered_topic_count": len(set(required) & covered),
        "missing_topic_ids": missing,
        "missing_fact_ids": sorted({fid for topic in missing for fid in required[topic]}),
    }
