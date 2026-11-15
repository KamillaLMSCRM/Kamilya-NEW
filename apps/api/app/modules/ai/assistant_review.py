"""Explicit source review: candidate observations, then model adjudication.

No course mutation and no regeneration. Python checks object identity and literal
witnesses; the model decides whether meaning actually conflicts with the source.
Rejected and unresolved observations remain distinguishable.
"""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ml_prompts import get_renderer
from app.modules.ai.assistant_policy import MAX_ASSISTANT_REPLY_CHARS


class ReviewProtocolError(ValueError):
    pass


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_kind: Literal["lesson", "question", "source"]
    target_id: str
    problem: str
    replacement: str


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewed_lesson_ids: list[str]
    reviewed_question_ids: list[str] = Field(default_factory=list)
    findings: list[Finding]


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    finding_id: str
    verdict: Literal["confirmed", "rejected", "uncertain"]
    reason: str
    source_document_id: str
    source_evidence: str


class Decisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[Decision]


def _json_response(response: Any, schema: type[BaseModel]) -> Any:
    if (getattr(response, "finish_reason", None) == "length"
            or getattr(response, "content_is_reasoning", False)):
        raise ReviewProtocolError("incomplete_review")
    try:
        return schema.model_validate_json(response.content)
    except (ValidationError, ValueError, TypeError):
        raise ReviewProtocolError("invalid_review_contract") from None


def read_decisions(response: Any) -> list[Decision]:
    """A malformed row leaves its own candidate pending, retaining valid peers."""
    if (getattr(response, "finish_reason", None) == "length"
            or getattr(response, "content_is_reasoning", False)):
        raise ReviewProtocolError("incomplete_review")
    try:
        raw = json.loads(response.content)
        if not isinstance(raw, dict) or not isinstance(raw.get("decisions"), list):
            raise ValueError
    except (ValueError, TypeError):
        raise ReviewProtocolError("invalid_review_contract") from None
    result = []
    for index, row in enumerate(raw["decisions"]):
        try:
            result.append(Decision.model_validate(row))
        except ValidationError:
            identifier = row.get("finding_id") if isinstance(row, dict) else None
            result.append(Decision(finding_id=identifier if isinstance(identifier, str) else f"unmapped-{index}",
                verdict="uncertain", reason="", source_document_id="", source_evidence=""))
    return result


def review_inventory(body: dict[str, Any]) -> dict[str, tuple[str, str]]:
    result = {d["document_id"]: ("source", d["title"]) for d in body["sources"]["documents"]}
    for module in body["modules"]:
        for lesson in module["lessons"]:
            result[lesson["id"]] = ("lesson", lesson["title"])
            for quiz in lesson["quizzes"]:
                for question in quiz["questions"]:
                    result[question["id"]] = ("question", question["text"])
    return result


def adjudication_messages(body: dict[str, Any], findings: list[dict[str, Any]], language: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": get_renderer().render("router/system_review_adjudication.md")},
        {"role": "user", "content": json.dumps({"language": language, "course_context": body,
            "candidate_findings": findings}, ensure_ascii=False, separators=(",", ":"))},
    ]


async def review_course(llm: Any, body: dict[str, Any], message: str, language: str) -> str:
    if body["sources"]["status"] != "complete":
        return {"ru": "Исходная редакция недоступна. Проверка курса по исходнику не выполнена.",
                "kk": "Бастапқы редакция қолжетімсіз. Курс дереккөзбен салыстырылған жоқ.",
                "en": "The source edition is unavailable. Source review was not performed."}[language]
    draft_response = await llm.ainvoke([
        {"role": "system", "content": get_renderer().render("router/system_review_candidates.md")},
        {"role": "user", "content": json.dumps({"language": language, "course_context": body,
            "request": message}, ensure_ascii=False, separators=(",", ":"))},
    ], response_format={"type": "json_object"})
    draft: Draft = _json_response(draft_response, Draft)
    candidates = [{"finding_id": f"finding-{i}", **finding.model_dump()}
        for i, finding in enumerate(draft.findings, 1)]
    decisions: list[Decision] = []
    if candidates:
        response = await llm.ainvoke(adjudication_messages(body, candidates, language),
                                   response_format={"type": "json_object"})
        decisions = read_decisions(response)
    return render_review(body, draft, decisions, language)


