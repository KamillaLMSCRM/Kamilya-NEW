"""Deterministic assessment truth boundary.

The source and server own the tested fact, correct answer, evidence and stable
identity. A language model may only phrase the question and propose wrong
answers. This keeps provider/model changes from moving the answer key.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import replace

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
from .operational_approval import is_unresolved_procedure_reference, project_operational_approvals
from .operational_control import project_control_responsibility
from .operational_coverage import audit_operational_coverage
from .operational_inspection import project_operational_inspections
from .operational_signing import project_signing_responsibilities
from .operational_steps import (
    ExactSentenceSpan,
    OperationalProjection,
    OperationalStep,
    project_rejection_followups,
)
from .quality import MAX_ASSESSMENT_ANSWER_CHARS
from .reference_selection import ReferenceSelection, project_reference_selections
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
        r"\bдолж(?:ен|на|но|ны)\s+(?P<answer>детально\s+ознакомиться\s+с\s+.+)$",
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
    re.compile(r"\bне\s+долж(?:ен|на|но|ны)\s+превышать\s+(?P<answer>.+)$", re.IGNORECASE),
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
    cleaned = re.sub(r"^\s*\d+(?:\.\d+)*[.)]\s+", "", sentence).strip()
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
        r"(?:[-–—](?:[ \t]+|(?=[^\W\d_]))(?:\d{1,2}[.)][ \t]+)?)|"
        r"(?:[*•▪‣][ \t]+(?:\d{1,2}[.)][ \t]+)?)|"
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
    response = re.fullmatch(
        r"в случае обнаружения пожара сообщить о нем в подразделение противопожарной службы "
        r"и принять возможные меры к спасению людей, имущества и ликвидации пожара[.]?",
        stripped, flags=re.IGNORECASE,
    )
    if response is not None:
        return "оповещение и меры реагирования", "в случае обнаружения пожара", False
    readiness = re.fullmatch(
        r"содержать в исправном состоянии (?P<object>[^,.!?;:]+),\s*"
        r"не допускать их использования не по назначению[.]?", stripped, re.IGNORECASE,
    )
    if readiness is not None:
        # Name only the object. Quoting both source duties here would reveal
        # the whole answer before the learner examines any choices.
        return readiness['object'], "", False
    qualified_action = re.fullmatch(
        r"(?P<qualifier>незамедлительно|немедленно|своевременно|визуально|четко|систематически|"
        r"при\s+необходимости|одновременно\s+с\s+[^.!?;:]{3,100}?)\s+"
        r"(?P<action>(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+.+)",
        stripped, flags=re.IGNORECASE,
    )
    if qualified_action is not None:
        parsed = _operational_clause_parts(qualified_action.group("action"))
        if parsed is not None:
            target, qualifier, prohibited = parsed
            context = "; ".join(item for item in (qualified_action.group("qualifier"), qualifier) if item)
            return target, context, prohibited
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
        r"^(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s*,?\s+(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if leading is not None:
        target, qualifier = _split_action_qualifier(leading.group("target"))
        return (target, qualifier, prohibited) if target else None
    nominal = re.fullmatch(r"(?:обеспечение|поддержание|соблюдение)\s+(?P<target>.+)",
                           stripped, flags=re.IGNORECASE)
    if nominal is not None:
        return nominal.group("target"), "", prohibited
    admission = re.fullmatch(
        r"(?P<actor>[^.!?;:]{5,120}?)\s+допускаются\s+к\s+работе\s+только\s+после\s+.+",
        stripped, flags=re.IGNORECASE,
    )
    if admission is not None:
        return admission.group("actor"), "", False
    passive_prohibition = re.fullmatch(r"(?P<target>.+?)\s+не\s+допускается", stripped, flags=re.IGNORECASE)
    if passive_prohibition is not None:
        return passive_prohibition.group("target"), "", True
    actor_action = re.match(
        r"^.+?\b(?:долж(?:ен|на|но|ны)|обязан\w*|запрещ\w*|не\s+допуска\w*)\s+(?:не\s+)?"
        r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+(?P<target>.+)$",
        stripped,
        flags=re.IGNORECASE,
    )
    if actor_action is None:
        return None
    target, qualifier = _split_action_qualifier(actor_action.group("target"))
    return (target, qualifier, prohibited) if target else None


def _affirmative_prohibition_modal(preamble: str) -> re.Match[str] | None:
    modal = re.search(r"\b(?:запрещается|запрещено|нельзя|не\s+допускается)\s*$", preamble,
                      flags=re.IGNORECASE)
    if modal is None:
        return None
    # Only a recognized paired actor-participle qualifier closes negation scope.
    # An arbitrary comma (e.g. не во всех случаях, предусмотренных правилами,)
    # cannot grant an affirmative predicate. Unsupported negation fails closed.
    governor = re.sub(
        r",\s*не\s+(?:прошедш\w*|выполнивш\w*|имеющ\w*|получивш\w*|"
        r"ознакомивш\w*|завершивш\w*)\b[^,]*,",
        ",", preamble[:modal.start()], flags=re.IGNORECASE,
    )
    return None if re.search(r"\bне\b", governor, flags=re.IGNORECASE) else modal


def _neutral_compound_object(value: str, *, include_secondary: bool = False) -> str:
    """Project a neutral stem object without claiming general Russian parsing.

    Only recognized coordinated action predicates are removed from the topic;
    noun conjunctions and unknown verbs retain the existing object. The complete
    source clause remains the immutable answer and both reviews remain binding.
    """
    verb = r"(?:выполнять|осуществлять|обучать|обеспечить|принять|выполнить|оказать)"
    shared = re.fullmatch(r"(?:и|а\s+также)\s+" + verb + r"\s+(?P<object>.+)",
                          value, flags=re.IGNORECASE)
    if shared is not None:
        value = shared['object']
    separator = r"(?:,\s*(?:а\s+также\s+)?|\s+и\s+)" + verb + r"\b"
    if include_secondary:
        return " / ".join(part.strip() for part in re.split(separator, value, flags=re.IGNORECASE) if part.strip())
    boundary = re.search(separator, value, flags=re.IGNORECASE)
    return value[:boundary.start()].strip() if boundary and value[:boundary.start()].strip() else value


def _structured_operational_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind safe source list actions to distinct, context-preserving prompts."""
    structured = _explicit_structured_list(fact.value)
    if structured is None:
        return []
    preamble, clauses = structured
    if not preamble or len(preamble) > 240:
        return []
    if (re.search(r"\b(?:запрещается|запрещено|нельзя|не\s+допускается)\s*$", preamble, flags=re.IGNORECASE)
            and _affirmative_prohibition_modal(preamble) is None):
        return []
    normative_parent = re.search(
        r"\b(?:долж(?:ен|на|но|ны)|обязан\w*|следует|запрещается|запрещено|нельзя|не\s+допускается)\s*$",
        preamble, flags=re.IGNORECASE,
    )
    operational: list[tuple[int, str, tuple[str, str, bool]]] = []
    for position, clause in [(position, statement) for position, child in clauses
                            for statement in (_structured_child_statements(child)
                                              if normative_parent else [child])]:
        parts = _operational_clause_parts(clause)
        if parts is not None:
            operational.append((position, clause, parts))
    if len(operational) < 2:
        return []
    preamble_prohibited = _affirmative_prohibition_modal(preamble) is not None
    topic_keys: dict[tuple[str, str, bool], set[str]] = defaultdict(set)
    for _position, clause, (target, qualifier, prohibited) in operational:
        topic_keys[(_norm(_neutral_compound_object(target)), _norm(qualifier), prohibited)].add(_norm(clause))
    axes: list[tuple[str, str]] = []
    projected_prompts: dict[str, tuple[str, bool]] = {}
    for _position, clause, (target, qualifier, _clause_prohibited) in operational:
        original_target = target
        target = _neutral_compound_object(original_target)
        disambiguated = (
            target != original_target
            and len(topic_keys[(_norm(target), _norm(qualifier), _clause_prohibited)]) > 1
        )
        if disambiguated:
            target = _neutral_compound_object(original_target, include_secondary=True)
        condition = f" с учетом условия «{qualifier}»" if qualifier else ""
        leading_prohibition = re.match(
            r"^(?:нельзя|запрещено|запрещается|не\s+допускается|must\s+not|forbidden)\b",
            clause.strip(), flags=re.IGNORECASE,
        )
        if preamble_prohibited or leading_prohibition:
            prompt = (
                f"Какое действие в отношении «{target}» запрещено{condition} "
                f"требованием «{preamble}»?"
            )
        else:
            prompt = (
                f"Какое полное правило в отношении «{target}» предусмотрено{condition} "
                f"требованием «{preamble}»?"
            )
        normalized_prompt = _norm(prompt)
        prior_projection = projected_prompts.get(normalized_prompt)
        changed_topic = target != original_target
        if prior_projection and prior_projection[0] != _norm(clause) and (changed_topic or prior_projection[1]):
            raise ValueError("assessment_compound_topic_collision")
        projected_prompts[normalized_prompt] = (_norm(clause), changed_topic)
        axes.append((clause, prompt))
    return axes


def _structured_child_statements(clause: str) -> list[str]:
    """Split only an overlong source child at preserved sentence boundaries."""
    if len(clause) <= MAX_ASSESSMENT_ANSWER_CHARS:
        return [clause]
    sentences = _source_sentences(clause)
    if len(sentences) < 2:
        return [clause]
    original_words = _ANCHOR_TOKEN.findall(_norm(clause))
    split_words = _ANCHOR_TOKEN.findall(_norm(" ".join(sentences)))
    return sentences if original_words == split_words else [clause]


def _focused_list_duty(fact: SourceFact, clause: str) -> tuple[str, str] | None:
    """Project a whole closed duty grammar into actor, action and exact focus.

    This is not a token-overlap shortcut. Each full match accounts for the
    entire child; unknown verbs, conditions and additional siblings stay on the
    ordinary whole-clause path. Both joint monitoring/remediation duties and
    readiness qualifiers remain mandatory in the question.
    """
    structured = _explicit_structured_list(fact.value)
    if structured is None:
        return None
    parent = re.fullmatch(
        r"(?P<actor>[^:;!?]{5,220}?)\s+(?:обязан(?:а|о|ы)?|долж(?:ен|на|но|ны))",
        _without_source_marker(structured[0]), flags=re.IGNORECASE,
    )
    value = clause.strip().rstrip(".;")
    passive = re.fullmatch(r"(?P<scope>[^.!?;:]+?)\s+(?P<key>не\s+допускается)", value,
                           flags=re.IGNORECASE)
    if passive is not None and _affirmative_prohibition_modal(structured[0]) is not None:
        return passive.group("key"), f"Допустима ли «{passive.group('scope')}»?"
    if parent is None or re.search(r"\b(?:не|если|при|когда)\b", parent.group("actor"), re.IGNORECASE):
        return None
    actor = parent.group("actor").rstrip(" ,")
    monitoring = re.fullmatch(
        r"следить\s+за\s+(?P<state>исправностью\s+работы)\s+(?P<key>[^.!?;:]+?)\s+"
        r"и\s+(?P<remedy>принимать\s+меры\s+к\s+устранению\s+[^.!?;:]+)",
        value, flags=re.IGNORECASE,
    )
    if monitoring is not None:
        return monitoring.group("key"), (
            f"За «{monitoring.group('state')}» каких систем и установок «{actor}» должны следить "
            f"и «{monitoring.group('remedy')}»?"
        )
    readiness = re.fullmatch(
        r"обеспечить\s+(?P<state>исправное\s+содержание\s+и\s+постоянную\s+готовность\s+к\s+действию)"
        r"\s+(?P<key>[^.!?;:]+)", value, flags=re.IGNORECASE,
    )
    if readiness is not None:
        return readiness.group("key"), (
            f"Для каких средств «{actor}» должны обеспечить «{readiness.group('state')}»?"
        )
    return None


def _long_list_responsibility_axis(fact: SourceFact, clause: str) -> tuple[str, str] | None:
    """Ask the exact responsible actor when an indivisible duty is a long key."""
    structured = _explicit_structured_list(fact.value)
    if structured is None or len(clause) <= MAX_ASSESSMENT_ANSWER_CHARS:
        return None
    preamble, _clauses = structured
    match = re.fullmatch(
        r"(?P<actor>[^:;!?]{5,220}?)\s+(?P<modal>обязан(?:а|о|ы)?|долж(?:ен|на|но|ны))",
        _without_source_marker(preamble), flags=re.IGNORECASE,
    )
    if match is None or re.search(r"\b(?:не|если|при|когда)\b", match.group("actor"), re.IGNORECASE):
        return None
    prompt = f"Кто согласно исходному правилу должен выполнить следующее: «{clause}»?"
    if len(prompt) > 900:
        return None
    return match.group("actor"), prompt


