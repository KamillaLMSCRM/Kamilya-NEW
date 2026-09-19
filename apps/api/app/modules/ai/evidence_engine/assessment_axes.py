"""Deterministic assessment truth boundary.

The source and server own the tested fact, correct answer, evidence and stable
identity. A language model may only phrase the question and propose wrong
answers. This keeps provider/model changes from moving the answer key.
"""

from __future__ import annotations

import hashlib
import re

from .models import (
    AssessmentAxis,
    AssessmentAxisKind,
    AuthoredAssessment,
    LessonDraft,
    QuestionDraft,
    SourceFact,
)


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


_LOW_VALUE_ATTRIBUTE = re.compile(
    r"^(?:код|артикул|sku|идентификатор|номер строки|источник|лист)$",
    flags=re.IGNORECASE,
)

_FORMULA_SYMBOL_DEFINITION = re.compile(
    r"^\s*[A-Za-zА-Яа-яЁё0-9|]{1,3}\s*[-—]\s*"
    r"(?:порядков\w*\s+номер|период\w*\s+времени|сумм\w*|"
    r"годов\w*\s+эффективн\w*\s+ставк\w*)\b",
    flags=re.IGNORECASE,
)

_DEPENDENT_LEADING_FRAGMENT = re.compile(
    r"^(?:получив|ознакомившись|изучив|рассмотрев|руководствуясь|"
    r"приняв\s+во\s+внимание)\b",
    flags=re.IGNORECASE,
)


def _has_ambiguous_formula_symbol(fact: SourceFact) -> bool:
    """Do not assess symbols whose identity can be changed by PDF OCR.

    Glyphs such as Latin ``t``, Cyrillic ``т``, ``l``, ``1`` and ``|`` are
    visually interchangeable in converted formulas.  The definition may stay
    in the lesson as source evidence, but it is not a safe autonomous answer
    key without a structured formula representation.
    """
    return bool(_FORMULA_SYMBOL_DEFINITION.match(fact.value))


_CONCISE_SOURCE_SPANS = (
    re.compile(
        r"^(?P<answer>[^—–-]{2,80}?)\s*[—–-]\s+"
        r"(?:договор|документ|соглашение|заявление|правил[оа])\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bдолжн\w*\s+(?P<answer>детально\s+ознакомиться\s+с\s+.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<answer>Ломбард\s+не\s+вправе\s+требовать\s+"
        r"выплаты\s+.+?\s+начислен\w*\s+по\s+истечении\s+"
        r"\d+\s+.+?\s+дней\s+просрочки)"
        r"(?:\s+исполнения|[.;]|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bне\s+вправе\s+требовать\s+"
        r"(?P<answer>выплаты\s+.+?\s+начислен\w*\s+по\s+истечении\s+"
        r"\d+\s+.+?\s+дней\s+просрочки)"
        r"(?:\s+исполнения|[.;]|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\bне\s+долж\w*\s+превышать\s+(?P<answer>.+)$", re.IGNORECASE),
    re.compile(
        r"\bразрабатываются\s+и\s+утверждаются\s+(?P<answer>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bуплат\w*\s+вознаграждения.*?\s+(?P<answer>в\s+момент\s+.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bначислен\w*\s+.+?\bосуществляется\s+"
        r"(?P<answer>в\s+момент\s+.+)$",
        re.IGNORECASE,
    ),
    re.compile(r"\bне\s+требуется.*?\b(?P<answer>если\s+.+)$", re.IGNORECASE),
    re.compile(r"\bпрекрат\w*\s+только\s+(?P<answer>после\s+.+)$", re.IGNORECASE),
    re.compile(r"\bвключающ\w*\s+в\s+себя\s+(?P<answer>.+)$", re.IGNORECASE),
)


def _concise_source_span(sentence: str) -> str:
    """Return a shorter exact normative value when grammar makes it unambiguous."""
    cleaned = re.sub(r"^\s*\d+[.)]\s*", "", sentence).strip()
    for pattern in _CONCISE_SOURCE_SPANS:
        match = pattern.search(cleaned)
        if match is None:
            continue
        answer = match.group("answer").strip().rstrip(".;:")
        if 5 <= len(answer) <= 240:
            return f"{answer[:1].upper()}{answer[1:]}"
    return cleaned


