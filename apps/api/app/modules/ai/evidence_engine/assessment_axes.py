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
from .quality import MAX_ASSESSMENT_ANSWER_CHARS
from .temporal_units import has_temporal_unit


def _norm(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


def operational_claim_priority(claim: str) -> tuple[int, int]:
    """Rank explicit source actions; this is a heuristic, not a safety proof."""
    value = _norm(claim)
    prohibition = bool(re.search(
        r"\b(?:нельзя|запрещ\w*|не\s+допуска\w*|не\s+вправе|"
        r"(?:must|shall)\s+not|do\s+not|prohibit\w*|forbidden|"
        r"тыйым\s+сал\w*|құқылы\s+емес|құқығы\s+жоқ)\b", value,
    ))
    conditional = bool(re.search(r"\b(?:если|когда|при|if|when|unless|егер)\b", value))
    stop = bool(re.search(
        r"\b(?:останов(?:ите|ить)|приостанов(?:ите|ить)|прекрат(?:ите|ить)|"
        r"не\s+продолж(?:айте|ать)|не\s+выдава(?:йте|ть)|"
        r"stop|halt|suspend|тоқтат\w*|бермеңіз)\b", value,
    ))
    escalation = bool(re.search(
        r"\b(?:обратитесь|сообщите|уведомите|notify|escalate|report|contact|хабарла\w*|жүгін\w*)\b", value,
    ))
    operational = prohibition or stop or escalation or bool(re.search(
        r"\b(?:проверь\w*|запиш\w*|отмет\w*|сверь\w*|переда\w*|"
        r"обесточ\w*|отключ\w*|осмотр\w*|"
        r"check|verify|record|log|тексер\w*|жазы\w*|белгіле\w*)\b", value,
    ))
    return int(prohibition or stop or (conditional and escalation)), int(operational)


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

# One complete infinitive action followed by a categorical prohibition. Do not
# invert arbitrary paragraphs, quoted claims or mixed permission/prohibition rules.
_POSTFIX_ACTION_PROHIBITION = re.compile(
    r"(?!.*\b(?:не|можно|нельзя|разрешен\w*)\b)"
    r'(?P<action>[А-Яа-яЁё]+(?:ть|ти|чь)\s+[^.!?;,«»"“”]+?)\s+запрещено\.?',
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
    explicit = _explicit_structured_list(value)
    if explicit is not None:
        return [clause for _position, clause in explicit[1]]
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


def _explicit_structured_list(
    value: str,
) -> tuple[str, list[tuple[int, str]]] | None:
    """Return an explicit numbered/bulleted list and its source preamble.

    Semicolon-separated prose remains eligible for the existing single-axis
    selector, but it is intentionally not expanded here. Expansion requires at
    least two visible source markers so ordinary long prose cannot multiply the
    lesson's assessment contracts.
    """
    markers = list(re.finditer(
        r"(?m)(?:^[ \t]*|[;:][ \t]+)(?P<marker>"
        r"(?:[-*•▪‣–—][ \t]+(?:\d{1,2}[.)][ \t]+)?)|"
        r"(?:\d{1,2}[.)][ \t]+))",
        value,
    ))
    if len(markers) < 2:
        return None
    preamble = value[:markers[0].start()].strip(" \t\r\n-–—;:.")
    clauses: list[tuple[int, str]] = []
    for position, marker in enumerate(markers, start=1):
        end = markers[position].start() if position < len(markers) else len(value)
        clause = value[marker.end():end].strip(" \t\r\n-–—;:.")
        if len(clause) >= 12 and any(character.isalpha() for character in clause):
            clauses.append((position, clause))
    if len(clauses) < 2:
        return None
    return preamble, clauses


_PURE_LIST_EXCEPTION = re.compile(
    r"^(?:кроме\b|за\s+исключением\b|исключени\w*\s*:|except\b)",
    flags=re.IGNORECASE,
)

def _split_action_qualifier(action_object: str) -> tuple[str, str]:
    """Keep a source exception visible without making it the action object."""
    qualified = re.fullmatch(
        r"(?P<target>.+?),\s*(?P<qualifier>"
        r"(?:кроме|за\s+исключением|except)\b.+)",
        action_object.strip(),
        flags=re.IGNORECASE,
    )
    if qualified is None:
        return action_object.strip(), ""
    return qualified.group("target").strip(), qualified.group("qualifier").strip()


def _operational_clause_parts(clause: str) -> tuple[str, str, bool] | None:
    """Return exact object, condition/exception, and prohibition semantics."""
    stripped = clause.strip()
    if _PURE_LIST_EXCEPTION.match(stripped):
        return None
    prohibited = bool(re.search(
        r"\b(?:нельзя|запрещ\w*|не\s+допуска\w*|must\s+not|forbidden)\b",
        _norm(stripped),
    ))
    conditional = re.match(
        r"^(?P<condition>(?:если|когда|при|в\s+случае)\b.+?),\s*"
        r"(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+"
        r"(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if conditional is not None:
        target, qualifier = _split_action_qualifier(conditional.group("target"))
        condition = conditional.group("condition").strip()
        context = "; ".join(item for item in (condition, qualifier) if item)
        return (target, context, prohibited) if target else None
    conditional_without_comma = re.match(
        r"^(?P<condition>(?:в\s+случае|при)\b.+?)\s+"
        r"(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+"
        r"(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if conditional_without_comma is not None:
        target, qualifier = _split_action_qualifier(
            conditional_without_comma.group("target")
        )
        condition = conditional_without_comma.group("condition").strip()
        context = "; ".join(item for item in (condition, qualifier) if item)
        return (target, context, prohibited) if target else None
    prohibition = re.match(
        r"^(?:запрещено|не\s+допускается)\s+(?:не\s+)?"
        r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if prohibition is not None:
        target, qualifier = _split_action_qualifier(prohibition.group("target"))
        return (target, qualifier, True) if target else None
    leading = re.match(
        r"^(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if leading is not None:
        target, qualifier = _split_action_qualifier(leading.group("target"))
        return (target, qualifier, prohibited) if target else None
    actor_action = re.match(
        r"^.+?\b(?:долж\w*|обязан\w*|запрещ\w*|не\s+допуска\w*)\s+(?:не\s+)?"
        r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if actor_action is None:
        return None
    target, qualifier = _split_action_qualifier(actor_action.group("target"))
    return (target, qualifier, prohibited) if target else None


def _structured_operational_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind safe source list actions to distinct, context-preserving prompts."""
    structured = _explicit_structured_list(fact.value)
    if structured is None:
        return []
    preamble, clauses = structured
    if not preamble or len(preamble) > 240:
        return []
    operational = [
        (position, clause, parts)
        for position, clause in clauses
        if (parts := _operational_clause_parts(clause)) is not None
    ]
    if len(operational) < 2:
        return []
    preamble_prohibited = bool(re.search(
        r"\b(?:нельзя|запрещ\w*|не\s+допуска\w*|must\s+not|forbidden)\b",
        _norm(preamble),
    ))
    axes: list[tuple[str, str]] = []
    for _position, clause, (target, qualifier, clause_prohibited) in operational:
        condition = f" с учетом условия «{qualifier}»" if qualifier else ""
        if preamble_prohibited or clause_prohibited:
            prompt = (
                f"Какое действие в отношении «{target}» запрещено{condition} "
                f"требованием «{preamble}»?"
            )
        else:
            prompt = (
                f"Какое действие в отношении «{target}» предусмотрено{condition} "
                f"требованием «{preamble}»?"
            )
        axes.append((clause, prompt))
    return axes


_SINGLE_NUMBERED_ACTION = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+\.?\s*)?"
    r"(?P<preamble>[^:]{12,200}?\b(?:долж\w*|обязан\w*|следует))\s*:\s*"
    r"(?:\d{1,2}[.)]\s*)?[-–—]\s*"
    r"(?P<action>(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+.+?)"
    r"\s*[;.]?\s*$",
    flags=re.IGNORECASE,
)


def _single_numbered_action_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind one explicit numbered action to its actor preamble and exceptions."""
    if _explicit_structured_list(fact.value) is not None:
        return []
    match = _SINGLE_NUMBERED_ACTION.fullmatch(fact.value)
    if match is None:
        return []
    preamble = match.group("preamble").strip()
    action = match.group("action").strip()
    if (
        not 12 <= len(action) <= MAX_ASSESSMENT_ANSWER_CHARS
        or _PURE_LIST_EXCEPTION.match(action)
        or _is_dependent_source_fragment(action)
        or _operational_clause_parts(action) is None
    ):
        return []
    prompt = (
        f"Для «{fact.subject.strip()}» в характеристике "
        f"«{fact.attribute.strip()}»: какое действие предусмотрено требованием "
        f"«{preamble}»?"
    )
    return [(action, prompt)]


_REGULATORY_RANGE_RE = re.compile(
    r"(?P<answer>\bот\s+\d[\d \u00a0]*\s+(?:"
    r"до\s+\d[\d \u00a0]*\s+тенге|тенге\s+и\s+выше))\s+"
    r"(?:для\s+)?РД\s+(?P<region>г\.\s*[А-ЯЁ][А-Яа-яЁё-]+)",
    flags=re.IGNORECASE,
)
_SOURCE_ABBREVIATION_TAIL = re.compile(
    r"(?:\b(?:г|ул|д|стр|рис|им|др)\.|\bп\.\s*\d+\.|"
    r"\b(?:т\.\s*п|т\.\s*д|и\s+др)\.)$",
    flags=re.IGNORECASE,
)
_DEPENDENT_TABLE_CLAUSE = re.compile(
    r"^(?:в\s+этом|в\s+таком|при\s+этом|в\s+случае\s+сво|"
    r"после\s+получения\s+(?:такой|этой)|подписанием|на\s+основании|"
    r"аналогич|указанн|вышеуказанн|он\b|она\b|они\b|это\b)",
    flags=re.IGNORECASE,
)


def _source_sentences(value: str) -> list[str]:
    """Split source sentences without treating common abbreviations as stops."""
    result: list[str] = []
    start = 0
    for boundary in re.finditer(r"[.!?]+(?=\s+(?:[*]?[А-ЯЁA-Z0-9]))", value):
        prefix = value[start:boundary.end()].rstrip()
        if _SOURCE_ABBREVIATION_TAIL.search(prefix):
            continue
        if prefix:
            result.append(prefix.strip())
        start = boundary.end()
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


_EXPLICIT_THEN_CONDITION = re.compile(
    r"^(?P<condition>(?:если|в\s+случае\s+если|когда|при\s+условии)\b.+),\s*"
    r"то\s+(?P<action>.+)$",
    flags=re.IGNORECASE,
)
_MODAL_CONDITION = re.compile(
    r"^(?P<condition>(?:если|в\s+случае\s+если|когда|при\s+условии)\b.+),\s*"
    r"(?P<action>(?:необходимо|следует|нужно|требуется)\b.+)$",
    flags=re.IGNORECASE,
)
_NORMATIVE_CONSEQUENCE = re.compile(
    r"\b(?:долж\w*|обязан\w*|необходим\w*|следует|нужно|требуется|"
    r"запрещ\w*|не\s+[А-Яа-яЁё]+(?:ется|ются|ит|ют))\b",
    flags=re.IGNORECASE,
)
_DEADLINE_VALUES = (
    re.compile(
        r"\bв\s+(?:первый|следующий)\s+рабочий\s+день"
        r"(?:\s+с\s+момента\s+[^,.;!?]+)?",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\bв\s+течени[еи]\s+\d+(?:-[^\s,.;!?]+)?\s+[^\s,.;!?]+"
        r"(?:\s+с\s+момента\s+[^,.;!?]+)?",
        flags=re.IGNORECASE,
    ),
)


def _without_source_marker(sentence: str) -> str:
    return re.sub(
        r"^\s*[*]?\s*(?:\d+(?:\.\d+)*[.)]?\s+)?",
        "",
        sentence,
        count=1,
    ).strip()


def _conditional_rule_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Project a complete long conditional into source-owned condition/action roles."""
    if len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS:
        return []
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        match = _EXPLICIT_THEN_CONDITION.fullmatch(clause)
        if match is None:
            match = _MODAL_CONDITION.fullmatch(clause)
        if match is None:
            continue
        condition = match.group("condition").strip()
        action = match.group("action").strip()
        if (
            not 12 <= len(condition)
            or not 12 <= len(action) <= MAX_ASSESSMENT_ANSWER_CHARS
            or not _NORMATIVE_CONSEQUENCE.search(action)
            or _PURE_LIST_EXCEPTION.match(action)
            or _is_dependent_source_fragment(action)
        ):
            continue
        prompt = (
            f"Для «{fact.subject.strip()}» в характеристике "
            f"«{fact.attribute.strip()}»: какое действие предусмотрено при условии "
            f"«{condition}»?"
        )
        axes.append((action, prompt))
    return axes


def _has_same_conditional_target(value: str, projections: list[tuple[str, str]]) -> bool:
    """A complete conditional and its exact condition/action projection are one target."""
    clause = _without_source_marker(value)
    match = _EXPLICIT_THEN_CONDITION.fullmatch(clause) or _MODAL_CONDITION.fullmatch(clause)
    if match is None:
        return False
    condition = _norm(match.group("condition"))
    action = _norm(match.group("action"))
    return any(_norm(answer) == action and condition in _norm(prompt)
               for answer, prompt in projections)


def _deadline_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Extract exact bounded deadlines while retaining their whole source rule."""
    if len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS:
        return []
    sentences = _source_sentences(fact.value)
    axes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, sentence in enumerate(sentences):
        matches = sorted(
            (
                match
                for pattern in _DEADLINE_VALUES
                for match in pattern.finditer(sentence)
            ),
            key=lambda item: item.start(),
        )
        for match in matches:
            answer = match.group(0).strip()
            if (
                answer in seen
                or len(answer) > MAX_ASSESSMENT_ANSWER_CHARS
                or not has_temporal_unit(answer)
            ):
                continue
            source_rule = f"{sentence[:match.start()]}_____{sentence[match.end():]}"
            if _DEPENDENT_TABLE_CLAUSE.match(_without_source_marker(sentence)):
                if index == 0:
                    continue
                source_rule = f"{sentences[index - 1]} {source_rule}"
            prompt = (
                f"Для «{fact.subject.strip()}» в характеристике "
                f"«{fact.attribute.strip()}»: какой точный срок пропущен в исходном "
                f"правиле «{source_rule.strip()}»?"
            )
            axes.append((answer, prompt))
            seen.add(answer)
    return axes


def _regulatory_table_range_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind each repeated monetary range to its contiguous region cohort."""
    if not is_tabular_locator(fact.source_locator):
        return []
    matches = list(_REGULATORY_RANGE_RE.finditer(fact.value))
    if len(matches) < 2:
        return []
    axes: list[tuple[str, str]] = []
    for match in matches:
        answer = match.group("answer").strip()
        region = match.group("region").strip()
        if len(answer) > MAX_ASSESSMENT_ANSWER_CHARS:
            return []
        prompt = (
            f"Какое значение характеристики «{fact.attribute.strip()}» указано "
            f"для «{fact.subject.strip()}» в РД {region}?"
        )
        axes.append((answer, prompt))
    return axes


def _table_clause_prompt(fact: SourceFact, clause: str) -> str:
    """Build a mandatory row-owned prompt only for a standalone action clause."""
    prompt = _required_prompt(clause)
    if not prompt:
        parts = _operational_clause_parts(clause.rstrip(".;"))
        if parts is None:
            return ""
        target, qualifier, prohibited = parts
        condition = f" с учетом условия «{qualifier}»" if qualifier else ""
        if prohibited:
            prompt = f"Какое действие в отношении «{target}» запрещено{condition}?"
        else:
            prompt = f"Какое действие в отношении «{target}» предусмотрено{condition}?"
    return (
        f"Для «{fact.subject.strip()}» в характеристике "
        f"«{fact.attribute.strip()}»: {prompt}"
    )


def _compound_table_operational_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Atomize only long table cells with complete, independently promptable rules."""
    if (
        not is_tabular_locator(fact.source_locator)
        or len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
    ):
        return []
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = re.sub(r"^\s*\d+[.)]\s*", "", sentence).strip()
        if (
            not 20 <= len(clause) <= MAX_ASSESSMENT_ANSWER_CHARS
            or clause.endswith((":", ";"))
            or any(pattern.search(clause) for pattern in _DEADLINE_VALUES)
            or _DEPENDENT_TABLE_CLAUSE.match(clause)
            or _is_dependent_source_fragment(clause)
        ):
            continue
        prompt = _table_clause_prompt(fact, clause)
        if prompt:
            axes.append((clause, prompt))
    return axes


def has_partial_unatomized_source_contract(fact: SourceFact) -> bool:
    """Flag rich table cells whose safe axes do not claim complete cell coverage."""
    if (
        not is_tabular_locator(fact.source_locator)
        or len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
        or _structured_operational_axes(fact)
        or _regulatory_table_range_axes(fact)
    ):
        return False
    return bool(_compound_table_operational_axes(fact))


def _unsupported_operational_list(fact: SourceFact) -> bool:
    """Fail closed when independent actions have no safe shared context."""
    structured = _explicit_structured_list(fact.value)
    if structured is None:
        return False
    preamble, clauses = structured
    operational_count = sum(
        _operational_clause_parts(clause) is not None
        for _position, clause in clauses
    )
    return operational_count >= 2 and (not preamble or len(preamble) > 240)


_AUTO_NARRATIVE_ATTRIBUTES = {
    "срок",
    "финансовое условие",
    "право",
    "обязанность",
    "запрет",
    "положение",
}

def _claim_attribute(value: str) -> str:
    """Classify the exact claim selected from a larger narrative evidence unit."""
    normalized = _norm(value)
    if has_temporal_unit(normalized) or re.search(r"\bсрок\w*\b", normalized):
        return "срок"
    if re.search(r"\b(?:ставк|вознагражден|тенге|сумм)\w*\b", normalized):
        return "финансовое условие"
    if re.search(
        r"(?:\bнельзя\b|\bзапрещен\w*\b|\bне допускается\b|\bне вправе\b)",
        normalized,
    ):
        return "запрет"
    if re.search(r"\b(?:вправе|право)\w*\b", normalized):
        return "право"
    if re.search(r"\b(?:обязан|должен|необходимо)\w*\b", normalized):
        return "обязанность"
    return "положение"


def _axis_attribute(fact: SourceFact, correct_value: str) -> str:
    attribute = fact.attribute.strip()
    if _norm(attribute) not in _AUTO_NARRATIVE_ATTRIBUTES:
        return attribute
    return _claim_attribute(correct_value)


def _axis_kind(attribute: str, value: str) -> AssessmentAxisKind:
    value = _norm(value)
    if re.search(r"\d|%", value) or has_temporal_unit(value):
        return "numeric_value"
    if re.search(
        r"\b(?:правил|требован|запрещ|нельзя|долж|разреш|обязат)",
        _norm(attribute + " " + value),
    ):
        return "rule_value"
    return "attribute"


def _source_owned_faq_pair(value: str) -> tuple[str, str] | None:
    """Keep a leading unquoted FAQ question with its complete exact answer.

    Do not interpret quoted questions, multiple question/answer pairs or an
    unanswered question as an assertion. Answer conditions stay verbatim;
    the source question supplies context, never the answer key.
    """
    match = re.fullmatch(
        r'(?P<prompt>[^.!?«»“”"\n]{5,200}\?)\s+(?P<answer>[^?]+)',
        value.strip(), flags=re.DOTALL,
    )
    if match is None:
        return None
    answer = match.group("answer").strip()
    if len(answer) < 12 or not re.search(r"[^\W\d_]", answer):
        return None
    return match.group("prompt").strip(), answer


def _source_owned_correct_value(fact: SourceFact) -> str:
    """Select one exact actionable sentence from a narrative paragraph.

    Facts retain exact source wording, but a multi-sentence spreadsheet cell or
    narrative paragraph must not become an obvious long answer key. The axis is
    one atomic source claim; the lesson still retains the complete fact.
    """
    faq_pair = _source_owned_faq_pair(fact.value)
    if faq_pair is not None:
        return faq_pair[1]
    structured_clauses = _structured_list_clauses(fact.value)
    sentences = structured_clauses or _source_sentences(fact.value)
    if len(sentences) <= 1:
        return _concise_source_span(fact.value.strip())

    has_scope_context = bool(re.search(
        r"\b(?:применяется|применяются)\b|\b(?:он|она|оно)\s+(?:нужен|нужна|нужно)\b",
        _norm(fact.value),
    ))

    def score(sentence: str, index: int) -> tuple[int, int, int, int, int]:
        normalized = _norm(sentence)
        points = 0
        if has_scope_context and _norm(fact.attribute) in _AUTO_NARRATIVE_ATTRIBUTES and re.search(
            r"\b(?:нельзя|запрещен\w*|обязан\w*|не\s+может|не\s+могут|"
            r"must|shall|must\s+not)\b", normalized,
        ):
            # An operational paragraph may lead with broad OR-scope/context.
            # Prefer its explicit required/forbidden action for one atomic
            # assessment; the full scope stays intact in the lesson evidence.
            points += 12
        if re.search(r"\b(?:если|когда|при|unless|when|if)\b", normalized):
            points += 8
        points += 3 * len(re.findall(
            r"\b(?:долж\w*|нельзя|запрещ\w*|отказ\w*|предлаг\w*|"
            r"переда\w*|использ\w*|требу\w*|необходим\w*|следу\w*|"
            r"must|shall|refus\w*|offer\w*)\b",
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
        # Narrative background must not outrank an explicit stop/action later
        # in the same evidence unit. Table attributes retain their value order.
        action_priority = (
            operational_claim_priority(sentence)
            if _norm(fact.attribute) in _AUTO_NARRATIVE_ATTRIBUTES
            and not is_tabular_locator(fact.source_locator) else (0, 0)
        )
        return *action_priority, points, -index, -len(sentence)

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


def _direct_binary_prohibition(correct_value: str) -> tuple[str, str] | None:
    """Preserve the entire action/condition when negating two explicit grammars.

    Do not distribute a joint prohibition across its individual actions or
    infer exceptions. Complex qualifications remain model-reviewed MCQ axes.
    """
    value = correct_value.strip()
    if re.search(
        r"[;!?]|\b(?:кроме|исключени\w*|но|однако|только|лишь|не)\b",
        re.sub(r"\bне\s+может\s+одновременно\b", "", value, count=1,
               flags=re.IGNORECASE), flags=re.IGNORECASE,
    ):
        return None
    leading = re.fullmatch(
        r"Нельзя\s+(?P<action>[А-Яа-яЁё]+(?:ть|ти|чь)\s+[^.!?]+)\.?",
        value, flags=re.IGNORECASE,
    )
    if leading is not None:
        action = leading.group("action").strip()
        return f"Допустимо ли {action}?", f"Можно {action}."
    joint = re.fullmatch(
        r"(?P<actor>[А-Яа-яЁё][А-Яа-яЁё -]{1,60})\s+не\s+может\s+одновременно\s+"
        r"(?P<action>[А-Яа-яЁё]+(?:ть|ти|чь)\s+[^.!?]+\s+и\s+"
        r"[А-Яа-яЁё]+(?:ть|ти|чь)\s+[^.!?]+)\.?",
        value, flags=re.IGNORECASE,
    )
    if joint is not None:
        actor = joint.group("actor").strip()
        action = joint.group("action").strip()
        return (
            f"Может ли {actor[:1].lower()}{actor[1:]} одновременно {action}?",
            f"{actor} может одновременно {action}.",
        )
    return None


def _required_prompt(correct_value: str) -> str:
    direct = _direct_binary_prohibition(correct_value)
    if direct is not None:
        return direct[0]
    postfix_prohibition = _POSTFIX_ACTION_PROHIBITION.fullmatch(correct_value.strip())
    if postfix_prohibition is not None:
        action = postfix_prohibition.group("action").strip()
        return f"Допустимо ли {action[:1].lower()}{action[1:]}?"
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
    direct = _direct_binary_prohibition(correct_value)
    if direct is not None:
        return direct[1]
    postfix_prohibition = _POSTFIX_ACTION_PROHIBITION.fullmatch(correct_value.strip())
    if postfix_prohibition is not None:
        return f"{postfix_prohibition.group('action').strip()} разрешено."
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
        if _norm(fact.attribute) in _AUTO_NARRATIVE_ATTRIBUTES and re.fullmatch(
            r'[^.!?«»“”"]+\?', fact.value.strip(),
        ):
            # A bare FAQ question carries no answer. Explicit source attributes
            # such as "вопрос для знакомства" may legitimately quote a question.
            continue
        single_action_axes = _single_numbered_action_axes(fact)
        structured_axes = (
            [] if single_action_axes else _structured_operational_axes(fact)
        )
        if not single_action_axes and not structured_axes and _unsupported_operational_list(fact):
            # Multiple source actions without a bounded shared context cannot
            # safely become either separate prompts or one apparently covered
            # parent axis. The assessment audit will retain the fact as
            # unassessed evidence and require review.
            continue
        regulatory_axes = (
            [] if single_action_axes or structured_axes
            else _regulatory_table_range_axes(fact)
        )
        conditional_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _conditional_rule_axes(fact)
        )
        deadline_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _deadline_axes(fact)
        )
        compound_table_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _compound_table_operational_axes(fact)
        )
        projected_axes = conditional_axes + deadline_axes + [
            (value, prompt) for value, prompt in compound_table_axes
            if not _has_same_conditional_target(value, conditional_axes)
        ]
        if projected_axes:
            fallback = _source_owned_correct_value(fact)
            if (
                fallback
                and len(fallback.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
                and not _is_dependent_source_fragment(fallback)
                and not _has_same_conditional_target(fallback, conditional_axes)
                and all(_norm(fallback) != _norm(value) for value, _prompt in projected_axes)
            ):
                projected_axes.append((fallback, ""))
        if (
            not single_action_axes
            and not structured_axes
            and not regulatory_axes
            and not projected_axes
            and is_tabular_locator(fact.source_locator)
            and len(fact.value.strip()) > MAX_ASSESSMENT_ANSWER_CHARS
        ):
            # A full-cell key is guaranteed to fail the local quality contract.
            # Without a complete independently promptable source span, preserve
            # the parent fact as explicit unassessable evidence before authoring.
            continue
        source_axes = (
            single_action_axes
            or structured_axes
            or regulatory_axes
            or projected_axes
            or [(_source_owned_correct_value(fact), "")]
        )
        for source_value, structured_prompt in source_axes:
            if (
                not source_value
                or len(source_value.strip()) > MAX_ASSESSMENT_ANSWER_CHARS
                or _is_dependent_source_fragment(source_value)
            ):
                continue
            if structured_prompt:
                correct_value, required_prompt = source_value, structured_prompt
            else:
                correct_value, required_prompt = _contextualized_list_axis(
                    fact, source_value
                )
            axis_attribute = _axis_attribute(fact, correct_value)
            faq_pair = _source_owned_faq_pair(fact.value)
            required_prompt = (faq_pair[0] if faq_pair else
                               required_prompt or _required_prompt(correct_value))
            if not required_prompt and re.search(
                r"^(?:необходимо\b|.+?\bследует\s+(?:обесточить|отключить)\b)",
                correct_value.strip(),
                flags=re.IGNORECASE,
            ):
                required_prompt = (
                    f"Для «{fact.subject.strip()}» в характеристике "
                    f"«{fact.attribute.strip()}»: какое действие предусмотрено?"
                )
            if not required_prompt and is_tabular_locator(fact.source_locator):
                # Keep the source-owned table subject and attribute in the stem;
                # a provider may propose alternatives, not recast a collection as
                # one product inferred from an attribute value or catalog row.
                required_prompt = (
                    f"Что указано в характеристике «{fact.attribute.strip()}» "
                    f"для «{fact.subject.strip()}»?"
                )
            normalized_value = _norm(correct_value)
            identity = (_norm(fact.subject), _norm(axis_attribute), normalized_value)
            if identity in seen:
                continue
            seen.add(identity)
            digest = hashlib.sha256(
                "|".join((
                    "assessment-axis",
                    lesson.lesson_id,
                    block_id,
                    fact.fact_id,
                    _norm(axis_attribute),
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
                attribute=axis_attribute,
                required_prompt=required_prompt,
                correct_value=correct_value,
                normalized_correct_value=normalized_value,
                eligible_distractor_fact_ids=peers,
                axis_kind=_axis_kind(axis_attribute, correct_value),
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
    """Give learners the selected claim without exposing authoring metadata."""
    sample = f"{axis.attribute} {axis.correct_value}".casefold()
    # A legal entity's proper name is not the language of the instruction.
    # Preserve the quoted name in the answer; exclude it only from detection.
    sample = re.sub(r'\b(?:тоо|ао|ооо|ип|жшс|llp|llc)\s*[«"“][^»"”]*[»"”]', "", sample)
    neutral_claim = (
        _norm(axis.attribute) == "положение"
        or axis.correct_value.casefold().startswith(("если ", "if ", "егер "))
    )
    # Numbers inside a prohibition are context, not a numeric teaching target.
    is_action = axis.axis_kind == "rule_value" or _norm(axis.attribute) == "запрет"
    if any(character in sample for character in "әғқңөұүһі"):
        if is_action:
            return f"Әрекет ету тәртібі: «{axis.correct_value}»."
        if neutral_claim:
            return f"Есте сақтаңыз: «{axis.correct_value}»."
        return f"«{axis.attribute}» мәні: «{axis.correct_value}»."
    if re.search(r"[а-яё]", sample):
        if is_action:
            return f"Как действовать: «{axis.correct_value}»."
        if neutral_claim:
            return f"Запомните: «{axis.correct_value}»."
        return f"Значение «{axis.attribute}»: «{axis.correct_value}»."
    if is_action:
        return f"How to act: “{axis.correct_value}”."
    if neutral_claim:
        return f"Remember: “{axis.correct_value}”."
    return f"Value “{axis.attribute}”: “{axis.correct_value}”."