def _simple_list_prohibition_axis(fact: SourceFact, clause: str) -> tuple[str, str] | None:
    """Ask about the WHOLE source list proposition, including its qualifiers.

    Both action and prohibition are source-owned. Joint actions and conditions
    are never distributed, inverted or omitted: the complete clause stays in
    the mandatory question. Both alternatives still need independent reviews.
    """
    structured = _explicit_structured_list(fact.value)
    value = clause.strip().rstrip(".")
    if (structured is None
            or not re.fullmatch(r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+[^.!?;:]+", value)):
        return None
    preamble, clauses = structured
    modal = _affirmative_prohibition_modal(preamble)
    if modal is None or not any(_norm(item.rstrip('.')) == _norm(value)
                               for _position, child in clauses for item in _structured_child_statements(child)):
        return None
    actor = _without_source_marker(preamble[:modal.start()]).strip()
    if not actor:
        return None
    return (modal.group().strip(),
            f"Допустимо ли {actor[:1].lower()}{actor[1:]} {value[:1].lower()}{value[1:]}?")


def _simple_list_obligation_axis(fact: SourceFact, clause: str) -> tuple[str, str] | None:
    """Keep the WHOLE scoped action in a closed obligation decision.

    A source list obligation does not have several distinct correct ways of
    being optional. Preserve actor, joint actions and exceptions verbatim;
    only the source's modal predicate is contrasted, never an individual step.
    Unknown/negated modal governors remain on the ordinary evidence path.
    """
    structured = _explicit_structured_list(fact.value)
    value = clause.strip().rstrip(".")
    nominal_state = re.fullmatch(
        r"обеспечение\s+исправное\s+состояние\s+[^.!?;:]+", value, flags=re.IGNORECASE,
    )
    if (structured is None
            or len(value) > MAX_ASSESSMENT_ANSWER_CHARS
            or (nominal_state is None and not re.fullmatch(
                r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+[^.!?;:]+", value))):
        return None
    parent = re.fullmatch(
        r"(?P<actor>[^:;!?]{5,220}?)\s+(?P<modal>обязан(?:а|о|ы)?|долж(?:ен|на|но|ны))",
        _without_source_marker(structured[0]), flags=re.IGNORECASE,
    )
    if (parent is None or re.search(r"\b(?:не|если|при|когда)\b", parent.group("actor"), flags=re.IGNORECASE)
            or re.match(r"^(?:при|если|когда|после|до|перед|во\s+время|по\s+окончании)\b",
                        parent.group("actor"), flags=re.IGNORECASE)):
        return None
    if not any(_norm(item.rstrip('.')) == _norm(value)
               for _position, child in structured[1] for item in _structured_child_statements(child)):
        return None
    actor = parent.group("actor").rstrip(" ,")
    # Nominal wording in an explicit source list still states the exact duty.
    # Normalize only its closed grammatical governor for the question, never
    # change the required state, object, joint actions or source evidence.
    action = (
        re.sub(r"^обеспечение\s+", "обеспечить ", value, count=1, flags=re.IGNORECASE)
        if nominal_state else value
    )
    return (parent.group("modal"), f"Обязательно ли для «{actor}» {action[:1].lower()}{action[1:]}?")


_SINGLE_NUMBERED_ACTION = re.compile(
    r"^\s*(?:\d+(?:\.\d+)+\.?\s*)?"
    r"(?P<preamble>[^:]{12,200}?\b(?:долж(?:ен|на|но|ны)|обязан\w*|следует))\s*:\s*"
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
    r"(?:\b(?:г|ул|д|стр|рис|им|др)\.|"
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
    for boundary in re.finditer(
        r"[.!?]+(?=\s+(?:[*]?[А-ЯЁA-Z0-9]))|"
        r"(?=\n[ \t]*[-—–][ \t]*(?i:[А-Яа-яЁё][^\n.!?;:]{1,160}\bпроходят\s+"
        r"(?:противопожарный\s+)?инструктаж\b))", value,
    ):
        prefix = value[start:boundary.end()].rstrip()
        if re.fullmatch(r"\s*\d+(?:\.\d+)*\.", prefix):
            # A section marker is not a sentence, much less a numeric answer.
            continue
        if _SOURCE_ABBREVIATION_TAIL.search(prefix):
            continue
        if (re.search(r"\bп\.\s*\d+(?:\.\d+)*\.$", prefix, flags=re.IGNORECASE)
                and re.match(r"\s+(?:Настоящ\w*|Данн\w*|Указанн\w*|Правил\w*|"
                             r"Положени\w*|Стандарт\w*|Регламент\w*|Инструкци\w*|Договор\w*)\b",
                             value[boundary.end():])):
            continue
        if prefix:
            result.append(prefix.strip())
        start = boundary.end()
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


def derive_reference_selections(fact: SourceFact) -> tuple[ReferenceSelection, ...]:
    """Expose exact reference-selection scope independently of execution coverage."""
    return project_reference_selections(fact, _source_sentences(fact.value))


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
_CONDITIONAL_NEGATIVE_RIGHT = re.compile(
    r"^(?P<actor>[^,.!?]{2,120}?)\s+"
    r"(?P<answer>не\s+вправе\s+.{5,180}?),\s*"
    r"(?P<condition>(?:если|в\s+случае\s+если|когда)\b[^.!?]{5,200})[.!?]?$",
    flags=re.IGNORECASE,
)
_SHARED_RESPONSIBILITY_RULE = re.compile(
    r"(?:^|[,;]\s*)(?P<actor>[^,;.!?]{2,120}?)\s+несут\s+"
    r"(?P<responsibility>[^,;.!?]{5,80}\bответственность)\s+"
    r"(?P<scope>за\s+.+?),\s+а\s+также\s+"
    r"(?P<modal>обязан\w*|долж(?:ен|на|но|ны))\s+(?P<actions>[^.!?]+)[.!?]?$",
    flags=re.IGNORECASE,
)
_COORDINATED_INFINITIVE = re.compile(
    r"\s+и\s+(?=(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\b)",
    flags=re.IGNORECASE,
)
_EXPLICIT_CONSEQUENCE_RULE = re.compile(
    r"^(?P<scope>За\s+.+?)\s+предусмотрен[аоы]?\s+"
    r"(?P<answer>[^,.;!?]{5,180}?)(?=\s+(?:в\s+соответствии|согласно)\b)"
    r"[^!?]*[.!?]?$",
    flags=re.IGNORECASE,
)
_VIOLATION_CONSEQUENCE_RULE = re.compile(
    r"^(?P<scope>Нарушение\b[^.!?]{5,300}?)\s+влечет\s+за\s+собой\s+"
    r"(?P<answer>[^.!?]{5,240}\bответственность(?:,\s*[^.!?]+)?)[.!?]?$",
    flags=re.IGNORECASE,
)
_INSTRUCTION_SCHEDULE_RULE = re.compile(
    r"^(?P<actor>[^.!?;:]{3,160}?)\s+"
    r"(?P<answer>проходят\s+(?:противопожарный\s+)?инструктаж\s+[^.!?;:]{5,200})[.;]?$",
    flags=re.IGNORECASE,
)
_PASSIVE_RESPONSIBILITY_RULE = re.compile(
    r"^(?P<duty>[^.!?]{5,220}?)\s+возлагается\s+на\s+"
    r"(?P<actor>[^.!?]{3,180})[.!?]?$",
    flags=re.IGNORECASE,
)
_APPOINTED_FUNCTION_RULE = re.compile(
    r"^(?P<actor>[^,.!?]{3,160}?)\s+"
    r"(?P<appointment>назначает\s+(?P<object>[^,.!?]{2,80})),\s+"
    r"которые\s+(?P<qualification>.+?)\s+"
    r"(?P<functions>выполняют\s+.+?\s+либо\s+обеспечивают\s+[^.!?]+)[.!?]?$",
    flags=re.IGNORECASE,
)
_SCOPED_MODAL_RULE = re.compile(
    r"^(?P<subject>[^.!?]{2,180}?)\s+"
    r"(?P<answer>(?:долж(?:ен|на|но|ны)|обязан\w*)\s+.+?)\s+"
    r"(?P<scope>в\s+соответствии\s+с\s+[^.!?]+)[.!?]?$",
    flags=re.IGNORECASE,
)
_TIME_QUALIFIED_SCOPE = re.compile(
    r"\b(?:независимо\s+от|по\s+окончании|перед\s+закрытием|"
    r"выходн\w*|праздничн\w*|уходящ\w*\s+последн\w*)\b",
    flags=re.IGNORECASE,
)
_FINITE_ACTION_VERB = r"[А-Яа-яЁё]+(?:ет|ит|ют|ут|ат|ят)(?:ся|сь)?"
_ACTOR_FINITE_ACTION = re.compile(
    rf"^(?P<actor>[^,.!?]{{2,120}}?)\s+"
    rf"(?P<answer>(?P<verb>{_FINITE_ACTION_VERB})\s+(?P<target>[^.!?]+))$",
    flags=re.IGNORECASE,
)
_FINITE_ACTION = re.compile(
    rf"^(?:об\s+этом\s+)?(?P<answer>(?P<verb>{_FINITE_ACTION_VERB})\s+(?P<target>[^.!?]+))$",
    flags=re.IGNORECASE,
)
_FLATTENED_LOCATION_BRANCH = re.compile(
    r"(?:^|(?<=[.!?:]))\s*-\s*"
    r"(?P<condition>при\s+[^.!?]+?)\s+[-–—]\s+"
    r"(?P<answer>[^.!?]+[.!?])",
    flags=re.IGNORECASE,
)
_PARENTHETICAL_MODAL_RULE = re.compile(
    r"^(?P<actor>[^,.!?]{3,160}?)\s+"
    r"(?P<timing>во\s+время\s+[^()!?]{5,220}?)\s+"
    r"\((?P<condition>если\s+[^()!?]{5,220})\)\s+"
    r"(?P<answer>обязан\w*\s+[^.!?]{8,220})[.!?]?$",
    flags=re.IGNORECASE,
)
_DEPENDENT_SIGNATURE_RULE = re.compile(
    r"^(?P<condition>В\s+случае\s+своего\s+согласия)\s+"
    r"(?P<answer>(?:не\s+)?[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+[^.!?]+)[.!?]?$",
    flags=re.IGNORECASE,
)
_DUAL_LOCATION_RESPONSE_RULE = re.compile(
    r"^После\s+получения\s+(?:такой|этой)\s+информации,\s*"
    r"(?P<actor>[^,.!?]{3,160}?)\s+обязан\w*\s+"
    r"при\s+(?P<local_condition>.+?)\s+"
    r"(?P<local_action>выехать\s+незамедлительно),\s*"
    r"а\s+при\s+(?P<remote_condition>.+?)\s*[-–—]\s*"
    r"(?P<remote_deadline>в\s+течени[еи]\s+\d+(?:-[^\s,.;!?]+)?\s+"
    r"[^\s,.;!?]+\s+с\s+момента\s+[^,.;!?]+),\s*"
    r"(?P<purpose>для\s+[^.!?]+)[.!?]?$",
    flags=re.IGNORECASE,
)
_NORMATIVE_CONSEQUENCE = re.compile(
    r"\b(?:долж(?:ен|на|но|ны)|обязан\w*|необходим\w*|следует|нужно|требуется|"
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
    ).strip().lstrip("-—–, ")


def _focused_step_prompt(clause: str) -> str:
    """Name the source action type, never imply it is the entire workflow."""
    conditional = _EXPLICIT_THEN_CONDITION.fullmatch(clause)
    if conditional is None:
        return ""
    if re.fullmatch(
        r"решение\b.+\bдолжно\s+быть\s+предварительно\s+согласовано\s+по\s+телефону[.!?]?",
        conditional.group("action"), flags=re.IGNORECASE,
    ):
        return (
            "Как необходимо предварительно согласовать решение при условии "
            f"«{conditional.group('condition')}»?"
        )
    notification = re.fullmatch(
        r"(?P<actor>.+?)\s+(?P<modal>обязан[аы]?|должен|должна|должны)\s+"
        r"(?:сразу|незамедлительно|немедленно)\s+"
        r"(?P<verb>поставить\s+в\s+известность|уведомить|сообщить)\s+[^.!?]+[.!?]?",
        conditional.group("action"), flags=re.IGNORECASE,
    )
    if notification is not None:
        return (
            f"Кого и когда {notification.group('actor')} {notification.group('modal')} "
            f"{notification.group('verb')} при условии «{conditional.group('condition')}»?"
        )
    negative_record = re.fullmatch(
        r"(?P<record>(?:отметка|запись)\b[^.!?]{0,160}?)\s+"
        r"не\s+(?:проставляется|делается|вносится)[.!?]?",
        conditional.group("action"),
        flags=re.IGNORECASE,
    )
    if negative_record is not None:
        return (
            f"Какое правило действует для «{negative_record.group('record').strip()}» "
            f"при условии «{conditional.group('condition')}»?"
        )
    action = re.fullmatch(
        r"(?P<location>в\s+.+?)\s+(?P<verb>проставляется|делается|вносится)\s+"
        r"(?P<record>отметка|запись),?\s+(?:что\s+)?[^.!?]+[.!?]?",
        conditional.group("action"), flags=re.IGNORECASE,
    )
    if action is None:
        return ""
    record = "отметку" if action.group("record").casefold() == "отметка" else "запись"
    verb = {"проставляется": "проставить", "делается": "сделать", "вносится": "внести"}[
        action.group("verb").casefold()
    ]
    return (
        f"Какую {record} следует {verb} {action.group('location')} "
        f"при условии «{conditional.group('condition')}»?"
    )


_STEP_ACTION = re.compile(
    r"\b(?:простав\w*|внос\w*|уведом\w*|сообщ\w*|подпис\w*|"
    r"поставить\s+в\s+известность|(?:сдела\w*|дела\w*)\s+запис\w*)\b",
    flags=re.IGNORECASE,
)
_NUMBERED_BRANCH = re.compile(r"(?<!\S)\d+(?:\.\d+)*[.)]\s+")
_BRANCH_CONDITION = re.compile(
    r"(?:при|если|когда)\b[^.!?]+?\s+[-—–]\s+", flags=re.IGNORECASE,
)
_UNIVERSAL_SCOPE = re.compile(
    r"\b(?:во\s+всех\s+случаях|независимо\s+от|при\s+любых)\b", flags=re.IGNORECASE,
)
_TEMPORAL_CONDITION = re.compile(
    r"\b(?:после|до|выходн\w*|праздничн\w*)\b", flags=re.IGNORECASE,
)


def _deadline_source_rule(fact: SourceFact, sentences: list[str], index: int,
                          match: re.Match[str]) -> tuple[tuple[str, ...], str] | None:
    """Retain explicit adjacent/numbered scope, or quarantine an ambiguous target.

    Do not infer a relationship from a large thematic paragraph. All added text
    is an exact source span; a sibling numbered item is a hard scope boundary.
    """
    sentence = sentences[index]
    positions: list[int] = []
    cursor = 0
    for row in sentences[:index + 1]:
        start = fact.value.index(row, cursor)
        positions.append(start)
        cursor = start + len(row)
    sentence_start = positions[index]
    branch_start = 0
    branch_content_start = 0
    contexts: list[str] = []
    if is_tabular_locator(fact.source_locator):
        prefix = fact.value[:sentence_start + match.start()]
        branches = list(_NUMBERED_BRANCH.finditer(prefix))
        if branches:
            branch = branches[-1]
            branch_start = branch.start()
            header = _BRANCH_CONDITION.match(prefix, branch.end())
            if header is None:
                return None
            branch_content_start = header.end()
            context = header.group(0).rstrip().rstrip("-—–").rstrip()
            if context not in sentence:
                contexts.append(context)
    if index and not _UNIVERSAL_SCOPE.search(sentence):
        previous_start = positions[index - 1]
        previous_end = previous_start + len(sentences[index - 1])
        if previous_start <= branch_content_start < previous_end:
            previous_start = branch_content_start
        previous = _without_source_marker(fact.value[previous_start:previous_end])
        previous_header = _BRANCH_CONDITION.match(previous)
        if previous_header is not None:
            previous = previous[previous_header.end():].strip()
        conditional = (_EXPLICIT_THEN_CONDITION.fullmatch(previous)
                       or _MODAL_CONDITION.fullmatch(previous))
        if conditional and previous_start >= branch_start:
            condition = conditional.group("condition")
            origin = re.search(r"\bс\s+момента\s+(.+)", match.group(0), flags=re.IGNORECASE)
            origin_anchors = _lexical_anchors(origin.group(1)) if origin else frozenset()
            # Actor/object overlap is not a causal link. Only a stated temporal
            # exception tied to the deadline's exact origin event can continue
            # into a non-anaphoric next sentence; otherwise retain it for review.
            if (not _TEMPORAL_CONDITION.search(condition) or len(origin_anchors) < 2
                    or not origin_anchors.issubset(_lexical_anchors(condition))):
                return None
            contexts.append(condition)
        elif (_TEMPORAL_CONDITION.search(previous)
              and re.search(r"\b(?:если|когда|при\s+условии)\b", previous, flags=re.IGNORECASE)
              and previous_start >= branch_start):
            # An embedded or malformed temporal condition is not permission to
            # emit the next deadline without it. Never guess a clause boundary.
            return None
        elif _DEPENDENT_TABLE_CLAUSE.match(_without_source_marker(sentence)):
            if previous_start < branch_start:
                return None
            contexts.append(sentences[index - 1])
    elif not index and _DEPENDENT_TABLE_CLAUSE.match(_without_source_marker(sentence)):
        return None
    source_rule = f"{sentence[:match.start()]}_____{sentence[match.end():]}"
    # Readable source scope, not an invitation to quote an entire compound cell.
    if sum(map(len, contexts)) + len(source_rule) > 700:
        return None
    return tuple(contexts), source_rule.strip()


def _conditional_rule_axes(fact: SourceFact, *, allow_short: bool = False) -> list[tuple[str, str]]:
    """Project a complete long conditional into source-owned condition/action roles."""
    if len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS and not allow_short:
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
        step_prompt = _focused_step_prompt(clause)
        if re.fullmatch(r"отметка\s+о\s+согласовании\s+не\s+проставляется[.!?]?", action,
                        flags=re.IGNORECASE):
            step_prompt = f"Нужно ли проставлять отметку о согласовании при условии «{condition}»?"
        if not step_prompt and _STEP_ACTION.search(action):
            continue
        context = f"Для «{fact.subject.strip()}»: " if is_tabular_locator(fact.source_locator) else ""
        prompt = (
            context
            + (step_prompt or f"какое действие предусмотрено при условии «{condition}»?")
        )
        axes.append((action, prompt))
    return axes


def _conditional_negative_right_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Ask for one exact prohibition inside its explicit source scenario."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        match = _CONDITIONAL_NEGATIVE_RIGHT.fullmatch(clause)
        if match is None:
            continue
        answer = match.group("answer").strip()
        if not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS:
            continue
        prompt = (
            f"Какое ограничение действует для «{match.group('actor').strip()}» "
            f"при условии "
            f"«{match.group('condition').strip()}»?"
        )
        axes.append((answer, prompt))
    return axes


def _shared_responsibility_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Split one explicit liability plus shared-modal obligations without paraphrase."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        match = _SHARED_RESPONSIBILITY_RULE.search(clause)
        if match is None:
            continue
        actor = match.group("actor").strip()
        responsibility = match.group("responsibility").strip()
        scope = match.group("scope").strip()
        if len(responsibility) <= MAX_ASSESSMENT_ANSWER_CHARS:
            axes.append((
                responsibility,
                f"Какую форму ответственности прямо называет это правило для «{actor}» {scope}?",
            ))
        actions = [
            item.strip().rstrip(".;")
            for item in _COORDINATED_INFINITIVE.split(match.group("actions"))
        ]
        if len(actions) < 2:
            continue
        for action in actions:
            parts = _operational_clause_parts(action)
            if parts is None:
                adverbial_action = re.match(
                    r"^(?:[А-Яа-яЁё]+\s+)?"
                    r"[А-Яа-яЁё]+(?:ть|ти|чь)(?:ся|сь)?\s+(?P<target>.+)$",
                    action,
                    flags=re.IGNORECASE,
                )
                if adverbial_action is not None:
                    parts = (adverbial_action.group("target").strip(), "", False)
            if (
                parts is None
                or not 12 <= len(action) <= MAX_ASSESSMENT_ANSWER_CHARS
            ):
                continue
            target, qualifier, _prohibited = parts
            condition = f" с учетом условия «{qualifier}»" if qualifier else ""
            if re.match(r"^бережно\s+относиться\s+к\s+.+\bимуществ", action, flags=re.IGNORECASE):
                prompt = (f"Как «{actor}» {match.group('modal').strip()} обращаться "
                          f"с вверенным имуществом отдельно от мер по предотвращению ущерба{condition}?")
            elif re.fullmatch(r"принимать\s+меры\s+по\s+предотвращению\s+ущерба", action,
                              flags=re.IGNORECASE):
                prompt = (f"Как «{actor}» {match.group('modal').strip()} действовать "
                          f"в отношении возможного ущерба{condition}?")
            else:
                prompt = (f"Какое действие в отношении «{target}» {match.group('modal').strip()} "
                          f"выполнить «{actor}»{condition}?")
            axes.append((
                action,
                prompt,
            ))
    return axes


def _explicit_consequence_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind a stated consequence to its complete source trigger and actors."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        match = _EXPLICIT_CONSEQUENCE_RULE.fullmatch(clause) or _VIOLATION_CONSEQUENCE_RULE.fullmatch(clause)
        if match is None:
            continue
        answer = match.group("answer").strip()
        scope = match.group("scope").strip().rstrip(" ,")
        if not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS:
            continue
        marker = re.match(r"^\s*(\d+(?:\.\d+)*)(?:[.)])\s+", sentence)
        provision = f" пунктом «{marker.group(1)}»" if marker else " этим правилом"
        prompt = f"Какое последствие прямо названо{provision} при условии «{scope}»?"
        if len(prompt) <= 900:
            axes.append((answer, prompt))
    return axes


def _instruction_schedule_axes(fact: SourceFact) -> list[tuple[str, str]]:
    axes: list[tuple[str, str]] = []
    unfinished_context = False
    for sentence in _source_sentences(fact.value):
        if sentence.rstrip().endswith(":"):
            unfinished_context = True
            continue
        match = _INSTRUCTION_SCHEDULE_RULE.fullmatch(_without_source_marker(sentence))
        if (match is not None and not unfinished_context
                and match.group("actor").casefold().strip() not in {"он", "она", "они", "это", "лицо"}
                and not re.match(r"^(?:если|при|когда)\b", match.group("actor"), flags=re.IGNORECASE)):
            answer = match.group("answer").strip()
            timing = re.fullmatch(
                r"(?P<action>проходят\s+(?:противопожарный\s+)?инструктаж(?:\s+по\s+[^.!?;:]+?)?)\s+"
                r"(?P<time>при\s+приеме\s+на\s+работу|не\s+реже\s+\d+\s+раз[а]?\s+в\s+год)",
                answer, flags=re.IGNORECASE,
            )
            axes.append((
                timing.group("time") if timing else answer,
                (f"Когда «{match.group('actor').strip()}» {timing.group('action')}?" if timing else
                 f"Какое правило проведения инструктажа установлено для «{match.group('actor').strip()}»?"),
            ))
        if not re.match(r"^\s*[-—–]", sentence) and sentence.endswith((".", "!", "?")):
            unfinished_context = False
    return axes


def _delegated_responsibility_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Keep an assigned owner, appointment, and alternative functions separate."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        responsibility = _PASSIVE_RESPONSIBILITY_RULE.fullmatch(clause)
        if responsibility is not None:
            actor = responsibility.group("actor").strip()
            duty = responsibility.group("duty").strip()
            if len(actor) <= MAX_ASSESSMENT_ANSWER_CHARS:
                axes.append((actor, f"На кого возлагается «{duty}»?"))
            continue
        appointed = _APPOINTED_FUNCTION_RULE.fullmatch(clause)
        if appointed is None:
            continue
        appointment = appointed.group("appointment").strip()
        appointing_actor = appointed.group("actor").strip()
        qualification = appointed.group("qualification").strip()
        functions = appointed.group("functions").strip()
        appointment_prompt = f"Кто {appointment}, которые {qualification} {functions}?"
        functions_prompt = (
            "Какие варианты функций предусмотрены для назначенных лиц с учетом "
            f"основания «{qualification}»?"
        )
        if (
            len(appointing_actor) <= MAX_ASSESSMENT_ANSWER_CHARS
            and len(appointment_prompt) <= 900
        ):
            axes.append((
                appointing_actor, appointment_prompt,
            ))
        if len(functions) <= MAX_ASSESSMENT_ANSWER_CHARS and len(functions_prompt) <= 900:
            axes.append((
                functions, functions_prompt,
            ))
    return axes


def _scoped_modal_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Keep a complete modal action while moving an overlong exact scope to the prompt."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        match = _SCOPED_MODAL_RULE.fullmatch(clause)
        if match is None:
            continue
        answer = match.group("answer").strip()
        scope = match.group("scope").strip()
        if not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS:
            continue
        prompt = (
            f"Для «{match.group('subject').strip()}» какое действие предусмотрено "
            f"с учетом требования «{scope}»?"
        )
        if len(prompt) <= 900:
            axes.append((answer, prompt))
    return axes


def _independent_state_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Account for each complete affirmative state duty, not only the salient one."""
    if is_tabular_locator(fact.source_locator):
        return []
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        match = re.fullmatch(
            r"(?P<subject>[^.!?;:]{3,180}?)(?:\s+(?P<time>всегда|постоянно))?\s+"
            r"(?P<key>долж(?:ен|на|но|ны)\s+(?:постоянно\s+)?(?:содержаться|находиться|быть)\s+[^.!?;:]+)[.!?]?",
            _without_source_marker(sentence), flags=re.IGNORECASE,
        )
        if match is None or re.search(
            r"\b(?:не|если|когда|при|он|она|они|эт(?:от|а|о|и|ого|ой|ому|им|их|ими|ом|у)|"
            r"указанн\w*|так(?:ой|ая|ое|ие|ого|ому|им|их|ими|ом|ую))\b",
            match.group("subject"), flags=re.IGNORECASE,
        ):
            continue
        answer = match.group("key").strip()
        if len(answer) > MAX_ASSESSMENT_ANSWER_CHARS:
            continue
        timing = f" {match.group('time')}" if match.group("time") else ""
        axes.append((answer, f"Какое состояние требуется{timing} для «{match.group('subject')}»?"))
    return axes


def _time_qualified_modal_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Move a complete explicit time/exception scope into a mandatory prompt."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence).rstrip(".!?")
        if (
            _EXPLICIT_THEN_CONDITION.fullmatch(clause)
            or _MODAL_CONDITION.fullmatch(clause)
        ):
            continue
        modals = list(re.finditer(r"\b(?:долж(?:ен|на|но|ны)|обязан\w*)\b", clause,
                                  flags=re.IGNORECASE))
        if len(modals) != 1:
            continue
        modal = modals[0]
        scope = clause[:modal.start()].strip(" ,")
        answer = clause[modal.start():].strip()
        if (
            not _TIME_QUALIFIED_SCOPE.search(scope)
            or not 12 <= len(scope) <= 700
            or not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS
        ):
            continue
        prompt = (
            f"Какое действие предусмотрено при условии «{scope}»?"
        )
        if len(prompt) <= 900:
            axes.append((answer, prompt))
    return axes


def _coordinated_conditional_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Split two explicit finite actions that share one source condition and actor."""
    axes: list[tuple[str, str]] = []
    for sentence in _source_sentences(fact.value):
        clause = _without_source_marker(sentence)
        conditional = _EXPLICIT_THEN_CONDITION.fullmatch(clause)
        if conditional is None:
            continue
        actions = re.split(
            r",\s*а\s+также\s+",
            conditional.group("action"),
            maxsplit=1,
            flags=re.IGNORECASE,
        )
        if len(actions) != 2:
            continue
        first = _ACTOR_FINITE_ACTION.fullmatch(actions[0].strip())
        second = _FINITE_ACTION.fullmatch(actions[1].strip().rstrip("."))
        if first is None or second is None:
            continue
        actor = first.group("actor").strip()
        condition = conditional.group("condition").strip()
        for action in (first, second):
            answer = action.group("answer").strip().rstrip(".")
            target = action.group("target").strip().rstrip(".")
            signing_day = re.fullmatch(
                r"(?P<action>подписывает\s+.+?)\s+(?P<day>в\s+день\s+[^.!?]{5,140})",
                answer, flags=re.IGNORECASE,
            )
            day_scope = ""
            if signing_day is not None:
                answer = signing_day.group("action")
                day_scope = signing_day.group("day")
                target = target[:target.rfind(day_scope)].strip()
            if not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS:
                continue
            marking = re.fullmatch(r"(?:об\s+этом\s+)?отметку\s+(?P<location>в\s+.+)", target,
                                  flags=re.IGNORECASE)
            prompt = (
                f"Как «{actor}» фиксирует решение {marking.group('location')} "
                f"при условии «{condition}»?"
                if marking is not None else
                f"Какое действие в отношении «{target}» выполняет «{actor}» "
                f"при условии «{condition}»?"
            )
            if day_scope:
                prompt = prompt.rstrip("?") + f" в срок «{day_scope}»?"
            axes.append((
                answer,
                prompt,
            ))
    return axes


def _numbered_action_scope(fact: SourceFact, answer: str) -> str | None:
    """Resolve a unique exact numbered branch without importing its sibling."""
    scopes: set[str] = set()
    for match in re.finditer(re.escape(answer), fact.value):
        prefix = fact.value[:match.start()]
        branches = list(_NUMBERED_BRANCH.finditer(prefix))
        scope = ""
        if branches:
            header = _BRANCH_CONDITION.match(prefix, branches[-1].end())
            if header is None:
                if any(_BRANCH_CONDITION.match(prefix, branch.end()) for branch in branches[:-1]):
                    return None
            else:
                scope = header.group().rstrip().rstrip("-—–").rstrip()
        scopes.add(scope)
    return next(iter(scopes)) if len(scopes) == 1 else None


def _location_branch_header(fact: SourceFact, first_branch_start: int) -> tuple[str, int] | None:
    """Keep only the containing source sentence's full shared branch header."""
    cursor = 0
    for sentence in _source_sentences(fact.value):
        start = fact.value.index(sentence, cursor)
        cursor = start + len(sentence)
        if start <= first_branch_start < cursor:
            header = fact.value[start:first_branch_start].rstrip(" :")
            return (header, start) if header else None
    return None


def _flattened_location_branch_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Project only visibly delimited table branches with independent scope."""
    if (
        not is_tabular_locator(fact.source_locator)
        or len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
    ):
        return []
    matches = list(_FLATTENED_LOCATION_BRANCH.finditer(fact.value))
    if len(matches) < 2:
        return []
    header_parts = _location_branch_header(fact, matches[0].start())
    if header_parts is None:
        return []
    header, _header_start = header_parts
    actors = list(re.finditer(
        r"(?P<actor>(?:[А-ЯЁ][а-яё-]+|[А-ЯЁ]{2,})"
        r"(?:\s+(?:[А-ЯЁ][а-яё-]+|[А-ЯЁ]{2,})){0,3})\s+"
        r"(?:проводит|осуществляет|выполняет|проверяет)\b",
        header,
    ))
    if not actors:
        return []
    actor = actors[-1].group("actor").strip()
    axes: list[tuple[str, str]] = []
    for match in matches:
        condition = match.group("condition").strip()
        answer = match.group("answer").strip()
        if not 12 <= len(answer) <= MAX_ASSESSMENT_ANSWER_CHARS:
            continue
        prompt = (
            f"Для «{fact.subject.strip()}»: какое правило применяет «{actor}» "
            f"при условии «{condition}» в рамках «{header}»?"
        )
        if len(prompt) > 900:
            return []
        axes.append((answer, prompt))
    return axes if len(axes) == len(matches) else []


def _dependent_signature_prompt(handover: re.Match[str], signature: re.Match[str]) -> str:
    """One canonical stem preserves the adjacent source actor and both conditions."""
    return (
        f"Какое действие выполняет «{handover.group('actor').strip()}» "
        f"{handover.group('timing').strip()} при условии "
        f"«{handover.group('condition').strip()}» и при условии "
        f"«{signature.group('condition').strip()}»?"
    )


def _handover_response_axes(fact: SourceFact) -> list[tuple[str, str]]:
    """Bind one handover check and its explicit escalation branches end to end."""
    if (
        not is_tabular_locator(fact.source_locator)
        or len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
    ):
        return []
    sentences = _source_sentences(fact.value)
    clauses = [_without_source_marker(sentence) for sentence in sentences]
    axes: list[tuple[str, str]] = []
    for index, clause in enumerate(clauses):
        handover = _PARENTHETICAL_MODAL_RULE.fullmatch(clause)
        if handover is not None:
            handover_actor = handover.group("actor").strip()
            answer = handover.group("answer").strip()
            axes.append((
                answer,
                f"Какое действие обязан выполнить «{handover_actor}» "
                f"{handover.group('timing').strip()} при условии "
                f"«{handover.group('condition').strip()}»?",
            ))
            continue
        signature = _DEPENDENT_SIGNATURE_RULE.fullmatch(clause)
        previous_handover = (
            _PARENTHETICAL_MODAL_RULE.fullmatch(clauses[index - 1])
            if index else None
        )
        if signature is not None and previous_handover is not None:
            axes.append((
                signature.group("answer").strip(),
                _dependent_signature_prompt(previous_handover, signature),
            ))
            continue
        notification = _EXPLICIT_THEN_CONDITION.fullmatch(clause)
        step_prompt = _focused_step_prompt(clause) if notification else ""
        if notification is not None and step_prompt:
            answer = notification.group("action").strip()
            axes.append((answer, step_prompt))
            continue
        response = _DUAL_LOCATION_RESPONSE_RULE.fullmatch(clause)
        if response is None or not index:
            continue
        previous = _EXPLICIT_THEN_CONDITION.fullmatch(clauses[index - 1])
        if previous is None or not _focused_step_prompt(clauses[index - 1]):
            continue
        trigger = previous.group("condition").strip()
        notification_action = previous.group("action").strip().rstrip(".")
        actor = response.group("actor").strip()
        purpose = response.group("purpose").strip()
        local_condition = response.group("local_condition").strip()
        remote_condition = response.group("remote_condition").strip()
        common = (
            f"После действия «{notification_action}» при условии «{trigger}»"
        )
        axes.append((
            response.group("local_action").strip(),
            f"{common}: какое действие обязан выполнить «{actor}» при условии "
            f"«при {local_condition}» {purpose}?",
        ))
        axes.append((
            response.group("remote_deadline").strip(),
            f"{common}: в какой срок «{actor}» обязан выехать при условии "
            f"«при {remote_condition}» {purpose}?",
        ))
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


def _deadline_axes(
    fact: SourceFact, *, excluded_sentences: frozenset[int] = frozenset(),
) -> list[tuple[str, str]]:
    """Extract exact bounded deadlines while retaining their whole source rule."""
    if len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS:
        return []
    sentences = _source_sentences(fact.value)
    axes: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, sentence in enumerate(sentences):
        if index in excluded_sentences:
            continue
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
            origin = re.search(r"\bс\s+момента\s+(.+)", answer, flags=re.IGNORECASE)
            if (
                len(answer) > MAX_ASSESSMENT_ANSWER_CHARS
                or not has_temporal_unit(answer)
                or (origin is not None and re.search(
                    r"\b(?:и|а|но|либо|или)\b", origin.group(1), flags=re.IGNORECASE,
                ) is not None)
            ):
                continue
            scoped = _deadline_source_rule(fact, sentences, index, match)
            if scoped is None:
                continue
            contexts, source_rule = scoped
            scope = " ".join(f"Контекст: «{context}»." for context in contexts)
            prompt = (
                f"Для «{fact.subject.strip()}» в характеристике "
                f"«{fact.attribute.strip()}». {scope} Какой точный срок пропущен в исходном "
                f"правиле «{source_rule.strip()}»?"
            )
            if len(prompt) > 900 or (answer, prompt) in seen:
                continue
            axes.append((answer, prompt))
            seen.add((answer, prompt))
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
    prompt = _focused_step_prompt(clause)
    generic_prompt = _required_prompt(clause) if not prompt else ""
    if generic_prompt and _STEP_ACTION.search(clause):
        return ""
    prompt = prompt or generic_prompt
    if not prompt:
        parts = _operational_clause_parts(clause.rstrip(".;"))
        if parts is None:
            return ""
        target, qualifier, prohibited = parts
        conditional_prefix = re.match(
            r"^(?:если|когда|в\s+случае\s+если|при\s+условии)\b", clause,
            flags=re.IGNORECASE,
        )
        if conditional_prefix and ("," not in clause
                                   or not qualifier.startswith(clause.split(",", 1)[0])):
            # The generic actor/action parser must not discard a leading
            # condition (or shorten it to 'if the actor must') when it finds
            # an infinitive inside that condition rather than in the action.
            return ""
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


def _sentence_conditional_axes(fact: SourceFact) -> list[tuple[str, str]]:
    return _conditional_rule_axes(fact, allow_short=True)


def _has_incomplete_specialized_sentences(fact: SourceFact, sentences: list[str]) -> bool | None:
    """Account for every sentence when a specialized narrative projector is used.

    Match against the targets actually derived for this parent, not the union of
    all possible grammar matches: precedence can suppress a different family.
    Derivation never calls this audit, so this single-fact probe is non-recursive.
    """
    projectors = (
        _delegated_responsibility_axes, _shared_responsibility_axes, _instruction_schedule_axes,
        _explicit_consequence_axes, _scoped_modal_axes, _time_qualified_modal_axes,
        _conditional_negative_right_axes, _coordinated_conditional_axes,
        _sentence_conditional_axes,
        _independent_state_axes,
    )
    if len(sentences) < 2 or not any(project(fact) for project in projectors):
        return None
    lesson = LessonDraft("source-coverage", "", "", "", "", (fact.fact_id,), (), 1)
    derived = derive_assessment_axes(lesson, [fact], block_id="source-coverage")
    actual = {(_norm(axis.correct_value), _norm(axis.required_prompt)) for axis in derived}
    actual_keys = {value.rstrip(".!?") for value, _prompt in actual}
    actual_selections = {(_norm(axis.correct_value), _norm(axis.required_prompt))
                         for axis in derived if axis.axis_kind == "selection"}
    selected_references = {selection.sentence_index for selection in project_reference_selections(fact, sentences)
                           if (_norm(selection.answer), _norm(selection.required_prompt)) in actual_selections}
    for sentence_index, sentence in enumerate(sentences):
        if sentence_index in selected_references:
            continue
        child = replace(fact, value=sentence)
        expected = [pair for project in projectors for pair in project(child)]
        shared = _SHARED_RESPONSIBILITY_RULE.search(sentence)
        if shared is not None and len(_shared_responsibility_axes(child)) != (
            1 + len(_COORDINATED_INFINITIVE.split(shared.group("actions")))
        ):
            return True
        if _APPOINTED_FUNCTION_RULE.fullmatch(sentence) is not None and len(
            _delegated_responsibility_axes(child)
        ) != 2:
            return True
        if expected:
            if any((_norm(value), _norm(prompt)) not in actual for value, prompt in expected):
                return True
        elif _norm(sentence).rstrip(".!?") not in actual_keys:
            return True
    return False


def _nominal_parenthetical_scope(value: str) -> str | None:
    """Remove only non-predicative context, never hide an independent action."""
    for match in re.finditer(r"\(([^()]*)\)", value):
        content = match.group(1)
        # Coverage is a closed admission rule, not a general parenthesis eraser.
        # Only the supported nominal inspection lists can be contextual scope.
        nominal = re.match(
            r"\s*(?:включая\s+)?(?:осмотр|проверк\w*|соответстви\w*|подписани\w*|согласовани\w*)\b",
            content, flags=re.IGNORECASE,
        )
        predicate = re.search(
            rf"\b(?:{_FINITE_ACTION_VERB}|долж(?:ен|на|но|ны)|обязан(?:а|о|ы)?|"
            r"необходимо|следует|нужно|требуется|надо|[А-Яа-яЁё]+(?:ть|ться|ти|тись|"
            r"л|ла|ло|ли|лся|лась|лось|лись|ен|ена|ено|ены|ён|ёна|ёно|ёны|ан|ана|ано|аны|ят|ята|ято|яты))\b",
            content, flags=re.IGNORECASE,
        )
        if not nominal or predicate or re.search(r"[:;!?]", content):
            return None
    result = re.sub(r"\([^()]*\)", " ", value)
    return None if "(" in result or ")" in result else result


def _operational_coverage_projections(
    fact: SourceFact, sentences: list[str], actual: list[tuple[str, str]],
    *, selection_targets: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[OperationalProjection, ...]:
    """Attach exact coverage only to complete grammar groups admitted as targets.

    Multi-action full-sentence claims require every member of that grammar group
    to survive derivation. Partial-prefix projectors retain their own spans.
    """
    actual_pairs = {(_norm(answer), _norm(prompt)) for answer, prompt in actual}
    projections = list(project_operational_inspections(fact, sentences))
    projections.extend(project_operational_approvals(fact, sentences))
    for selection in project_reference_selections(fact, sentences):
        if ((_norm(selection.answer), _norm(selection.required_prompt)) in actual_pairs
                and (_norm(selection.answer), _norm(selection.required_prompt)) in selection_targets):
            projections.append(OperationalProjection(
                OperationalStep(selection.answer, selection.required_prompt,
                                selection.sentence_index, selection.sentence_index, selection.scope),
                selection.consumed_spans,
            ))

    def claim_sentence(index: int, pairs: list[tuple[str, str]]) -> None:
        if not pairs or any((_norm(answer), _norm(prompt)) not in actual_pairs
                            for answer, prompt in pairs):
            return
        answer, prompt = pairs[0]
        sentence = sentences[index]
        projections.append(OperationalProjection(
            OperationalStep(answer, prompt, index, index, ""),
            (ExactSentenceSpan(index, 0, len(sentence), sentence),),
        ))

    steps = (*project_rejection_followups(fact, sentences),
             *project_signing_responsibilities(fact, sentences))
    for index in sorted({step.consumed_sentence_index for step in steps}):
        claim_sentence(index, [(step.answer, step.required_prompt) for step in steps
                               if step.consumed_sentence_index == index])

    handovers = _handover_response_axes(fact)
    deadlines = _deadline_axes(fact)
    for index, sentence in enumerate(sentences):
        clause = _without_source_marker(sentence)
        child = replace(fact, value=sentence)
        negative = _conditional_negative_right_axes(child)
        if negative:
            claim_sentence(index, negative)
        coordinated = _coordinated_conditional_axes(child)
        if len(coordinated) == 2:
            claim_sentence(index, coordinated)
        conditional = _conditional_rule_axes(child, allow_short=True)
        if conditional:
            claim_sentence(index, conditional)

        handover = _PARENTHETICAL_MODAL_RULE.fullmatch(clause)
        signature = _DEPENDENT_SIGNATURE_RULE.fullmatch(clause)
        notification = _EXPLICIT_THEN_CONDITION.fullmatch(clause)
        response = _DUAL_LOCATION_RESPONSE_RULE.fullmatch(clause)
        if handover is not None:
            expected_keys = {handover.group("answer").strip()}
        elif signature is not None and index and _PARENTHETICAL_MODAL_RULE.fullmatch(
            _without_source_marker(sentences[index - 1]),
        ) is not None:
            expected_keys = {signature.group("answer").strip()}
        elif notification is not None and _focused_step_prompt(clause):
            expected_keys = {notification.group("action").strip()}
        elif response is not None:
            expected_keys = {response.group("local_action").strip(),
                             response.group("remote_deadline").strip()}
        else:
            expected_keys = set()
        matching = [(answer, prompt) for answer, prompt in handovers if answer in expected_keys]
        if expected_keys and len(matching) == len(expected_keys):
            claim_sentence(index, matching)

        temporal = [match for pattern in _DEADLINE_VALUES for match in pattern.finditer(sentence)]
        temporal_pairs: list[tuple[str, str]] = []
        for match in temporal:
            scoped = _deadline_source_rule(fact, sentences, index, match)
            if scoped is not None:
                _contexts, source_rule = scoped
                temporal_pairs.extend((answer, prompt) for answer, prompt in deadlines
                                      if answer == match.group(0).strip() and source_rule in prompt)
        if len(temporal) == 1 and len(temporal_pairs) == 1:
            match = temporal[0]
            prefix = sentence[:match.start()]
            plain_prefix = _nominal_parenthetical_scope(prefix)
            # Only one bounded predicate may consume its leading context. A
            # deadline does not assess a comma-separated or coordinated sibling.
            if (plain_prefix is not None
                    and not re.search(r"[,;:()!?]|\b(?:и|а|но|либо|или)\b", plain_prefix,
                              flags=re.IGNORECASE)
                    and re.search(r"\b(?:производ(?:ит|ят|ится|ятся)|"
                                  r"провод(?:ит|ят|ится|ятся)|"
                                  r"выполня(?:ет|ют|ется|ются))\s*$", plain_prefix,
                                  flags=re.IGNORECASE)):
                answer, prompt = temporal_pairs[0]
                projections.append(OperationalProjection(
                    OperationalStep(answer, prompt, index, index, ""),
                    (ExactSentenceSpan(index, 0, match.end(), sentence[:match.end()]),),
                ))

        # An admitted exact whole-sentence key is already a complete source span;
        # finding only an answer substring somewhere in the parent is not enough.
        whole = [(answer, prompt) for answer, prompt in actual
                 if _norm(answer).rstrip(".!?") == _norm(clause).rstrip(".!?")]
        if whole:
            claim_sentence(index, whole)

    location_pairs = _flattened_location_branch_axes(fact)
    matches = list(_FLATTENED_LOCATION_BRANCH.finditer(fact.value))
    header = _location_branch_header(fact, matches[0].start()) if matches else None
    if header is not None and location_pairs and len(location_pairs) == len(matches):
        header_text, header_start = header
        plain_header = _nominal_parenthetical_scope(header_text)
        header_is_scope = (
            plain_header is not None
            and re.match(r"^(?:Согласование|Проверку|Осмотр|Контроль)\b", plain_header,
                     flags=re.IGNORECASE) is not None
            and not re.search(r"[,;:()!?]", plain_header)
            and not re.search(r"\b(?:и|а|но|либо|или)\b", plain_header, flags=re.IGNORECASE)
            and re.search(r"\b(?:проводит|осуществляет|выполняет|проверяет)$",
                          plain_header.strip(), flags=re.IGNORECASE) is not None
        )
        cursor = 0
        positions: list[int] = []
        for sentence in sentences:
            position = fact.value.index(sentence, cursor)
            positions.append(position)
            cursor = position + len(sentence)
        for (answer, prompt), match in zip(location_pairs, matches, strict=True):
            spans: list[ExactSentenceSpan] = []
            ranges = [match.span()]
            if header_is_scope:
                ranges.insert(0, (header_start, header_start + len(header_text)))
            for start, end in ranges:
                for index, position in enumerate(positions):
                    left, right = max(start, position), min(end, position + len(sentences[index]))
                    if left < right:
                        spans.append(ExactSentenceSpan(index, left - position, right - position,
                                                       fact.value[left:right]))
            if spans:
                index = spans[-1].sentence_index
                projections.append(OperationalProjection(
                    OperationalStep(answer, prompt, index, index, ""), tuple(spans),
                ))
    return tuple(projections)


def has_partial_unatomized_source_contract(fact: SourceFact) -> bool:
    """Flag source content not claimed by a complete bounded projection."""
    source_sentences = _source_sentences(fact.value)
    selections = project_reference_selections(fact, source_sentences)
    selectable_indexes = {selection.sentence_index for selection in selections}
    if any(is_unresolved_procedure_reference(sentence) and index not in selectable_indexes
           for index, sentence in enumerate(source_sentences)):
        return True
    if selections:
        lesson = LessonDraft("source-coverage", "", "", "", "", (fact.fact_id,), (), 1)
        selection_pairs = {(_norm(axis.correct_value), _norm(axis.required_prompt))
                           for axis in derive_assessment_axes(lesson, [fact], block_id="source-coverage")
                           if axis.axis_kind == "selection"}
        if any((_norm(selection.answer), _norm(selection.required_prompt)) not in selection_pairs
               for selection in selections):
            return True
    if (selections or project_rejection_followups(fact, source_sentences)
            or project_signing_responsibilities(fact, source_sentences)
            or project_operational_inspections(fact, source_sentences)
            or project_operational_approvals(fact, source_sentences)):
        lesson = LessonDraft("source-coverage", "", "", "", "", (fact.fact_id,), (), 1)
        axes = derive_assessment_axes(lesson, [fact], block_id="source-coverage")
        actual = [(axis.correct_value, axis.required_prompt) for axis in axes]
        projections = _operational_coverage_projections(fact, source_sentences, actual,
            selection_targets=frozenset((_norm(axis.correct_value), _norm(axis.required_prompt))
                                        for axis in axes if axis.axis_kind == "selection"))
        return bool(audit_operational_coverage(source_sentences, actual, projections).uncovered_spans)
    sentences = [
        clause
        for item in _source_sentences(fact.value)
        if (clause := _without_source_marker(item))
        and not re.fullmatch(r"\d+(?:\.\d+)*[.)]?", clause)
    ]
    structured = _explicit_structured_list(fact.value)
    if structured is not None and _structured_operational_axes(fact):
        lesson = LessonDraft("source-coverage", "", "", "", "", (fact.fact_id,), (), 1)
        derived_axes = derive_assessment_axes(lesson, [fact], block_id="source-coverage")
        # Audit source children, not just the subset of targets already derived.
        # Complete source children may be in the key OR the mandatory stem (a
        # prohibition/responsibility question); punctuation is not lexical scope.
        def normalized(text: str) -> str:
            return " ".join(_ANCHOR_TOKEN.findall(_norm(text)))

        return any(not any(normalized(statement) in normalized(
            axis.correct_value + " " + axis.required_prompt,
        ) or _focused_list_duty(fact, statement) == (axis.correct_value, axis.required_prompt)
                          or _simple_list_obligation_axis(fact, statement) == (
                              axis.correct_value, axis.required_prompt,
                          )
                          for axis in derived_axes) for _position, clause in structured[1]
                   for statement in _structured_child_statements(clause))
    specialized_partial = _has_incomplete_specialized_sentences(fact, sentences)
    if specialized_partial is not None:
        return specialized_partial
    conditional_axes = _conditional_rule_axes(fact)
    if len(sentences) > 1 and conditional_axes:
        fallback = _norm(_source_owned_correct_value(fact))
        conditional_coverage = {
            (_norm(value), _norm(prompt))
            for value, prompt in conditional_axes
        }
        for sentence in sentences:
            if _norm(sentence) == fallback:
                continue
            conditional = (
                _EXPLICIT_THEN_CONDITION.fullmatch(sentence)
                or _MODAL_CONDITION.fullmatch(sentence)
            )
            if conditional is not None and any(
                _norm(conditional.group("action")) == value
                and _norm(conditional.group("condition")) in prompt
                for value, prompt in conditional_coverage
            ):
                continue
            return True
    if (
        not is_tabular_locator(fact.source_locator)
        or len(fact.value.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
        or _structured_operational_axes(fact)
        or _regulatory_table_range_axes(fact)
    ):
        return False
    return bool(
        _flattened_location_branch_axes(fact)
        or _handover_response_axes(fact)
        or _coordinated_conditional_axes(fact)
        or _conditional_rule_axes(fact)
        or _deadline_axes(fact)
        or _compound_table_operational_axes(fact)
    )


def derive_reference_only_dependencies(fact: SourceFact) -> tuple[ExactSentenceSpan, ...]:
    """Record nonexecuting section locators without claiming their contents."""
    sentences = _source_sentences(fact.value)
    lesson = LessonDraft("source-coverage", "", "", "", "", (fact.fact_id,), (), 1)
    axes = derive_assessment_axes(lesson, [fact], block_id="source-coverage")
    actual = [(axis.correct_value, axis.required_prompt) for axis in axes]
    projections = _operational_coverage_projections(fact, sentences, actual,
        selection_targets=frozenset((_norm(axis.correct_value), _norm(axis.required_prompt))
                                    for axis in axes if axis.axis_kind == "selection"))
    return audit_operational_coverage(sentences, actual, projections).reference_only_spans


def _unsupported_operational_list(fact: SourceFact) -> bool:
    """Fail closed when independent actions have no safe shared context."""
    structured = _explicit_structured_list(fact.value)
    if structured is None:
        return False
    preamble, clauses = structured
    if (re.search(r"\b(?:запрещается|запрещено|нельзя|не\s+допускается)\s*$", preamble, flags=re.IGNORECASE)
            and _affirmative_prohibition_modal(preamble) is None):
        return True
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


def is_assessment_reference_metadata(fact: SourceFact) -> bool:
    """Identify a standalone drafting-basis bibliography, never a working rule.

    Keep this evidence in the lesson and governing context. Its legal citations
    are not a worker competence; dates and section ordinals must not become test
    targets. A second sentence, imperative, condition or modal duty fails closed.
    """
    if is_tabular_locator(fact.source_locator):
        return False
    value = _without_source_marker(fact.value).strip()
    bibliography = re.fullmatch(
        r"(?:(?:Настоящие|Данные)\s+)?(?:правила|требования|стандарты)"
        r"(?:\s+[^,.!?;:\n]{1,100}?)?\s+разработаны\s+"
        r"в\s+соответствии\s+с\s+(?P<basis>[^!?\n]+)", value, flags=re.IGNORECASE,
    )
    if bibliography is None:
        return False
    if re.search(
        r"\b(?:долж\w*|обязан\w*|нельзя|запрещ\w*|не\s+допуска\w*|"
        r"следует|необходимо|если|когда|сотрудник\w*|проверь\w*|выполни\w*)\b",
        value, flags=re.IGNORECASE,
    ):
        return False
    if ";" in value or re.search(r"\.\s+[А-Яа-яЁё]", value):
        return False
    # Only a closed list of nominal citation heads may continue after commas.
    # Do not try to recognize every Russian imperative/infinitive: unknown
    # continuations remain ordinary assessable evidence, never hidden context.
    if any(not re.match(
        r"^(?:Законом|Законами|Кодексом|Приказом|Приказами|Постановлением|"
        r"Правилами|Требованиями|Положением|Инструкцией|Стандартом|утвержденн\w*)\b",
        part.strip(), flags=re.IGNORECASE,
    ) for part in bibliography.group("basis").split(",")):
        return False
    # Err on keeping doubtful text assessable: an infinitive/imperative can
    # introduce a lowercase working instruction even after a mere comma.
    return not re.search(
        r"\b(?:[А-Яа-яЁё]+(?:ть|чь)(?:ся|сь)?|храни\w*|проверь\w*|"
        r"выполни\w*|пройди\w*|провести|пройти)\b", value, flags=re.IGNORECASE,
    )


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


def _room_installation_prohibition(value: str) -> tuple[str, str] | None:
    """Contrast one complete room/object prohibition, never qualified clauses."""
    match = re.fullmatch(
        r"(?P<scope>В\s+помещениях\s+[А-Яа-яЁё]+(?:\s*,\s*[А-Яа-яЁё]+)*)\s+"
        r"не\s+должно\s+допускаться\s+(?P<object>устройство\s+[^,.!?;:—\n]+)\.?",
        value.strip(), flags=re.IGNORECASE,
    )
    if match is None or re.search(
        r"\b(?:кроме|исключени\w*|если|когда|при|после|до|пока|но|однако|не|только|лишь)\b",
        match['object'], flags=re.IGNORECASE,
    ):
        return None
    scope, object_value = match['scope'], match['object']
    return (f"Допускается ли {scope[:1].lower()}{scope[1:]} {object_value}?",
            f"{scope} допускается {object_value}.")


def _categorical_conditional_prohibition(value: str) -> tuple[str, str] | None:
    """Negate permission, not a condition inside one complete prohibition."""
    match = re.fullmatch(
        r"(?P<actor>[^,.!?;:]{3,100})\s+категорически\s+запрещается\s+"
        r"(?P<action>[А-Яа-яЁё]+(?:ть|ти|чь)\s+[^,.!?;:]{5,140}),\s*"
        r"(?P<condition>в\s+случае\s+если\s+[^,.!?;:]{5,180})[.]?",
        value.strip(), re.IGNORECASE,
    )
    if match is None or re.search(
        r"\b(?:кроме|исключени\w*|но|однако|только|лишь)\b",
        match['action'] + ' ' + match['condition'], re.IGNORECASE,
    ):
        return None
    return (
        f"Разрешается ли «{match['actor']}» {match['action']} {match['condition']}?",
        re.sub(r"категорически\s+запрещается", "разрешается", value.strip(), count=1, flags=re.IGNORECASE),
    )


def _required_prompt(correct_value: str) -> str:
    categorical = _categorical_conditional_prohibition(correct_value)
    if categorical is not None:
        return categorical[0]
    room_prohibition = _room_installation_prohibition(correct_value)
    if room_prohibition is not None:
        return room_prohibition[0]
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


def _nominal_placement_prohibition(value: str) -> tuple[str, str] | None:
    """A complete nominal placement ban, not an inferred permitted location."""
    match = re.fullmatch(
        r"Не допускается (?P<placement>размещение [^.!?;:\r\n—–]{3,240} вплотную к [^,.!?;:\r\n—–]{3,160})[.]?",
        value.strip(), re.IGNORECASE,
    )
    if match is None or re.search(
        r"\b(?:кроме|исключени\w*|если|когда|но|однако|только|лишь|не|при|после|до|"
        r"следует|необходимо|разрешен[аоы]?|допустим[аоы]?|запрещен[аоы]?|обязательн[аоы]?|"
        r"возможн[аоы]?|можно|нельзя|нужно|надо|[А-Яа-яЁё]+(?:ется|ются|ит|ят|ет|ют|ат)(?:ся)?)\b",
        match['placement'], re.IGNORECASE,
    ):
        return None
    return f"Допустимо ли {match['placement']}?", f"Допускается {match['placement']}."


def _server_owned_inverse(correct_value: str) -> str | None:
    """Build an exact binary opposite for server-owned yes/no statements.

    Asking a model for several distractors to a binary normative statement
    only creates paraphrases of the same mistake.  For patterns whose truth
    and negation are unambiguous, the server owns both choices and emits a
    true/false assessment instead.
    """
    categorical = _categorical_conditional_prohibition(correct_value)
    if categorical is not None:
        return categorical[1]
    placement = _nominal_placement_prohibition(correct_value)
    if placement is not None:
        return placement[1]
    inspection_timing = re.fullmatch(
        r"(?P<subject>согласование\s+[^,.!?;:]{3,100})\s+осуществляется\s+"
        r"(?P<timing>во\s+время\s+проведения\s+(?:[А-Яа-яЁё]+(?:ых|их)\s+)+проверок)[.]?",
        correct_value.strip(), re.IGNORECASE,
    )
    if inspection_timing is not None:
        # Deny the complete stated event. This does not add 'only', an
        # exclusive schedule, or a ban on any other inspection.
        return f"{inspection_timing['subject']} не осуществляется {inspection_timing['timing']}."
    room_prohibition = _room_installation_prohibition(correct_value)
    if room_prohibition is not None:
        return room_prohibition[1]
    direct = _direct_binary_prohibition(correct_value)
    if direct is not None:
        return direct[1]
    obligation = re.fullmatch(
        r"(?P<modal>должен|должна|должно|должны|обязан|обязана|обязано|обязаны)\s+(?P<action>[^.!?;:]+)\.?",
        correct_value.strip(), flags=re.IGNORECASE,
    )
    if obligation is not None:
        # Negate the complete obligation, not individual joint actions, dates
        # or conditions. Several cosmetic versions of 'not required' are one
        # mistake and must not be padded into a multiple-choice item.
        form = {"должен": "обязан", "должна": "обязана", "должно": "обязано", "должны": "обязаны"}
        modal = obligation.group('modal').casefold()
        return f"не {form.get(modal, modal)} {obligation.group('action')}"
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


def assessment_option_token_limit(axis: AssessmentAxis) -> int | None:
    """Expose the existing concise answer-domain contract before paid authoring."""
    correct_tokens = _ANCHOR_TOKEN.findall(axis.correct_value)
    if (
        axis.axis_kind != "attribute"
        or len(axis.correct_value) > 50
        or not 1 <= len(correct_tokens) <= 3
    ):
        return None
    return len(correct_tokens) + 3


def assessment_source_timing_exclusions(axis: AssessmentAxis) -> list[str]:
    """Expose known source-true timing alternatives before paid authoring.

    These values are not proved false under an action-only stem. The same
    guard still rejects them at admission; the author can avoid wasting its
    bounded attempt on an alternative that the server must remove.
    """
    return list(dict.fromkeys(
        _norm(match.group()) for constraint in axis.distractor_constraints
        for match in re.finditer(r"\bв\s+(?:первый|следующий)\s+рабочий\s+день\b",
                                 constraint.value, flags=re.IGNORECASE)
    ))


def _uses_source_true_timing(axis: AssessmentAxis, candidate: str) -> bool:
    excluded = set(assessment_source_timing_exclusions(axis))
    return any(_norm(match.group()) in excluded for match in re.finditer(
        r"\bв\s+(?:первый|следующий)\s+рабочий\s+день\b", candidate, flags=re.IGNORECASE,
    ))


def _has_comparable_option_shape(axis: AssessmentAxis, candidate: str) -> bool:
    """Reject a long statement offered instead of a comparable short category."""
    limit = assessment_option_token_limit(axis)
    if limit is None:
        return True
    candidate_tokens = _ANCHOR_TOKEN.findall(candidate)
    return len(candidate_tokens) <= limit


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
        # An action-only question cannot mark the same source-defined later
        # deadline as false. It may apply under a sibling exception not named
        # by this stem. Prefer an actual action error; do not guess chronology.
        if _uses_source_true_timing(axis, distractor):
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


def _control_responsibility_axes(fact: SourceFact) -> list[tuple[str, str]]:
    projected = project_control_responsibility(_without_source_marker(fact.value))
    return [projected] if projected is not None else []


def _sentence_projection_groups(
    fact: SourceFact, handover_axes: list[tuple[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """Apply grammar precedence to a sentence, never to unrelated siblings."""
    projectors = (
        ("control", _control_responsibility_axes),
        ("scoped", _scoped_modal_axes),
        ("delegated", _delegated_responsibility_axes),
        ("consequence", _explicit_consequence_axes),
        ("training", _instruction_schedule_axes),
        ("shared", _shared_responsibility_axes),
        ("time", _time_qualified_modal_axes),
        ("negative", _conditional_negative_right_axes),
        ("coordinated", _coordinated_conditional_axes),
        ("state", _independent_state_axes),
    )
    groups: dict[str, list[tuple[str, str]]] = {name: [] for name, _project in projectors}
    groups["conditional"] = []
    sentences = _source_sentences(fact.value)
    for sentence in sentences:
        if is_unresolved_procedure_reference(sentence):
            continue
        child = replace(fact, value=sentence)
        for name, project in projectors:
            pairs = project(child)
            if pairs:
                groups[name].extend(pairs)
                break
        else:
            pairs = _conditional_rule_axes(
                child, allow_short=(len(sentences) > 1 or
                                    len(fact.value.strip()) > MAX_ASSESSMENT_ANSWER_CHARS),
            )
            if not _has_same_conditional_target(_without_source_marker(sentence), handover_axes):
                groups["conditional"].extend(pairs)
    return groups


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
    seen: set[tuple[str, str, str, str]] = set()
    source_order = {fact_id: index for index, fact_id in enumerate(lesson.fact_ids)}
    eligible.sort(key=lambda item: (source_order.get(item.fact_id, len(source_order)), item.fact_id))
    for fact in eligible:
        if _norm(fact.attribute) in _AUTO_NARRATIVE_ATTRIBUTES and re.fullmatch(
            r'[^.!?«»“”"]+\?', fact.value.strip(),
        ):
            # A bare FAQ question carries no answer. Explicit source attributes
            # such as "вопрос для знакомства" may legitimately quote a question.
            continue
        reference_axes = [(selection.answer, selection.required_prompt)
                          for selection in project_reference_selections(fact, _source_sentences(fact.value))]
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
        rejection_followup_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else [(step.answer, step.required_prompt) for step in
                  project_rejection_followups(fact, _source_sentences(fact.value))]
        )
        signing_responsibility_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else [(step.answer, step.required_prompt) for step in
                  project_signing_responsibilities(fact, _source_sentences(fact.value))]
        )
        inspection_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else [(projection.step.answer, projection.step.required_prompt) for projection in
                  project_operational_inspections(fact, _source_sentences(fact.value))]
        )
        approval_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else [(projection.step.answer, projection.step.required_prompt) for projection in
                  project_operational_approvals(fact, _source_sentences(fact.value))]
        )
        location_branch_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _flattened_location_branch_axes(fact)
        )
        handover_response_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _handover_response_axes(fact)
        )
        sentence_groups = (
            {} if single_action_axes or structured_axes or regulatory_axes
            else _sentence_projection_groups(fact, handover_response_axes)
        )
        scoped_modal_axes = sentence_groups.get("scoped", [])
        control_responsibility_axes = sentence_groups.get("control", [])
        delegated_responsibility_axes = sentence_groups.get("delegated", [])
        consequence_axes = sentence_groups.get("consequence", [])
        instruction_axes = sentence_groups.get("training", [])
        shared_responsibility_axes = sentence_groups.get("shared", [])
        time_qualified_modal_axes = sentence_groups.get("time", [])
        negative_right_axes = sentence_groups.get("negative", [])
        coordinated_conditional_axes = sentence_groups.get("coordinated", [])
        independent_state_axes = sentence_groups.get("state", [])
        conditional_axes = sentence_groups.get("conditional", [])
        deadline_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _deadline_axes(fact, excluded_sentences=frozenset(
                index for index, sentence in enumerate(_source_sentences(fact.value))
                if (handover_response_axes and _DUAL_LOCATION_RESPONSE_RULE.fullmatch(
                    _without_source_marker(sentence),
                ) is not None) or any(
                    pair in time_qualified_modal_axes for pair in
                    _time_qualified_modal_axes(replace(fact, value=sentence))
                )
            ))
        )
        compound_table_axes = (
            [] if single_action_axes or structured_axes or regulatory_axes
            else _compound_table_operational_axes(fact)
        )
        scoped_conditional_axes = (
            approval_axes
            + handover_response_axes
            + negative_right_axes
            + coordinated_conditional_axes
            + independent_state_axes
            + conditional_axes
        )
        context_owned_axes = (
            reference_axes
            + control_responsibility_axes
            + rejection_followup_axes
            + signing_responsibility_axes
            + inspection_axes
            + approval_axes
            + location_branch_axes
            + handover_response_axes
            + scoped_modal_axes
            + delegated_responsibility_axes
            + consequence_axes
            + instruction_axes
            + shared_responsibility_axes
            + time_qualified_modal_axes
            + negative_right_axes
            + coordinated_conditional_axes
            + independent_state_axes
            + conditional_axes
        )
        projected_axes = (
            control_responsibility_axes
            + rejection_followup_axes
            + signing_responsibility_axes
            + inspection_axes
            + approval_axes
            + location_branch_axes
            + handover_response_axes
            + scoped_modal_axes
            + delegated_responsibility_axes
            + consequence_axes
            + instruction_axes
            + shared_responsibility_axes
            + time_qualified_modal_axes
            + negative_right_axes
            + coordinated_conditional_axes
            + independent_state_axes
            + conditional_axes
            + deadline_axes
            + [
            (value, prompt) for value, prompt in compound_table_axes
            if not _has_same_conditional_target(value, scoped_conditional_axes)
            ]
        )
        if projected_axes and not is_tabular_locator(fact.source_locator):
            # Table projections are the only admitted independently scoped
            # targets. Salience fallback would reintroduce a clause deliberately
            # quarantined above, without its condition/step contract.
            fallback = _source_owned_correct_value(fact)
            fallback_child = replace(fact, value=fallback)
            fallback_projected = _sentence_projection_groups(fallback_child, [])
            already_projected = any(
                pair in projected_axes for pairs in fallback_projected.values() for pair in pairs
            )
            if (
                fallback
                and len(fallback.strip()) <= MAX_ASSESSMENT_ANSWER_CHARS
                and not negative_right_axes
                and not already_projected
                and not _is_dependent_source_fragment(fallback)
                and not _has_same_conditional_target(fallback, scoped_conditional_axes)
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
        source_axes = [*source_axes, *reference_axes]
        for source_value, structured_prompt in source_axes:
            list_pair = ((source_value, structured_prompt) in structured_axes)
            focused_duty = _focused_list_duty(fact, source_value) if list_pair else None
            binary_prohibition = (_simple_list_prohibition_axis(fact, source_value) if list_pair else None)
            binary_obligation = (_simple_list_obligation_axis(fact, source_value) if list_pair else None)
            responsibility = (_long_list_responsibility_axis(fact, source_value) if list_pair else None)
            if (
                not source_value
                or is_unresolved_procedure_reference(source_value)
                or (not structured_prompt and any(is_unresolved_procedure_reference(sentence)
                                                  for sentence in _source_sentences(fact.value)))
                or (not structured_prompt and reference_axes)
                or (len(source_value.strip()) > MAX_ASSESSMENT_ANSWER_CHARS
                    and not binary_prohibition and not binary_obligation and not responsibility)
                or _is_dependent_source_fragment(source_value)
            ):
                continue
            if focused_duty:
                correct_value, required_prompt = focused_duty
            elif binary_prohibition:
                correct_value, required_prompt = binary_prohibition
            elif binary_obligation:
                correct_value, required_prompt = binary_obligation
            elif responsibility:
                correct_value, required_prompt = responsibility
            elif structured_prompt:
                correct_value, required_prompt = source_value, structured_prompt
            else:
                correct_value, required_prompt = _contextualized_list_axis(
                    fact, source_value
                )
            axis_attribute = _axis_attribute(fact, correct_value)
            faq_pair = _source_owned_faq_pair(fact.value)
            required_prompt = (faq_pair[0] if faq_pair else
                               required_prompt or _required_prompt(correct_value))
            if not required_prompt and (placement := _nominal_placement_prohibition(correct_value)):
                required_prompt = placement[0]
            if len(required_prompt) > 900:
                continue
            if not required_prompt and re.search(
                r"^(?:необходимо\b|.+?\bследует\s+(?:обесточить|отключить)\b)",
                correct_value.strip(),
                flags=re.IGNORECASE,
            ):
                appliance_check = re.fullmatch(
                    r"Необходимо\s+обесточить\s+(?P<objects>все\s+электроприборы)\s+и\s+"
                    r"осмотреть\s+на\s+наличие\s+признаков\s+возгорания[.]?",
                    correct_value.strip(), re.IGNORECASE,
                )
                if appliance_check:
                    required_prompt = (
                        f"Какие два действия необходимо выполнить в отношении "
                        f"«{appliance_check['objects']}» согласно разделу "
                        f"«{_without_source_marker(fact.subject).strip()}»?"
                    )
                else:
                    required_prompt = (
                        f"Для «{fact.subject}» в характеристике «{axis_attribute}»: "
                        f"какое действие предусмотрено?"
                    )
            if not required_prompt and is_tabular_locator(fact.source_locator):
                # Keep the source-owned table subject and attribute in the stem;
                # a provider may propose alternatives, not recast a collection as
                # one product inferred from an attribute value or catalog row.
                required_prompt = (
                    f"Что указано в характеристике «{fact.attribute.strip()}» "
                    f"для «{fact.subject.strip()}»?"
                )
            source_context = (
                fact.subject.strip()
                if is_tabular_locator(fact.source_locator)
                and (source_value, structured_prompt) in context_owned_axes else ""
            )
            numbered_scope = ""
            if source_context and (source_value, structured_prompt) in coordinated_conditional_axes:
                resolved_scope = _numbered_action_scope(fact, correct_value)
                if resolved_scope is None:
                    continue
                numbered_scope = resolved_scope
                if numbered_scope:
                    source_context += f"; при условии «{numbered_scope}»"
            normalized_value = _norm(correct_value)
            deadline_scope = (
                _norm(required_prompt)
                if (source_value, structured_prompt) in deadline_axes else ""
            )
            context_scope = (
                _norm(required_prompt)
                if list_pair or (source_value, structured_prompt) in context_owned_axes else ""
            )
            base_identity = (
                _norm(fact.subject),
                _norm(axis_attribute),
                normalized_value,
            )
            identity_scope = deadline_scope or context_scope
            if numbered_scope:
                identity_scope += "|" + _norm(numbered_scope)
            identity = (*base_identity, identity_scope)
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
                ) + ((identity_scope,) if identity_scope else ())).encode("utf-8")
            ).hexdigest()[:20]
            peers = tuple(
                peer.fact_id
                for peer in eligible
                if peer.fact_id != fact.fact_id
                and _norm(peer.attribute) == _norm(fact.attribute)
                and _norm(peer.subject) != _norm(fact.subject)
                and _norm(peer.value) != normalized_value
            )
            if source_context and len(f"Для «{source_context}»: {required_prompt}") > 900:
                continue
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
                axis_kind=(
                    "selection" if (source_value, structured_prompt) in reference_axes else
                    "rule_value"
                    if (source_value, structured_prompt) in (handover_response_axes + coordinated_conditional_axes)
                    and not has_temporal_unit(correct_value)
                    else _axis_kind(axis_attribute, correct_value)
                ),
                distractor_constraints=_distractor_constraints(fact, eligible),
                source_context=source_context,
            ))
    return tuple(result)


def assessment_required_prompt(axis: AssessmentAxis) -> str:
    """Keep explicit operational table applicability in the learner's question."""
    if axis.source_context and axis.required_prompt:
        prefix = f"Для «{axis.source_context}»: "
        return (axis.required_prompt if axis.required_prompt.startswith(prefix)
                else prefix + axis.required_prompt)
    return axis.required_prompt


def assessment_signing_object(axis: AssessmentAxis) -> str | None:
    """Recognize only the complete server-owned signing/action projection."""
    prompt = axis.required_prompt
    prefix = f"Для «{axis.source_context}»: "
    if axis.source_context and prompt.startswith(prefix):
        prompt = prompt[len(prefix):]
    match = re.fullmatch(
        r"Какое действие в отношении «(?P<object>[^«»!?]+)» выполняет «[^«»!?]+» "
        r"при условии «[^«»!?]+»(?: в срок «[^«»!?]+»)?\?", prompt,
    )
    if match and axis.correct_value == "подписывает " + match['object']:
        return match['object']
    return None


def _source_owned_list_decision(axis: AssessmentAxis) -> tuple[str, str] | None:
    """Only a verified complete list proposition grants the predicate opposite."""
    opposites = {"запрещается": "Разрешается", "запрещено": "Разрешается", "нельзя": "Разрешается",
                 "не допускается": "допускается",
                 "должен": "не обязан", "должна": "не обязана", "должно": "не обязано", "должны": "не обязаны",
                 "обязан": "не обязан", "обязана": "не обязана", "обязано": "не обязано", "обязаны": "не обязаны"}
    if _norm(axis.correct_value) not in opposites:
        return None
    for constraint in axis.distractor_constraints:
        if constraint.relation != "same_axis":
            continue
        fact = SourceFact(constraint.fact_id, constraint.subject, constraint.attribute,
                          constraint.value, "doc_id=source-owned-list")
        structured = _explicit_structured_list(fact.value)
        if structured:
            for _position, child in structured[1]:
                for clause in _structured_child_statements(child):
                    if (axis.correct_value, axis.required_prompt) in (
                        _simple_list_prohibition_axis(fact, clause), _simple_list_obligation_axis(fact, clause),
                        _focused_list_duty(fact, clause),
                    ):
                        statement = f"{structured[0]}: {clause.rstrip(';')}"
                        return opposites[_norm(axis.correct_value)], statement
    return None


def _source_owned_appointment_decision(axis: AssessmentAxis) -> tuple[str, str] | None:
    """Negate only the source-verified appointment qualification, not a role guess."""
    if assessment_appointed_control_role(axis):
        return axis.correct_value.replace('назначенное', 'не назначенное', 1), axis.correct_value
    match = re.fullmatch(
        r"лицо,\s+назначенное\s+(?P<authority>"
        r"(?:руководителем|директором|начальником)\s+"
        r"(?:организации|компании|предприятия|подразделения))",
        axis.correct_value, flags=re.IGNORECASE,
    )
    listed_actor = re.fullmatch(
        r"(?P<actor>Ответственные за [^,;:!?]{5,120} сотрудники),\s+"
        r"назначенные приказом (?P<authority>руководителя|директора|начальника) "
        r"(?P<organization>ломбарда|организации|компании|предприятия|подразделения),?",
        axis.correct_value, flags=re.IGNORECASE,
    )
    if match is None and listed_actor is None:
        return None
    for constraint in axis.distractor_constraints:
        if constraint.relation != "same_axis":
            continue
        fact = SourceFact(constraint.fact_id, constraint.subject, constraint.attribute,
                          constraint.value, "doc_id=source-owned-appointment")
        if listed_actor is not None and (structured := _explicit_structured_list(fact.value)):
            for _position, clause in structured[1]:
                if (axis.correct_value, axis.required_prompt) == _long_list_responsibility_axis(fact, clause):
                    inverse = axis.correct_value.replace(", назначенные приказом", ", не назначенные приказом", 1)
                    if inverse != axis.correct_value:
                        return inverse, f"{structured[0]}: {clause}"
        if match is None:
            continue
        for sentence in _source_sentences(fact.value):
            if (axis.correct_value, axis.required_prompt) in _delegated_responsibility_axes(
                replace(fact, value=sentence),
            ):
                return f"лицо, не назначенное {match.group('authority')}", sentence
    return None


def assessment_appointed_control_role(axis: AssessmentAxis) -> bool:
    """Verify a single source-appointed controller, not an arbitrary actor set."""
    if re.fullmatch(
        r"Должностное лицо, назначенное ответственным за [^.!?;:]{5,190}",
        axis.correct_value,
    ) is None or re.search(r"\b(?:и|или|либо|не|кроме|если|когда)\b", axis.correct_value):
        return False
    pair = axis.correct_value, axis.required_prompt
    return any(
        project_control_responsibility(_without_source_marker(sentence)) == pair
        for constraint in axis.distractor_constraints if constraint.relation == 'same_axis'
        for sentence in _source_sentences(constraint.value)
    )


def assessment_appliance_closing_duties(axis: AssessmentAxis) -> bool:
    """Expose the two existing components only for the exact source projection."""
    if axis.correct_value != 'Необходимо обесточить все электроприборы и осмотреть на наличие признаков возгорания.':
        return False
    expected = (
        'Какие два действия необходимо выполнить в отношении «все электроприборы» согласно разделу '
        f'«{_without_source_marker(axis.subject).strip()}»?'
    )
    return axis.required_prompt == expected and any(
        axis.correct_value == _without_source_marker(sentence)
        for constraint in axis.distractor_constraints if constraint.relation == 'same_axis'
        for sentence in _source_sentences(constraint.value)
    )


def assessment_named_value_kind(axis: AssessmentAxis) -> str | None:
    """Verify the server's exact projection before disclosing a name-only task.

    An unmentioned alternative can be a different answer to 'which name does
    this clause specify?', not proof that it is universally illegal/impossible.
    Neither this response type nor the source match decides reviewer truth.
    """
    pair = (axis.correct_value, axis.required_prompt)
    for constraint in axis.distractor_constraints:
        if constraint.relation != "same_axis":
            continue
        fact = SourceFact(constraint.fact_id, constraint.subject, constraint.attribute,
                          constraint.value, "doc_id=source-owned-named-value")
        if pair in _explicit_consequence_axes(fact):
            return "prescribed_consequence"
        if ("форму ответственности прямо" in axis.required_prompt
                and pair in _shared_responsibility_axes(fact)):
            return "stated_liability_form"
        if any(pair == (item.answer, item.required_prompt)
               for item in project_reference_selections(fact, _source_sentences(fact.value))):
            return "referenced_procedure"
        if ("прямо названной проверки" in axis.required_prompt
                and any(pair == (item.step.answer, item.step.required_prompt)
                        for item in project_operational_approvals(fact, _source_sentences(fact.value)))):
            return "inspection_name"
    return None


def assessment_conditioned_signing_source(axis: AssessmentAxis) -> str | None:
    """Prove one adjacent conditional signature action, never arbitrary negation."""
    if re.fullmatch(r"поставить свою подпись (?:в|на) [^.!?;:]{2,160}", axis.correct_value) is None:
        return None
    if re.search(r"\b(?:и|или|либо|кроме|если|когда|затем|до|после|при|только)\b", axis.correct_value):
        return None
    for constraint in axis.distractor_constraints:
        if constraint.relation != "same_axis":
            continue
        sentences = _source_sentences(constraint.value)
        for index, sentence in enumerate(sentences):
            if not index:
                continue
            signature = _DEPENDENT_SIGNATURE_RULE.fullmatch(_without_source_marker(sentence))
            handover = _PARENTHETICAL_MODAL_RULE.fullmatch(_without_source_marker(sentences[index - 1]))
            if (signature is not None and handover is not None
                    and signature.group('answer').strip() == axis.correct_value
                    and _dependent_signature_prompt(handover, signature) == axis.required_prompt):
                return ' '.join(sentences[index - 1:index + 1])
    return None


def _source_owned_conditional_decision(axis: AssessmentAxis) -> tuple[str, str] | None:
    """Oppose a projected record state or one shared duty, never arbitrary text."""
    signature_source = assessment_conditioned_signing_source(axis)
    if signature_source is not None:
        return "не требуется " + axis.correct_value, signature_source
    pair = (axis.correct_value, axis.required_prompt)
    for constraint in axis.distractor_constraints:
        if constraint.relation != "same_axis":
            continue
        fact = SourceFact(constraint.fact_id, constraint.subject, constraint.attribute,
                          constraint.value, "doc_id=source-owned-conditional-decision")
        if (re.fullmatch(r"отметка о согласовании не проставляется[.]?", axis.correct_value, re.IGNORECASE)
                and pair in _conditional_rule_axes(fact, allow_short=True)):
            return axis.correct_value.replace("не проставляется", "проставляется"), fact.value
        # Each shared-modal infinitive inherits the explicit obligation. The
        # liability value is the first projection, never a duty to negate.
        if pair in _shared_responsibility_axes(fact)[1:]:
            return "не требуется " + axis.correct_value, fact.value
    return None


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
    signing_object = assessment_signing_object(axis)
    if signing_object is not None:
        # This projection asks for the signing/mark action; the source actor,
        # applicability and timing already live in its immutable stem. A new
        # prerequisite can be true in another branch, not a false action here.
        object_core = re.split(r"\s+с\s+", signing_object, maxsplit=1)[0]
        distractors = tuple(option for option in distractors
                            if re.search(r"(?<!\w)" + re.escape(_norm(object_core)) + r"(?!\w)", _norm(option))
                            and re.search(r"\bподпис[а-яё]*\b", option, flags=re.IGNORECASE)
                            and not re.search(
                                r"\b(?:если|когда|до|после|пока|только)\b|\bпри\s+условии\b", option,
                                flags=re.IGNORECASE,
                            ))
    source_decision = (_source_owned_list_decision(axis) or _source_owned_appointment_decision(axis)
                       or _source_owned_conditional_decision(axis))
    inverse = _server_owned_inverse(axis.correct_value) or (source_decision[0] if source_decision else None)
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
    if axis.required_prompt:
        prompt = assessment_required_prompt(axis)
    elif _prompt_is_bound_to_axis(authored_prompt, axis):
        prompt = authored_prompt
    else:
        prompt = _server_owned_axis_prompt(axis)
    if inverse is None:
        # A source-true timing is individually identifiable. Remove only this
        # known unsafe extra before the unchanged cross-attribute admission;
        # do not turn arbitrary mixed-source distractors into a passing item.
        distractors = tuple(item for item in distractors if not _uses_source_true_timing(axis, item))
        if len(distractors) < 2:
            return None
        if not axis.source_context and (
            not _admissible_source_distractors(axis, distractors, authored_prompt)
            or not _admissible_source_distractors(axis, distractors, prompt)
        ):
            return None
        # Reject each unsafe alternative without discarding two independently
        # admissible operational alternatives. Generic attribute admission,
        # the minimum and both later model reviews remain unchanged.
        distractors = tuple(item for item in distractors
                            if _admissible_source_distractors(axis, (item,), authored_prompt)
                            and _admissible_source_distractors(axis, (item,), prompt))
        if len(distractors) < 2:
            return None
    explanation = source_decision[1] if source_decision else _teaching_explanation(axis)
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
