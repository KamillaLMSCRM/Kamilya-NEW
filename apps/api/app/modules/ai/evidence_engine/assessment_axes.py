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
    DistractorConstraint,
    DistractorSourceRelation,
    LessonDraft,
    QuestionDraft,
    SourceFact,
    is_tabular_locator,
)


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


_ANCHOR_TOKEN = re.compile(r"[^\W_]+", flags=re.UNICODE)
_BARE_NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)?")
_NUMBER_WITH_OPTIONAL_UNIT = re.compile(
    r"\s*(?P<number>[+-]?\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>[%A-Za-zА-Яа-яЁё°²³/.-]+)?\s*"
)


def _conservative_stem(token: str) -> str:
    """Normalize only common inflections; lexical meaning remains source-owned."""
    if len(token) >= 5 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) >= 5 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    for suffix in ("ами", "ями", "ого", "ему", "ому", "ыми", "ими", "ах", "ях", "ов", "ев"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    if len(token) >= 6 and token[-1] in "аеиоуыэюя":
        return token[:-1]
    return token


def _lexical_anchors(text: str) -> frozenset[str]:
    return frozenset(
        _conservative_stem(token)
        for token in _ANCHOR_TOKEN.findall(_norm(text))
        if len(token) >= 3
    )


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

    def score(sentence: str, index: int) -> tuple[int, int, int]:
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
        # Spreadsheet cells normally lead with the direct value for the row
        # attribute and follow with compatibility/context.  Preserve that
        # source order when no later sentence has a stronger normative signal.
        return points, -index, -len(sentence)

    return _concise_source_span(max(
        enumerate(sentences),
        key=lambda item: score(item[1], item[0]),
    )[1])


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
    after_action = re.fullmatch(
        r"После\s+(?P<condition>[^.!?]{5,100}?)\s+"
        r"(?P<actor>сотрудник|работник|оператор)\s+(?P<action>[^.!?]{5,160})\.?",
        correct_value.strip(), flags=re.IGNORECASE,
    )
    if after_action is not None:
        return (
            f"Что делает {after_action.group('actor').strip()} после "
            f"{after_action.group('condition').strip()}?"
        )
    conditional_action = re.fullmatch(
        r"Если\s+(?P<condition>[^,.!?]{5,100}),\s+(?P<action>[^.!?]{5,180})\.?",
        correct_value.strip(), flags=re.IGNORECASE,
    )
    if conditional_action is not None and re.search(
        r"\b(?:долж\w*|нельзя|(?:не\s+)?\w+(?:ют|ет|ит))\b",
        conditional_action.group("action"), flags=re.IGNORECASE,
    ):
        return f"Как следует поступить, если {conditional_action.group('condition').strip()}?"
    refusal_right = re.fullmatch(
        r"(?P<actor>.+?)\s+вправе\s+отказаться\s+от\s+(?P<object>.+?)\.?",
        correct_value.strip(),
        flags=re.IGNORECASE,
    )
    if refusal_right is not None:
        return (
            f"Что вправе сделать {refusal_right.group('actor').strip()} в отношении "
            f"{refusal_right.group('object').strip()}?"
        )
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


def _distractor_constraints(
    target: SourceFact,
    facts: list[SourceFact],
) -> tuple[DistractorConstraint, ...]:
    """Classify source values once so model wording cannot move the tested axis."""
    constraints: list[DistractorConstraint] = []
    seen: set[tuple[str, str]] = set()
    target_subject = _norm(target.subject)
    target_attribute = _norm(target.attribute)
    anchors_by_fact = {
        fact.fact_id: (
            _lexical_anchors(fact.attribute)
            | _lexical_anchors(fact.value)
            | _lexical_anchors(_source_owned_correct_value(fact))
        )
        for fact in facts
    }
    anchor_owners: dict[str, set[str]] = {}
    for fact_id, anchors in anchors_by_fact.items():
        for anchor in anchors:
            anchor_owners.setdefault(anchor, set()).add(fact_id)
    for fact in facts:
        relation: DistractorSourceRelation
        if fact.fact_id == target.fact_id:
            relation = "same_axis"
        elif (
            _norm(fact.attribute) == target_attribute
            and _norm(fact.subject) != target_subject
        ):
            relation = "same_attribute_other_subject"
        else:
            relation = "other_function_or_attribute"
        for value in (fact.value.strip(), _source_owned_correct_value(fact)):
            normalized_value = _norm(value)
            identity = (fact.fact_id, normalized_value)
            if not normalized_value or identity in seen:
                continue
            seen.add(identity)
            constraints.append(DistractorConstraint(
                fact_id=fact.fact_id,
                subject=fact.subject.strip(),
                attribute=fact.attribute.strip(),
                value=value,
                relation=relation,
                attribute_anchors=tuple(sorted(_lexical_anchors(fact.attribute))),
                value_anchors=tuple(sorted(_lexical_anchors(value))),
                distinctive_anchors=tuple(sorted(
                    anchor
                    for anchor in anchors_by_fact[fact.fact_id]
                    if anchor_owners[anchor] == {fact.fact_id}
                )),
            ))
    return tuple(constraints)


def _recognizably_bound_to_source(
    candidate: str,
    candidate_anchors: frozenset[str],
    constraint: DistractorConstraint,
) -> bool:
    # Short workbook values may have only one anchor. A wrong option that
    # quotes another known attribute's exact value is still source-bound,
    # even when the independent reviewer overlooks the axis mismatch.
    source_value = _norm(constraint.value)
    value_quoted = len(source_value) >= 3 and re.search(
        rf"(?<!\w){re.escape(source_value)}(?!\w)", _norm(candidate)
    )
    if value_quoted and (
        len(source_value) >= 6
        or bool(candidate_anchors.intersection(constraint.attribute_anchors))
    ):
        return True
    attribute_hits = candidate_anchors.intersection(constraint.attribute_anchors)
    value_hits = candidate_anchors.intersection(constraint.value_anchors)
    distinctive_hits = candidate_anchors.intersection(constraint.distinctive_anchors)
    value_coverage = len(value_hits) / max(1, len(constraint.value_anchors))
    return bool(
        attribute_hits
        and len(value_hits) >= 2
        and distinctive_hits
        and value_coverage >= 0.6
    ) or (
        len(value_hits) >= 3
        and len(distinctive_hits) >= 2
        and value_coverage >= 0.7
    )


def _prompt_is_bound_to_axis(prompt: str, axis: AssessmentAxis) -> bool:
    """Require generic provider wording to name the server-owned target.

    A provider may paraphrase a question, but it cannot silently switch the
    practical task.  Subject, attribute, or a source-owned value anchor is
    enough to establish that the wording is about this axis.  Normative axes
    already have a server-owned prompt and are handled separately by the
    caller.
    """
    prompt_anchors = _lexical_anchors(prompt)
    axis_anchors = (
        _lexical_anchors(axis.subject)
        | _lexical_anchors(axis.attribute)
        | _lexical_anchors(axis.correct_value)
    )
    return bool(prompt_anchors.intersection(axis_anchors))


def _server_owned_axis_prompt(axis: AssessmentAxis) -> str:
    """Build a neutral prompt when provider wording switches the task."""
    return (
        f"Что верно в отношении «{axis.attribute.strip()}» "
        f"у объекта «{axis.subject.strip()}»?"
    )


def _is_different_same_fact_clause(
    candidate: str,
    axis: AssessmentAxis,
    constraint: DistractorConstraint,
) -> bool:
    """Reject a source clause that answers a different task in this axis.

    Compound spreadsheet cells often contain both the requested attribute and
    a nearby caveat.  The caveat is still from the same fact, so a different
    source-axis check cannot catch it.  Exact clause matching is deliberately
    strict; value-changing counterfactuals remain valid because they are not a
    copied clause.
    """
    if constraint.relation != "same_axis":
        return False
    normalized_candidate = _norm(candidate)
    normalized_correct = _norm(axis.correct_value)
    if normalized_candidate == normalized_correct:
        return False
    clauses = _structured_list_clauses(constraint.value) or [
        match.group(0).strip()
        for match in re.finditer(r"[^.!?]+(?:[.!?]+|$)", constraint.value)
        if match.group(0).strip()
    ]
    return any(
        normalized_candidate == _norm(clause)
        and _norm(clause) != normalized_correct
        for clause in clauses
    )


def _has_comparable_option_shape(axis: AssessmentAxis, candidate: str) -> bool:
    """Keep concise categorical alternatives comparable with the answer key.

    A provider can otherwise answer a question such as "which collection?"
    with one collection name and several full statements about usage scope.
    Those statements may be false and well written, but they do not belong to
    the same answer domain.  The guard is deliberately narrow: it applies only
    to short attribute values and still allows a little contextual wording.
    """
    correct_tokens = _ANCHOR_TOKEN.findall(axis.correct_value)
    if (
        axis.axis_kind != "attribute"
        or len(axis.correct_value) > 50
        or not 1 <= len(correct_tokens) <= 3
    ):
        return True
    candidate_tokens = _ANCHOR_TOKEN.findall(candidate)
    return len(candidate_tokens) <= len(correct_tokens) + 3


def _normalize_bare_numeric_distractors(
    axis: AssessmentAxis,
    distractors: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Remove an answer-position cue when the source key is a bare number.

    Spreadsheet sources often store a dimension as ``720`` while a provider
    phrases alternatives as ``560 мм``.  Keeping that formatting would expose
    the correct option.  The unit is not invented for the key; instead, every
    option is reduced to its numeric value.  A nonnumeric alternative fails
    closed because it is not comparable with this source-owned numeric axis.
    """
    if axis.axis_kind != "numeric_value" or not _BARE_NUMBER.fullmatch(
        axis.correct_value.strip()
    ):
        return distractors
    normalized: list[str] = []
    for distractor in distractors:
        match = _NUMBER_WITH_OPTIONAL_UNIT.fullmatch(distractor)
        if match is None:
            return None
        normalized.append(match.group("number"))
    return tuple(normalized)


def _admissible_source_distractors(
    axis: AssessmentAxis,
    distractors: tuple[str, ...],
    prompt: str,
) -> bool:
    """Allow a cited alternative only for the target attribute and named subject.

    Free-form wrong options remain provider-authored hypotheses.  A candidate
    that exactly restates an admitted source value is different: the source
    gives the server enough information to determine whether it answers this
    axis.  Ambiguous duplicate source values fail closed.
    """
    for distractor in distractors:
        if not _has_comparable_option_shape(axis, distractor):
            return False
        normalized_distractor = _norm(distractor)
        candidate_anchors = _lexical_anchors(distractor)
        exact_matches = [
            constraint
            for constraint in axis.distractor_constraints
            if _norm(constraint.value) == normalized_distractor
        ]
        # Exact same-axis source text is another copy of the key.  Fuzzy
        # same-axis overlap is deliberately not enough: a useful
        # counterfactual often differs from the true value by one term (movable
        # vs immovable property, 15 vs 30 days).  The independent reviewer owns
        # semantic equivalence; this deterministic boundary only rejects exact
        # keys and candidates recognizably bound to a different source axis.
        if any(match.relation == "same_axis" for match in exact_matches):
            return False
        if any(
            _is_different_same_fact_clause(distractor, axis, constraint)
            for constraint in axis.distractor_constraints
        ):
            return False
        source_matches = [
            constraint
            for constraint in axis.distractor_constraints
            if constraint.relation != "same_axis"
            and (
                constraint in exact_matches
                or _recognizably_bound_to_source(distractor, candidate_anchors, constraint)
            )
        ]
        if not source_matches:
            continue
        if (
            _norm(axis.subject) not in _norm(prompt)
            or any(
                match.relation != "same_attribute_other_subject"
                for match in source_matches
            )
        ):
            return False
    return True


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
        if not required_prompt and is_tabular_locator(fact.source_locator):
            # Keep the source-owned table subject and attribute in the stem;
            # a provider may propose alternatives, not recast a collection as
            # one product inferred from an attribute value or catalog row.
            required_prompt = (
                f"Что указано в характеристике «{fact.attribute.strip()}» "
                f"для «{fact.subject.strip()}»?"
            )
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
            and _norm(peer.subject) != _norm(fact.subject)
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
            distractor_constraints=_distractor_constraints(fact, eligible),
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
    normalized_numeric = _normalize_bare_numeric_distractors(axis, distractors)
    if normalized_numeric is None:
        return None
    distractors = normalized_numeric
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
    authored_prompt = authored.prompt.strip()
    if inverse is None and not _admissible_source_distractors(
        axis, distractors, authored_prompt
    ):
        return None
    if axis.required_prompt:
        prompt = axis.required_prompt
    elif _prompt_is_bound_to_axis(authored_prompt, axis):
        prompt = authored_prompt
    else:
        prompt = _server_owned_axis_prompt(axis)
    if inverse is None and not _admissible_source_distractors(axis, distractors, prompt):
        return None
    explanation = _teaching_explanation(axis)
    return QuestionDraft(
        question_id=f"semantic-{axis.axis_id.removeprefix('axis-')}",
        lesson_id=axis.lesson_id,
        kind="true_false" if inverse is not None else "single_choice",
        prompt=prompt,
        options=(axis.correct_value, *distractors),
        correct_answer=axis.correct_value,
        explanation=explanation,
        fact_id=axis.primary_fact_id,
        evidence_fact_ids=axis.evidence_fact_ids,
        source_quote=axis.correct_value,
        semantic_block_id=axis.semantic_block_id,
        repaired_prompt=repaired_prompt,
    )


def _teaching_explanation(axis: AssessmentAxis) -> str:
    """Explain the server-owned key without trusting provider prose."""
    sample = f"{axis.subject} {axis.attribute} {axis.correct_value}".casefold()
    if any(character in sample for character in "әғқңөұүһі"):
        if axis.axis_kind == "numeric_value":
            return (
                f"«{axis.subject}» үшін дереккөзде «{axis.attribute}» параметрі "
                f"«{axis.correct_value}» деп көрсетілген. Басқа мән көрсетілген "
                "параметрді өзгертер еді."
            )
        if axis.axis_kind == "rule_value":
            return (
                f"Сұрақ «{axis.subject}» үшін «{axis.attribute}» ережесін тексереді. "
                f"Дереккөзде тікелей «{axis.correct_value}» деп көрсетілген; осы "
                "ережені қолдану қажет."
            )
        return (
            f"«{axis.subject}» үшін «{axis.attribute}» сипаттамасы тексеріледі. "
            f"Дереккөзде оған «{axis.correct_value}» мәні сәйкес келеді, сондықтан "
            "басқа мән бұл сипаттаманы білдірмейді."
        )
    if not re.search(r"[а-яё]", sample):
        if axis.axis_kind == "numeric_value":
            return (
                f"For “{axis.subject}”, the source sets “{axis.attribute}” to "
                f"“{axis.correct_value}”. A different value would change the stated parameter."
            )
        if axis.axis_kind == "rule_value":
            return (
                f"This question checks the “{axis.attribute}” rule for “{axis.subject}”. "
                f"The source states: “{axis.correct_value}”; this is the rule to apply."
            )
        return (
            f"This question checks the “{axis.attribute}” characteristic for "
            f"“{axis.subject}”. The source gives “{axis.correct_value}”, so a different "
            "value does not describe that characteristic."
        )
    if axis.axis_kind == "numeric_value":
        return (
            f"Для «{axis.subject}» параметр «{axis.attribute}» в источнике "
            f"задан так: «{axis.correct_value}». Другое значение изменило бы "
            "указанный параметр."
        )
    if axis.axis_kind == "rule_value":
        return (
            f"Вопрос проверяет правило «{axis.attribute}» для «{axis.subject}». "
            f"Источник прямо устанавливает: «{axis.correct_value}»; именно это "
            "правило следует применить."
        )
    return (
        f"Для «{axis.subject}» проверяется характеристика «{axis.attribute}». "
        f"В источнике ей соответствует значение «{axis.correct_value}», поэтому "
        "вариант с другим значением не описывает эту характеристику."
    )