def render_review(body: dict[str, Any], draft: Draft, decisions: list[Decision], language: str) -> str:
    objects = review_inventory(body)
    sources = {d["document_id"]: d["text"] for d in body["sources"]["documents"]}
    lessons = [lesson for module in body["modules"] for lesson in module["lessons"]]
    lesson_ids = {lesson["id"] for lesson in lessons}
    reviewed = set(draft.reviewed_lesson_ids) & lesson_ids
    question_count = sum(len(quiz["questions"]) for lesson in lessons for quiz in lesson["quizzes"])
    question_ids = {q["id"] for lesson in lessons for quiz in lesson["quizzes"] for q in quiz["questions"]}
    reviewed_questions = set(draft.reviewed_question_ids) & question_ids
    labels = {
        "ru": ("Рассмотрено уроков", "Всего вопросов в курсе", "Подтверждённые замечания",
               "Требует дополнительной проверки", "Отклонено при перепроверке", "Предложение", "Основание",
               "Существенных замечаний не подтверждено.", "Проверка охватывает не все уроки или вопросы.",
               "Ответ проверки не подтверждён или не привязан к исходнику.", "Ничего не применено."),
        "kk": ("Қаралған сабақтар", "Курстағы сұрақтар", "Расталған ескертулер",
               "Қосымша тексеру қажет", "Қайта тексеруде қабылданбады", "Ұсыныс", "Негіз",
               "Маңызды ескертулер расталмады.", "Барлық сабақ немесе сұрақ қамтылмаған.",
               "Тексеру жауабы расталмаған немесе дереккөзбен байланыстырылмаған.", "Өзгеріс енгізілген жоқ."),
        "en": ("Lessons reviewed", "Questions in course", "Confirmed findings", "Needs further review",
               "Rejected on review", "Proposal", "Evidence", "No material findings confirmed.",
               "Not all lessons or questions were reviewed.", "Decision unverified or not grounded in the source.",
               "No changes applied."),
    }[language]
    confirmed, pending, rejected = [], [], []
    for i, finding in enumerate(draft.findings, 1):
        matching = [d for d in decisions if d.finding_id == f"finding-{i}"]
        known = objects.get(finding.target_id)
        title = known[1] if known else finding.target_id
        entry = f"{title} ({finding.target_id}): {finding.problem}"
        if len(matching) != 1 or known is None or known[0] != finding.target_kind:
            pending.append(entry + " — " + labels[9])
            continue
        decision = matching[0]
        if decision.verdict == "rejected" and decision.reason.strip():
            rejected.append(entry + " — " + decision.reason)
        elif (decision.verdict == "confirmed" and decision.reason.strip() and decision.source_evidence.strip()
              and decision.source_evidence in sources.get(decision.source_document_id, "")):
            confirmed.append(entry + f"\n{labels[5]}: {finding.replacement}\n{labels[6]}: {decision.source_evidence}")
        else:
            pending.append(entry + " — " + (decision.reason or labels[9]))
    # Unknown decisions cannot clear a different finding or create an apply action.
    extra = [d for d in decisions if d.finding_id not in {f"finding-{i}" for i in range(1, len(draft.findings)+1)}]
    lines = [f"{labels[0]}: {len(reviewed)}/{len(lessons)}. {labels[1]}: {question_count}."]
    if reviewed != lesson_ids or reviewed_questions != question_ids:
        lines.append(labels[8])
    if len(draft.reviewed_lesson_ids) != len(set(draft.reviewed_lesson_ids)) or set(draft.reviewed_lesson_ids) - lesson_ids:
        lines.append(labels[9])
    if len(draft.reviewed_question_ids) != len(set(draft.reviewed_question_ids)) or set(draft.reviewed_question_ids) - question_ids:
        lines.append(labels[9])
    for heading, entries in ((labels[2], confirmed), (labels[3], pending), (labels[4], rejected)):
        if entries:
            lines += ["\n" + heading + ":", *["- " + e for e in entries]]
    if extra:
        lines.append(labels[9])
    if not confirmed:
        lines.append(labels[7])
    lines.append(labels[10])
    reply = "\n".join(lines)
    if len(reply) > MAX_ASSISTANT_REPLY_CHARS:
        raise ReviewProtocolError("review_reply_too_large")
    return reply
