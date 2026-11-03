"""Batch-check support by displayed citations, independently of full-source QA.

The caller must establish tenant/document/revision/span ownership before use.
Semantic output is probabilistic and never replaces provenance or human review.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.models import RuleEntity, V3Lesson

_SYSTEM = (
    "Независимо для каждого элемента проверь, подтверждает ли только показанная цитата все существенные "
    "фактические действия, исполнителей, условия и объекты правильного ответа и объяснения в условиях вопроса. "
    "Не используй знания вне цитаты и не предполагай отсутствующие фразы; идентификатор источника — метаданные, "
    "а не доказательство содержания. Верни только JSON "
    '{"items":[{"id":"...","verdict":"COMPLETE|PARTIAL|UNSUPPORTED|UNKNOWN",'
    '"unsupported":["..."],"summary":"..."}]}; каждый id ровно один раз.'
)


class CitationReviewInvalidError(ValueError):
    """A completed local citation-review contract is incomplete or malformed."""


def bind_displayed_citation(corpus: DirectSourceCorpus, rule: RuleEntity, quote: str) -> str | None:
    """Return opaque source identity only for one literal, rule-owned source span."""
    if (
        not corpus.tenant_id
        or not rule.doc_id
        or not rule.source_revision
        or not isinstance(quote, str)
        or not quote.strip()
        or type(rule.source_start) is not int
        or type(rule.source_end) is not int
    ):
        return None
    docs = [
        doc
        for doc in corpus.documents
        if doc.doc_id == rule.doc_id and doc.source_revision == rule.source_revision and doc.source_text is not None
    ]
    if len(docs) != 1:
        return None
    source = docs[0].source_text or ""
    if not 0 <= rule.source_start < rule.source_end <= len(source):
        return None
    start = source.find(quote)
    if start < 0 or source.find(quote, start + 1) >= 0:
        return None
    end = start + len(quote)
    if not rule.source_start <= start < end <= rule.source_end:
        return None
    identity = {
        "tenant": corpus.tenant_id,
        "document": rule.doc_id,
        "revision": rule.source_revision,
        "source_sha256": hashlib.sha256(source.encode("utf8")).hexdigest(),
        "start": start,
        "end": end,
    }
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf8")).hexdigest()


def build_citation_review_items(
    lesson: V3Lesson,
    rules: list[RuleEntity],
    corpus: DirectSourceCorpus,
) -> tuple[list[dict[str, str]], list[str]]:
    """Collect delivered questions with bound source identities; unresolved items remain held."""
    questions = []
    if lesson.cases:
        for ci, case in enumerate(lesson.cases, 1):
            for vi, variant in enumerate(case.variants, 1):
                questions.append((variant.assemble_question(seed=100 + ci * 10 + vi), case.rule_id))
    else:
        questions = [(question, question.rule_id) for question in lesson.questions]
    if not questions:
        return [], ["no_questions"]
    ids = [q.question_id for q, _ in questions]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(ids) != len(set(ids)):
        return [], ["duplicate_or_empty_question_id"]
    items: list[dict[str, str]] = []
    issues: list[str] = []
    for question, rule_id in questions:
        linked = [rule for rule in rules if rule.rule_id == rule_id]
        if len(linked) != 1:
            issues.append(f"{question.question_id}:unresolved_rule")
            continue
        rule = linked[0]
        identity = bind_displayed_citation(corpus, rule, question.source_quote)
        rule_identity = bind_displayed_citation(corpus, rule, rule.source_quote)
        correct = [option.text for option in question.options if option.is_correct]
        if (
            identity is None
            or rule_identity is None
            or len(correct) != 1
            or not isinstance(correct[0], str)
            or not correct[0].strip()
            or not isinstance(question.prompt, str)
            or not question.prompt.strip()
            or not isinstance(question.explanation, str)
            or not question.explanation.strip()
            or not isinstance(question.scenario_premise, str)
        ):
            issues.append(f"{question.question_id}:unresolved_source_or_answer")
            continue
        provenance = {
            "displayed": identity,
            "rule_quote": rule_identity,
            "rule_id": rule.rule_id,
            "unit_start": rule.source_start,
            "unit_end": rule.source_end,
        }
        provenance_hash = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode("utf8")).hexdigest()
        items.append(
            {
                "id": question.question_id,
                "scenario": question.scenario_premise or "(не указана)",
                "question": question.prompt,
                "answer": correct[0],
                "explanation": question.explanation,
                "displayed_quote": question.source_quote,
                "source_identity": provenance_hash,
            }
        )
    return items, issues


def validate_citation_review(result: Any, expected_ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Reject missing, duplicated, malformed or inconsistent verdicts."""
    if not expected_ids or len(set(expected_ids)) != len(expected_ids) or any(not i for i in expected_ids):
        raise CitationReviewInvalidError("v3_citation_review_identity_invalid")
    rows = result.get("items") if isinstance(result, dict) and set(result) == {"items"} else None
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        raise CitationReviewInvalidError("v3_citation_review_incomplete")
    validated: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"id", "verdict", "unsupported", "summary"}:
            raise CitationReviewInvalidError("v3_citation_review_invalid")
        key, verdict, unsupported, summary = row["id"], row["verdict"], row["unsupported"], row["summary"]
        if (
            not isinstance(key, str)
            or key not in expected_ids
            or key in validated
            or not isinstance(verdict, str)
            or verdict not in {"COMPLETE", "PARTIAL", "UNSUPPORTED", "UNKNOWN"}
            or not isinstance(unsupported, list)
            or any(not isinstance(item, str) or not item.strip() for item in unsupported)
            or not isinstance(summary, str)
            or not summary.strip()
            or (verdict == "COMPLETE" and unsupported)
            or (verdict in {"PARTIAL", "UNSUPPORTED"} and not unsupported)
        ):
            raise CitationReviewInvalidError("v3_citation_review_invalid")
        validated[key] = row
    if set(validated) != set(expected_ids):
        raise CitationReviewInvalidError("v3_citation_review_incomplete")
    return validated


async def review_displayed_citations(
    items: list[dict[str, str]],
    invoke: Callable[[list[dict[str, str]], dict[str, Any] | None], Awaitable[dict[str, Any]]],
    *,
    typed_output: bool = False,
) -> dict[str, dict[str, Any]]:
    """Review exactly the provided quotes; the full source is deliberately absent."""
    keys = {"id", "scenario", "question", "answer", "explanation", "displayed_quote", "source_identity"}
    if not items or any(
        not isinstance(item, dict)
        or set(item) != keys
        or any(not isinstance(v, str) or not v.strip() for v in item.values())
        for item in items
    ):
        raise CitationReviewInvalidError("v3_citation_review_input_invalid")
    expected = tuple(item["id"] for item in items)
    if len(set(expected)) != len(expected):
        raise CitationReviewInvalidError("v3_citation_review_identity_invalid")
    from app.modules.ai.v3.auxiliary_response_contracts import citation_review_format

    result = await invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": json.dumps({"items": items}, ensure_ascii=False)},
        ],
        citation_review_format(list(expected)) if typed_output else {"type": "json_object"},
    )
    return validate_citation_review(result, expected)