def _structured_list_clauses(value: str) -> list[str]:
    """Extract complete list clauses from one OCR-preserved paragraph."""
    sublist_markers = list(re.finditer(r"(?:^|[.;:]\s*)-\s*\d+[.)]\s+", value))
    if len(sublist_markers) >= 2:
        sublist_clauses: list[str] = []
        for index, marker in enumerate(sublist_markers):
            end = (sublist_markers[index + 1].start()
                   if index + 1 < len(sublist_markers) else len(value))
            clause = value[marker.end():end].strip(" -–—;:.")
            if len(clause) >= 12 and any(character.isalpha() for character in clause):
                sublist_clauses.append(f"{clause[:1].upper()}{clause[1:]}")
        if sublist_clauses:
            return sublist_clauses
    markers = list(re.finditer(r"(?:^|[.;:]\s*|[-–—]\s*)\d+[.)]\s+", value))
    if len(markers) >= 2:
        clauses: list[str] = []
        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(value)
            clause = value[marker.end():end].strip(" -–—;:.")
            if len(clause) >= 12 and any(character.isalpha() for character in clause):
                clauses.append(f"{clause[:1].upper()}{clause[1:]}")
        return clauses
    if value.count(";") < 2:
        return []
    body = value.partition(":")[2] or value
    return [
        f"{clause[:1].upper()}{clause[1:]}"
        for raw_clause in body.split(";")
        if (clause := raw_clause.strip(" -–—;:."))
        and len(clause) >= 20
        and any(character.isalpha() for character in clause)
    ]


def _axis_kind(fact: SourceFact) -> AssessmentAxisKind:
    value = _norm(fact.value)
    if re.search(r"\d|%|\b(?:минут|час|дн|день|месяц)", value):
        return "numeric_value"
    if re.search(r"\b(?:правил|требован|запрещ|нельзя|долж|разреш|обязат)", _norm(fact.attribute + " " + fact.value)):
        return "rule_value"
    return "attribute"


def _source_owned_correct_value(fact: SourceFact) -> str:
    """Select one exact actionable sentence from a narrative paragraph.

    Facts retain exact source wording, but a multi-sentence spreadsheet cell or
    narrative paragraph must not become an obvious long answer key. The axis is
    one atomic source claim; the lesson still retains the complete fact.
    """
    structured_clauses = _structured_list_clauses(fact.value)
    sentences = structured_clauses or [
        match.group(0).strip()
        for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", fact.value)
        if match.group(0).strip()
    ]
    if len(sentences) <= 1:
        return _concise_source_span(fact.value.strip())

    def score(sentence: str) -> tuple[int, int]:
        normalized = _norm(sentence)
        points = 0
        if re.search(r"\b(?:если|когда|при|unless|when|if)\b", normalized):
            points += 8
        points += 3 * len(re.findall(
            r"\b(?:долж\w*|нельзя|запрещ\w*|отказ\w*|предлаг\w*|"
            r"переда\w*|использ\w*|требу\w*|must|shall|refus\w*|offer\w*)\b",
            normalized,
        ))
        if re.search(r"\b(?:сотрудник|клиент|оператор|employee|customer|operator)\b", normalized):
            points += 2
        if re.match(r"^(?:это|данное|такое|this|it)\b", normalized):
            points -= 5
        if 40 <= len(sentence) <= 240:
            points += 2
        return points, -len(sentence)

    return _concise_source_span(max(sentences, key=score))


def _is_dependent_source_fragment(value: str) -> bool:
    """Reject introductory source fragments that cannot stand as an answer.

    PDF/list splitting can leave a gerund phrase such as ``Получив информацию
    и ознакомившись ...`` without the independent clause that states what the
    person then confirms or does.  Such text is evidence context, not an
    assessable fact.  A comma is intentionally required before a possible
    independent clause, so complete sentences such as ``Получив документ,
    сотрудник обязан ...`` remain eligible.
    """
    stripped = value.strip()
    return bool(_DEPENDENT_LEADING_FRAGMENT.match(stripped)) and "," not in stripped


def _required_prompt(correct_value: str) -> str:
    open_information = re.fullmatch(
        r"(?P<subject>.+?)\s+являются\s+открытой\s+информацией\s+и\s+"
        r"не\s+могут\s+быть\s+предметом\s+коммерческой\s+тайны\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if open_information is not None:
        subject = open_information.group("subject").strip()
        return (
            f"Являются ли {subject[:1].lower()}{subject[1:]} открытой информацией "
            "и могут ли быть предметом коммерческой тайны?"
        )
    negative_right = re.fullmatch(
        r"(?P<actor>.+?)\s+не\s+вправе\s+(?P<action>требовать\s+.+?)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if negative_right is not None:
        return (
            f"Вправе ли {negative_right.group('actor').strip()} "
            f"{negative_right.group('action').strip()}?"
        )
    not_admitted = re.fullmatch(
        r"(?P<subject>.+?)\s+не\s+допускается\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if not_admitted is not None:
        subject = not_admitted.group("subject").strip()
        return f"Допускается ли {subject[:1].lower()}{subject[1:]}?"
    optional = re.fullmatch(
        r"(?P<subject>.+?)\s+не\s+(?:требуется|обязательн[оаы]?|нужно)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if optional is not None:
        subject = optional.group("subject").strip()
        if subject:
            subject = subject[:1].lower() + subject[1:]
            return f"Требуется ли {subject}?"
    prohibited = re.fullmatch(
        r"(?P<object>.+?)\s+нельзя\s+(?P<verb>[^\s]+)(?P<tail>.*)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if prohibited is not None:
        subject = prohibited.group("object").strip()
        subject = subject[:1].lower() + subject[1:]
        tail = prohibited.group("tail").strip().rstrip(".")
        return " ".join(
            part for part in (
                "Допустимо ли",
                prohibited.group("verb").strip(),
                subject,
                tail,
            ) if part
        ) + "?"
    return ""


def _contextualized_list_axis(fact: SourceFact, source_value: str) -> tuple[str, str]:
    """Attach a list preamble to one selected item without model-owned truth."""
    normalized_source = _norm(fact.value)
    item = source_value.strip().rstrip(".;:")
    item_lower = f"{item[:1].lower()}{item[1:]}" if item else item
    if "не допускается принятие в залог" in normalized_source:
        return (
            f"Нет, принятие в залог {item_lower} не допускается.",
            f"Допускается ли принятие в залог {item_lower}?",
        )
    if "имеет право принимать в залог" in normalized_source:
        return (
            f"Да, Ломбард вправе принимать в залог {item_lower}.",
            f"Вправе ли Ломбард принимать в залог {item_lower}?",
        )
    if "вправе отказать" in normalized_source and "основан" in normalized_source:
        return (
            f"Да, {item_lower} является основанием для отказа в предоставлении микрокредита.",
            f"Является ли {item_lower} основанием для отказа в предоставлении микрокредита?",
        )
    if "персональные данные подлежат уничтожению" in normalized_source:
        condition = item_lower
        return (
            f"Да, персональные данные подлежат уничтожению {condition}.",
            f"Подлежат ли персональные данные уничтожению {condition}?",
        )
    return source_value, ""


def _server_owned_inverse(correct_value: str) -> str | None:
    """Build an exact binary opposite for server-owned yes/no statements.

    Asking a model for several distractors to a binary normative statement
    only creates paraphrases of the same mistake.  For patterns whose truth
    and negation are unambiguous, the server owns both choices and emits a
    true/false assessment instead.
    """
    optional = re.fullmatch(
        r"(?P<subject>.+?)\s+не\s+(?:требуется|обязательн[оаы]?|нужно)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if optional is not None:
        return f"{optional.group('subject').strip()} требуется."
    open_information = re.fullmatch(
        r"(?P<subject>.+?)\s+являются\s+открытой\s+информацией\s+и\s+"
        r"не\s+могут\s+быть\s+предметом\s+коммерческой\s+тайны\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if open_information is not None:
        return (
            f"{open_information.group('subject').strip()} не являются открытой "
            "информацией и могут быть предметом коммерческой тайны."
        )
    negative_right = re.fullmatch(
        r"(?P<actor>.+?)\s+не\s+вправе\s+(?P<action>.+?)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if negative_right is not None:
        return (
            f"{negative_right.group('actor').strip()} вправе "
            f"{negative_right.group('action').strip()}."
        )
    not_admitted = re.fullmatch(
        r"(?P<subject>.+?)\s+не\s+допускается\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if not_admitted is not None:
        return f"{not_admitted.group('subject').strip()} допускается."
    return None


def derive_assessment_axes(
    lesson: LessonDraft,
    facts: list[SourceFact],
    *,
    block_id: str,
) -> tuple[AssessmentAxis, ...]:
    """Derive stable, unambiguous answer targets without a provider call."""
    eligible = [
        fact
        for fact in facts
        if fact.fact_id in lesson.fact_ids
        and fact.value.strip()
        and fact.confidence >= 0.8
        and fact.uncertainty in {"", "local_ocr"}
        and not _LOW_VALUE_ATTRIBUTE.fullmatch(fact.attribute.strip())
        and not _has_ambiguous_formula_symbol(fact)
    ]
    result: list[AssessmentAxis] = []
    seen: set[tuple[str, str, str]] = set()
    source_order = {fact_id: index for index, fact_id in enumerate(lesson.fact_ids)}
    eligible.sort(key=lambda item: (source_order.get(item.fact_id, len(source_order)), item.fact_id))
    for fact in eligible:
        source_value = _source_owned_correct_value(fact)
        if _is_dependent_source_fragment(source_value):
            continue
        correct_value, required_prompt = _contextualized_list_axis(fact, source_value)
        required_prompt = required_prompt or _required_prompt(correct_value)
        normalized_value = _norm(correct_value)
        identity = (_norm(fact.subject), _norm(fact.attribute), normalized_value)
        if identity in seen:
            continue
        seen.add(identity)
        digest = hashlib.sha256(
            "|".join((
                "assessment-axis",
                lesson.lesson_id,
                block_id,
                fact.fact_id,
                _norm(fact.attribute),
                normalized_value,
            )).encode("utf-8")
        ).hexdigest()[:20]
        peers = tuple(
            peer.fact_id
            for peer in eligible
            if peer.fact_id != fact.fact_id
            and _norm(peer.attribute) == _norm(fact.attribute)
            and _norm(peer.value) != normalized_value
        )
        result.append(AssessmentAxis(
            axis_id=f"axis-{digest}",
            lesson_id=lesson.lesson_id,
            semantic_block_id=block_id,
            primary_fact_id=fact.fact_id,
            evidence_fact_ids=(fact.fact_id,),
            subject=fact.subject.strip(),
            attribute=fact.attribute.strip(),
            required_prompt=required_prompt,
            correct_value=correct_value,
            normalized_correct_value=normalized_value,
            eligible_distractor_fact_ids=peers,
            axis_kind=_axis_kind(fact),
        ))
    return tuple(result)


def materialize_assessment(
    axis: AssessmentAxis,
    authored: AuthoredAssessment,
    *,
    repaired_prompt: str = "",
) -> QuestionDraft | None:
    """Attach server truth to provider wording, or reject malformed wording."""
    if authored.axis_id != axis.axis_id or not authored.prompt.strip():
        return None
    distractors = tuple(item.strip() for item in authored.distractors if item.strip())
    inverse = _server_owned_inverse(axis.correct_value)
    if inverse is not None:
        distractors = (inverse,)
    elif not 2 <= len(distractors) <= 3:
        return None
    normalized = [_norm(item) for item in distractors]
    if len(set(normalized)) != len(normalized):
        return None
    if axis.normalized_correct_value in normalized:
        return None
    prompt = axis.required_prompt or authored.prompt.strip()
    return QuestionDraft(
        question_id=f"semantic-{axis.axis_id.removeprefix('axis-')}",
        lesson_id=axis.lesson_id,
        kind="true_false" if inverse is not None else "single_choice",
        prompt=prompt,
        options=(axis.correct_value, *distractors),
        correct_answer=axis.correct_value,
        explanation=axis.correct_value,
        fact_id=axis.primary_fact_id,
        evidence_fact_ids=axis.evidence_fact_ids,
        source_quote=axis.correct_value,
        semantic_block_id=axis.semantic_block_id,
        repaired_prompt=repaired_prompt,
    )
