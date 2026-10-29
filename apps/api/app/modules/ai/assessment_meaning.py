"""Source-owned negative semantic contracts shared by admission and repair.

These bounded projections never choose an answer key or replace blind review.
Literal source proof and required answer meaning are separate responsibilities.
Unknown grammar retains the ordinary literal/review path, not a guessed pass.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.ai.source_literal import literal_source_span

_FINITE_VERB = r"[а-яё]+(?:ет|ит|ют|ут|ат|ят)(?:ся|сь)?"
_REFERENCE = r"(?:об\s+этом|о\s+нем|о\s+нём|о\s+ней)"
_ACTION = re.compile(
    rf"^(?P<negation>не\s+)?(?P<action>{_FINITE_VERB})\s+"
    rf"(?:(?P<reference>{_REFERENCE})\s+)?(?P<object>.+)$", re.I)
_IN_CITY_SCOPE = re.compile(
    r"в\s+границах\s+населенн|в\s+том\s+же\s+населенн|в\s+городе\s+офиса", re.I)
_NEGATED_IN_CITY_SCOPE = re.compile(
    r"\bне\s+(?:(?:наход\w*|располож\w*|дислоцир\w*)\s+)?"
    r"(?:в\s+границах\s+населенн|в\s+том\s+же\s+населенн|в\s+городе\s+офиса)", re.I)
_OUT_CITY_SCOPE = re.compile(
    r"\bвне\s+границ\s+населенн|\bне\s+(?:(?:наход\w*|располож\w*|дислоцир\w*)\s+)?"
    r"(?:в\s+границах\s+населенн|в\s+том\s+же\s+населенн|в\s+городе\s+офиса)", re.I)
_NUMBERED_BRANCH = re.compile(r"(?<!\w)(?P<number>\d+)\)\s+", re.I)
_SIGNING_SAME_DAY = re.compile(
    r"(?<!\w)(?P<negation>не\s+)?подпис\w*\s+"
    r"(?P<object>[^.!?;\r\n]{2,180}?)\s+в\s+день\s+оформления"
    r"(?:\s+и\s+выдачи\s+микрокредита)?(?=$|[,.!?;])", re.I)
_SIGNING_ACTION = re.compile(
    r"(?<!\w)(?P<negation>не\s+)?подпис\w*\s+"
    r"(?P<object>[^,.!?;\r\n]{2,180}?)(?=$|[,.!?;])", re.I)
_SIGNING_BRANCH = re.compile(
    r"\b(?P<outside>вне)\s+границ\s+населенн|\bв\s+границах\s+населенн", re.I)
_NUMERIC_CATEGORY_COORDINATION = re.compile(
    r"(?<!\w)(?P<first>\d+)\s*-\s*[а-яё]{1,4}\s+"
    r"(?P<connector>или|и)\s+"
    r"(?P<second>\d+)\s*-\s*[а-яё]{1,4}\s+категори[а-яё]*\b",
    re.I,
)
_INFINITIVE = r"[а-яё]{4,}(?:ть|ти|чь)(?:ся|сь)?"
_NEGATIVE_OBLIGATION = re.compile(
    rf"\bне\s+обяз[а-яё]*\s+(?P<actor>[а-яё][а-яё\s-]{{0,100}}?)\s+"
    rf"(?P<action>{_INFINITIVE})\s+(?P<object>[^.!?;]{{2,240}})",
    re.I,
)
_AGREEMENT_OPTION = re.compile(
    r"^да\s*,\s*если\s+(?P<subject>[а-яё][а-яё\s-]{0,100}?)\s+"
    r"соглас(?:ен|на|ны)\s+с\s+(?P<terms>[^.!?;]{2,180})$",
    re.I,
)
_AGREEMENT_SOURCE_BRANCH = re.compile(
    r"\bпри\s+согласии\s+(?P<subject>[а-яё][а-яё\s-]{0,100}?)\s+"
    r"с\s+(?P<terms>[^,.!?;]{2,180}),\s*(?P<outcome>[^.!?;]{2,300})",
    re.I,
)
_WORD = re.compile(r"[а-яё0-9]+", re.I)

# Directional forms observed in source-owned requirements versus grammatical
# answers. This is deliberately a closed list, not suffix similarity or stemming.
_REQUIRED_TO_ANSWER_CASE_ENDINGS = (
    ("ках", "ок"),
    ("ия", "ии"),
    ("ой", "ую"),
    ("ки", "ку"),
    ("шей", "шую"),
    ("ии", "ием"),
    ("ии", "ию"),
    ("иком", "ик"),
)


def _phrase(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _object_prefix_related(candidate: str, proved: str) -> bool:
    """Relate one parsed object to one source object without proving an answer."""
    return (
        candidate == proved
        or candidate.startswith(proved + " ")
        or proved.startswith(candidate + " ")
    )


def _numeric_category_coordinations(value: str) -> list[tuple[tuple[str, str], str]]:
    return [
        ((match["first"], match["second"]), match["connector"].casefold())
        for match in _NUMERIC_CATEGORY_COORDINATION.finditer(value)
    ]


def unsupported_action_or_role_not_excluded(source: str, key: str, alternative: str) -> bool:
    """Hold narrowly recognized alternatives that do not exclude the source duty.

    These are negative-only uncertainty checks, never evidence that an
    alternative is correct or an actor authorized. A different cited passage
    can provide a separate contradiction and is handled by the caller.
    """
    source, key, alternative = map(_phrase, (source, key, alternative))
    if re.search(r"\b(?:не|без|вместо)\b", key):
        return False
    if (re.search(r"\bсообщить\b", key)
            and re.search(r"\bпоставить\s+в\s+известность\b", source)
            and re.match(r"^самостоятельно\s+[а-яе-]+(?:ть|ти|чь)\b", alternative)
            and not re.search(r"\b(?:не|без|вместо|только)\b", alternative)):
        return True
    phone_rule = r"\bсогласован[а-яе]*[^.!?]{0,100}\bпо\s+телефону\b"
    if (re.search(phone_rule, key) and re.search(phone_rule, source)
            and re.match(r"^только\s+устн[а-яе]*\s+(?:разрешен[а-яе]*|согласие)\b", alternative)
            and not re.search(r"\b(?:без|не|вместо)\b", alternative)):
        return True
    return False


def overlapping_reply_obligations(options: Sequence[str]) -> bool:
    """Detect one narrowly equivalent response-duty / no-silence contrast.

    This is a negative-only quality veto. Exact shared context, actor and tail
    are mandatory; it neither establishes source truth nor matches other acts.
    """
    duty = re.compile(r"^(?P<prefix>.+?)\b(?:обязан|должен)\s+(?:ответить|отвечать|(?:дать|давать|предоставить|предоставлять|направить|направлять)\s+ответ)\b(?P<tail>.*)$")
    no_silence = re.compile(r"^(?P<prefix>.+?)\bне\s+(?:вправе|имеет права?)\s+(?:оставить|оставлять)\s+"
                            r"(?P<object>заявление|обращение|запрос)\s+без\s+ответа\b(?P<tail>.*)$")
    normalized = [_phrase(option).rstrip(".!?; ") for option in options]
    for option in normalized:
        required = duty.fullmatch(option)
        if required is None:
            continue
        for other in normalized:
            blocked = no_silence.fullmatch(other)
            if blocked is None:
                continue
            prefix, obj = required["prefix"], blocked["object"]
            root = {"заявление": "заявлен", "обращение": "обращен", "запрос": "запрос"}[obj]
            if (prefix == blocked["prefix"] and len(prefix.strip()) >= 12 and root in prefix
                    and required["tail"].strip() == blocked["tail"].strip()):
                return True
    return False


def parallel_permission_not_excluded(source: str, key: str, alternative: str) -> bool:
    """Conservatively hold distinct actions sharing an exact permission scope.

    The passage must literally contain the whole key. A shared actor, condition
    and positive permission prefix is preserved exactly, but no inference is
    made that the alternative is true. A common citation to a permission alone
    is not enough to prove a different permitted action impossible.
    """
    clause = _phrase(source)
    correct = _phrase(key).rstrip(".!?; ")
    other = _phrase(alternative).rstrip(".!?; ")
    if not correct or correct not in clause or not other or correct == other:
        return False
    for modal in re.finditer(r"(?<!\w)(?:вправе|может|имеет право)(?!\w)", correct):
        before = correct[:modal.start()].rstrip()
        if len(before) < 8 or before.endswith(" не") or before == "не":
            continue
        prefix = correct[:modal.end()]
        if not other.startswith(prefix + " "):
            continue
        correct_action = correct[modal.end():].strip()
        other_action = other[len(prefix):].strip()
        if correct_action and other_action and correct_action != other_action:
            return True
    return False


def source_coordination_issue(source: str, candidate: str) -> str | None:
    """Reject connector changes for an identical ordinal numeric-category pair.

    This is a negative-only check. Unknown grammar or an unmatched pair remains
    with the existing literal and review owners; no connector is inferred.
    """
    source_records = _numeric_category_coordinations(source)
    for pair, candidate_connector in _numeric_category_coordinations(candidate):
        source_connectors = {
            connector for source_pair, connector in source_records if source_pair == pair
        }
        if len(source_connectors) > 1:
            return (
                "ambiguous_numeric_category_coordination: source uses conflicting "
                f"connectors for the {pair[0]}-{pair[1]} category pair"
            )
        if source_connectors and candidate_connector not in source_connectors:
            source_connector = next(iter(source_connectors))
            return (
                "changed_numeric_category_coordination: candidate changes source connector "
                f"'{source_connector}' to '{candidate_connector}' for the "
                f"{pair[0]}-{pair[1]} category pair"
            )
    return None


def _words(value: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(_phrase(value)))


def _common_prefix_length(left: str, right: str) -> int:
    return next(
        (index for index, (a, b) in enumerate(zip(left, right, strict=False)) if a != b),
        min(len(left), len(right)),
    )


def _inflected_words_equal(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if len(left) != len(right) or not left:
        return False
    return all(
        len(a) >= 5
        and len(b) >= 5
        and _common_prefix_length(a, b) >= min(5, len(a), len(b))
        for a, b in zip(left, right, strict=True)
    )


def _word_prefix_related(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    if not left or not right:
        return False
    shorter = min(len(left), len(right))
    return left[:shorter] == right[:shorter]


@dataclass(frozen=True)
class _ObligationContract:
    actor: tuple[str, ...]
    action: str
    object_words: tuple[str, ...]


def _question_outcome(stem: str) -> tuple[str, tuple[str, ...]] | None:
    question = re.search(r"\bобяз[а-яё]*\s+ли\b(?P<body>[^?]{2,400})", _phrase(stem), re.I)
    if question is None:
        return None
    infinitives = list(re.finditer(rf"(?<!\w)(?P<action>{_INFINITIVE})(?!\w)", question["body"], re.I))
    if len(infinitives) != 1:
        return None
    action = infinitives[0]
    object_words = _words(question["body"][action.end():])
    return (action["action"], object_words) if object_words else None


def _owned_negative_obligation(
    sources: Sequence[str],
    action: str,
    object_words: tuple[str, ...],
) -> _ObligationContract | None:
    matches = []
    for source in sources:
        for match in _NEGATIVE_OBLIGATION.finditer(_phrase(source)):
            if match["action"] != action:
                continue
            source_object = _words(match["object"])
            if _word_prefix_related(object_words, source_object):
                matches.append(_ObligationContract(
                    _words(match["actor"]),
                    match["action"],
                    source_object,
                ))
    return matches[0] if len(matches) == 1 and matches[0].actor else None


def _outcome_matches_obligation(outcome: str, contract: _ObligationContract) -> bool:
    tokens = _words(outcome)
    for index, token in enumerate(tokens):
        if _common_prefix_length(token, contract.action) < 5:
            continue
        if not (re.fullmatch(_FINITE_VERB, token, re.I) or re.fullmatch(_INFINITIVE, token, re.I)):
            continue
        if index and tokens[index - 1] == "не":
            continue
        actor = tokens[:index]
        if actor and actor[0] == "то":
            actor = actor[1:]
        if (_inflected_words_equal(actor, contract.actor)
                and _word_prefix_related(tokens[index + 1:], contract.object_words)):
            return True
    return False


def source_conditional_option_issue(
    sources: Sequence[str],
    stem: str,
    key: str,
    options: Sequence[str],
) -> str | None:
    """Reject a false label for one explicit source-owned agreement branch.

    Activation requires an owned negative-obligation rule plus a sibling source
    branch with the same actor, action and object. The typed condition relation
    is limited to ``if <subject> agrees with <terms>`` versus the corresponding
    ``upon agreement of <subject> with <terms>`` form. Unknown grammar is left
    to ordinary literal and review handling.
    """
    normalized_key = _phrase(key)
    if not re.match(r"^нет\b", normalized_key) or not re.search(r"\bне\s+обяз", normalized_key):
        return None
    question_outcome = _question_outcome(stem)
    if question_outcome is None:
        return None
    action, object_words = question_outcome
    contract = _owned_negative_obligation(sources, action, object_words)
    if contract is None:
        return None

    branches = [
        branch
        for source in sources
        for branch in _AGREEMENT_SOURCE_BRANCH.finditer(_phrase(source))
        if _outcome_matches_obligation(branch["outcome"], contract)
    ]
    for option_index, option in enumerate(options):
        if option == key:
            continue
        candidate = _AGREEMENT_OPTION.fullmatch(_phrase(option))
        if candidate is None:
            continue
        for branch in branches:
            if (_inflected_words_equal(_words(candidate["subject"]), _words(branch["subject"]))
                    and _words(candidate["terms"]) == _words(branch["terms"])):
                return (
                    "source_supported_conditional_option: option "
                    f"{option_index} states an explicit sibling source branch"
                )
    return None


@dataclass(frozen=True)
class SourceActionRequirement:
    """A finite predicate, object/modifiers and polarity, proved in one source."""

    source_phrase: str
    action: str
    object_and_modifiers: str
    negative: bool

    def satisfied(self, answer: str) -> bool:
        # Optional anaphoric references point to the already supplied decision;
        # they are not part of action identity. All object/modifier text remains
        # required in order, including systems, units, recipients and conditions.
        action_pattern = re.escape(self.action)
        object_pattern = r"\s+".join(re.escape(p) for p in self.object_and_modifiers.split())
        pattern = re.compile(
            rf"(?<!\w)(?P<negation>не\s+)?{action_pattern}\s+"
            rf"(?:{_REFERENCE}\s+)?{object_pattern}(?!\w)", re.I)
        matches = list(pattern.finditer(_phrase(answer)))
        return bool(matches) and all(bool(match["negation"]) == self.negative for match in matches)


def source_action_requirement(component: str, sources: Sequence[str]) -> SourceActionRequirement | None:
    """Project only a source-proved finite action with explicit polarity."""
    proved = next((value for text in sources
                   if _literal_component_satisfied(component, text)
                   and (value := literal_source_span(component, text, allow_stem=True)) is not None), None)
    if proved is None:
        return None
    parsed = _ACTION.fullmatch(_phrase(proved))
    if parsed is None:
        return None
    return SourceActionRequirement(proved, parsed["action"], parsed["object"], bool(parsed["negation"]))


def _literal_component_satisfied(component: str, answer: str) -> bool:
    """Preserve literal fallback while refusing an opposite or mixed polarity."""
    normalized_component = _phrase(component)
    expected_negative = normalized_component.startswith("не ")
    base = normalized_component[3:] if expected_negative else normalized_component
    if not base:
        return False
    literal = r"\s+".join(re.escape(part) for part in base.split())
    start = r"(?<!\w)(?<!не\s)" if base[0].isalnum() else r"(?<!не\s)"
    end = r"(?!\d)" if base[-1].isdigit() else ""
    matches = list(re.finditer(
        rf"{start}(?P<negation>не\s+)?{literal}{end}",
        _phrase(answer),
        re.I,
    ))
    normalized_answer = _phrase(answer)
    relations = (("не", "за"), ("не", "при"), ("не", "в", "случае"))
    return bool(matches) and all(
        bool(match["negation"]) == expected_negative
        and (
            expected_negative
            or not any(
                _words(normalized_answer[:match.start()])[-len(relation):] == relation
                for relation in relations
            )
        )
        for match in matches
    )


def _unique_positive_source_component(component: str, sources: Sequence[str]) -> bool:
    """Require one exact source-owned occurrence with unchanged polarity."""
    normalized = _phrase(component)
    if not normalized or normalized.startswith("не "):
        return False
    pattern = r"(?<!\w)(?<!не\s)" + r"\s+".join(
        re.escape(part) for part in normalized.split()
    )
    if normalized[-1].isalnum():
        pattern += r"(?!\w)"
    return sum(len(re.findall(pattern, _phrase(source), re.I)) for source in sources) == 1


def _closed_case_word_satisfied(required: str, answer: str) -> bool:
    if required == answer:
        return True
    for required_ending, answer_ending in _REQUIRED_TO_ANSWER_CASE_ENDINGS:
        if not required.endswith(required_ending) or not answer.endswith(answer_ending):
            continue
        required_stem = required[:-len(required_ending)]
        answer_stem = answer[:-len(answer_ending)]
        if len(required_stem) >= 4 and required_stem == answer_stem:
            return True
    return False


def _source_case_owner(
    required_words: tuple[str, ...],
    sources: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    owners: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for source in sources:
        for clause in re.split(r"[.!?;\r\n]+", source):
            clause_words = _words(clause)
            for index in range(len(clause_words) - len(required_words) + 1):
                if clause_words[index:index + len(required_words)] != required_words:
                    continue
                prefix = clause_words[:index]
                if prefix[-1:] == ("не",):
                    continue
                owners.append((prefix, clause_words[index:]))
    return owners[0] if len(owners) == 1 else None


def _source_owned_case_template_satisfied(
    required_words: tuple[str, ...],
    answer_words: tuple[str, ...],
    component_index: int,
    actor_projection: bool,
    sources: Sequence[str],
) -> bool:
    """Bind an inflected span to one closed source/answer proposition template."""
    answer_prefix = answer_words[:component_index]
    if actor_projection:
        return not answer_prefix and len(answer_words) == len(required_words)

    source_owner = _source_case_owner(required_words, sources)
    if source_owner is None:
        return False
    source_prefix, _ = source_owner
    if "не" in source_prefix:
        return False
    if (
        source_prefix[-3:] == ("во", "время", "проведения")
        and answer_prefix == ("во", "время", "проведения")
    ):
        return True
    if source_prefix[-1:] == ("согласно",) and answer_prefix in (
        ("согласно",),
        ("в", "соответствии", "с"),
    ):
        return True
    if (
        source_prefix[-3:] == ("ответственность", "за", "осуществление")
        and answer_prefix == ("за",)
    ):
        return True
    if (
        _contains_words(source_prefix, ("дисциплинарная", "ответственность"))
        and _contains_words(source_prefix, ("тк", "рк"))
        and source_prefix[-3:] == ("а", "также", "согласно")
        and answer_prefix
        in (
            ("дисциплинарная", "ответственность", "в", "соответствии", "с", "тк", "рк", "и"),
            (
                "дисциплинарная", "ответственность", "в", "соответствии", "с",
                "тк", "рк", "а", "также", "согласно",
            ),
        )
    ):
        return True
    source_owns_responsibility = any(
        _contains_words(source_prefix, phrase)
        for phrase in (
            ("принятие", "солидарной", "ответственности"),
            ("принятие", "на", "себя", "солидарной", "ответственности"),
        )
    )
    return (
        source_prefix[-2:] == ("в", "случае")
        and source_owns_responsibility
        and answer_prefix
        == ("принятие", "на", "себя", "солидарной", "ответственности", "при")
    )


def _source_owned_case_projection_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
) -> bool:
    """Accept only enumerated case forms of one literal source component."""
    if not _unique_positive_source_component(component, sources):
        return False
    required_words = _words(component)
    answer_words = _words(answer)
    if not required_words or len(answer_words) < len(required_words):
        return False

    matches: list[int] = []
    for index in range(len(answer_words) - len(required_words) + 1):
        window = answer_words[index:index + len(required_words)]
        if window == required_words:
            continue
        actor_projection = any(
            required.endswith("иком") and candidate.endswith("ик")
            for required, candidate in zip(required_words, window, strict=True)
        )
        if actor_projection and (index != 0 or len(answer_words) != len(required_words)):
            continue
        plural_case_projection = any(
            required.endswith("ках") and candidate.endswith("ок")
            for required, candidate in zip(required_words, window, strict=True)
        )
        if plural_case_projection and (
            len(required_words) < 4 or "или" not in required_words
        ):
            continue
        if all(
            _closed_case_word_satisfied(required, candidate)
            for required, candidate in zip(required_words, window, strict=True)
        ) and _source_owned_case_template_satisfied(
            required_words,
            answer_words,
            index,
            actor_projection,
            sources,
        ):
            matches.append(index)
    return bool(matches)


def _question_line(stem: str) -> str | None:
    candidate = stem.rsplit("\n", 1)[-1].strip()
    if candidate.count("?") != 1 or not candidate.endswith("?"):
        return None
    return _phrase(candidate[:-1])


def _source_clauses(sources: Sequence[str]) -> list[str]:
    return [
        _phrase(clause)
        for source in sources
        for clause in re.split(r"[.!?;\r\n]+", source)
        if clause.strip()
    ]


def _contains_words(haystack: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    return bool(needle) and any(
        haystack[index:index + len(needle)] == needle
        for index in range(len(haystack) - len(needle) + 1)
    )


_PHONE_APPROVAL_PREDICATE = re.compile(
    r"(?<!не\s)должн[а-яё]*\s+быть\s+предварительно\s+согласов[а-яё]*\s+по\s+телефону\b",
    re.I,
)


def _closed_condition_answer_matches_source(
    answer_words: tuple[str, ...],
    source_words: tuple[str, ...],
    question_words: tuple[str, ...],
) -> bool:
    """Allow exact source condition or one repeated source referent omitted."""
    if answer_words == source_words:
        return True
    if len(source_words) != len(answer_words) + 1:
        return False
    for index in range(2, len(source_words) - 1):
        if source_words[:index] + source_words[index + 1:] != answer_words:
            continue
        if source_words[index] not in question_words:
            continue
        if re.fullmatch(_FINITE_VERB, source_words[index + 1], re.I) is not None:
            return True
    return False


def _out_city_location_signature(value: str) -> tuple[str, ...] | None:
    """Normalize only the optional relational filler in one out-city scope."""
    words = _words(value)
    required_scope = ("вне", "границ", "населенного", "пункта")
    if words[:2] != ("при", "дислокации"):
        return None
    indexes = [
        index
        for index in range(len(words) - len(required_scope) + 1)
        if words[index:index + len(required_scope)] == required_scope
    ]
    if len(indexes) != 1:
        return None
    scope_end = indexes[0] + len(required_scope)
    if scope_end >= len(words):
        return None
    normalized = list(words)
    if normalized[scope_end:scope_end + 2] == ["нахождения", "офиса"]:
        del normalized[scope_end]
    if normalized[scope_end] != "офиса" or scope_end == 2:
        return None
    return tuple(normalized)


def _source_owned_phone_actor_owners(
    question: str,
    sources: Sequence[str],
) -> list[tuple[str, ...]]:
    """Select actor owners through one complete phone/category/location proposition."""
    parsed_question = re.fullmatch(
        r"кто\s+предварительно\s+(?P<negation>не\s+)?согласов[а-яё]*\s+"
        r"по\s+телефону\s+(?P<object>[а-яё-]+)\s+(?:по\s+)?"
        r"(?P<category>[ivxlcdm]+)\s+категори[а-яё]*\s+"
        r"(?P<location>при\s+дислокации.+)",
        question,
        re.I,
    )
    if parsed_question is None or parsed_question["negation"]:
        return []
    question_location = _out_city_location_signature(parsed_question["location"])
    if question_location is None:
        return []

    owners: list[tuple[str, ...]] = []
    for clause in _source_clauses(sources):
        parsed_source = re.search(
            r"(?<!\w)(?P<object>[а-яё-]+)\s+по\s+"
            r"(?P<category>[ivxlcdm]+)\s+категори[а-яё]*\s+"
            r"(?P<location>при\s+дислокации.+?)\s+предварительно\s+"
            r"(?P<negation>не\s+)?согласов[а-яё]*\s+"
            r"(?P<actor>[а-яё-]+)\s+по\s+телефону\b",
            clause,
            re.I,
        )
        if parsed_source is None or parsed_source["negation"]:
            continue
        if _phrase(parsed_source["object"]) != _phrase(parsed_question["object"]):
            continue
        if parsed_source["category"].casefold() != parsed_question["category"].casefold():
            continue
        if _out_city_location_signature(parsed_source["location"]) != question_location:
            continue
        owners.append(_words(parsed_source["actor"]))
    return owners


def _source_owned_phone_actor_case_projection(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool | None:
    """Own a case projection through the closed Who/phone/location question."""
    component_words = _words(component)
    answer_words = _words(answer)
    if (
        not component_words
        or len(component_words) != len(answer_words)
        or component_words == answer_words
        or not all(
            _closed_case_word_satisfied(required, candidate)
            for required, candidate in zip(component_words, answer_words, strict=True)
        )
    ):
        return None
    question = _question_line(stem)
    if question is None or re.match(r"^кто\b", question, re.I) is None:
        return None
    if "по телефону" not in question or "при дислокации" not in question:
        return None
    owners = _source_owned_phone_actor_owners(question, sources)
    return len(owners) == 1 and owners[0] == component_words


def _source_owned_condition_method_ellipsis_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Allow one closed condition question to state its telephone method."""
    if _phrase(component) != "по телефону":
        return False
    question = _question_line(stem)
    if question is None:
        return False
    if re.match(r"^кто\b", question, re.I):
        answer_words = _words(answer)
        owners = _source_owned_phone_actor_owners(question, sources)
        return (
            len(owners) == 1
            and len(owners[0]) == len(answer_words)
            and owners[0] != answer_words
            and all(
                _closed_case_word_satisfied(required, candidate)
                for required, candidate in zip(owners[0], answer_words, strict=True)
            )
        )
    if not re.match(r"^при\s+как(?:ом|их)\s+услов(?:ии|иях)\b", question, re.I):
        return False
    question_predicate = _PHONE_APPROVAL_PREDICATE.search(question)
    if (
        question_predicate is None
        or question_predicate.end() != len(question)
        or _phrase(answer) in question
    ):
        return False

    answer_words = _words(answer)
    if not answer_words or answer_words[0] != "если" or "после" not in answer_words:
        return False
    condition_owners: list[str] = []
    for clause in _source_clauses(sources):
        if _PHONE_APPROVAL_PREDICATE.search(clause) is None:
            continue
        clause_words = _words(clause)
        if "если" not in clause_words or "после" not in clause_words or "то" not in clause_words:
            continue
        condition_index = clause_words.index("если")
        boundary_index = clause_words.index("то", condition_index)
        source_condition = clause_words[condition_index:boundary_index]
        if (
            "после" in source_condition
            and _closed_condition_answer_matches_source(
                answer_words,
                source_condition,
                _words(question),
            )
        ):
            condition_owners.append(clause)
    return len(condition_owners) == 1


_DATIVE_TO_GENITIVE_OBJECT_ENDINGS = (
    ("ому", "ого"),
    ("ему", "его"),
    ("у", "а"),
    ("ю", "я"),
)


def _closed_dative_to_genitive_object(
    source_object: tuple[str, ...],
    question_object: tuple[str, ...],
) -> bool:
    if source_object == question_object:
        return True
    if len(source_object) != len(question_object) or len(source_object) < 2:
        return False
    for source_word, question_word in zip(source_object, question_object, strict=True):
        if source_word == question_word:
            continue
        if not any(
            source_word.endswith(source_ending)
            and question_word.endswith(question_ending)
            and len(source_word) > len(source_ending) + 3
            and source_word[:-len(source_ending)] == question_word[:-len(question_ending)]
            for source_ending, question_ending in _DATIVE_TO_GENITIVE_OBJECT_ENDINGS
        ):
            return False
    return True


def _prohibition_actor_matches(
    source_actor: tuple[str, ...],
    question_actor: tuple[str, ...],
) -> bool:
    if len(source_actor) != len(question_actor):
        return False
    for source_word, question_word in zip(source_actor, question_actor, strict=True):
        if source_word == question_word:
            continue
        if source_word[-1:].isalnum() and question_word == source_word + "у":
            continue
        if source_word.endswith("ам") and question_word == source_word[:-2] + "у":
            continue
        return False
    return True


def _source_owned_prohibition_condition_ellipsis_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Allow one negative if-guard fixed in its complete prohibition question."""
    normalized_component = _phrase(component)
    if not normalized_component.startswith("не "):
        return False
    question = _question_line(stem)
    if question is None:
        return False
    parsed_question = re.fullmatch(
        r"что\s+(?:категорически\s+)?запрещается\s+"
        r"(?P<actor>[а-яё-]+)\s+(?:по|в\s+отношении)\s+"
        r"(?P<object>[^,]+),\s+(?:в\s+случае\s+)?если\s+"
        r"(?P<subject>[а-яё-]+)\s+(?P<condition>.+)",
        question,
        re.I,
    )
    if (
        parsed_question is None
        or _phrase(parsed_question["condition"]) != normalized_component
    ):
        return False

    normalized_answer = _phrase(answer)
    owners = []
    source_pattern = re.compile(
        rf"(?P<actor>[а-яё-]+)\s+(?:категорически\s+)?запрещается\s+"
        rf"(?P<answer>.+?),\s+(?:в\s+случае\s+)?если\s+"
        rf"(?P<subject>[а-яё-]+)\s+{re.escape(normalized_component)}$",
        re.I,
    )
    for clause in _source_clauses(sources):
        parsed_source = source_pattern.fullmatch(clause)
        if parsed_source is None or _phrase(parsed_source["answer"]) != normalized_answer:
            continue
        if _phrase(parsed_source["subject"]) != _phrase(parsed_question["subject"]):
            continue
        if not _prohibition_actor_matches(
            _words(parsed_source["actor"]),
            _words(parsed_question["actor"]),
        ):
            continue
        answer_parts = re.fullmatch(
            rf"(?P<action>{_INFINITIVE}(?:\s+[а-яё-]+){{1,4}})\s+"
            r"по\s+(?P<object>[а-яё-]+(?:\s+[а-яё-]+)*)",
            normalized_answer,
            re.I,
        )
        if answer_parts is None or not _closed_dative_to_genitive_object(
            _words(answer_parts["object"]),
            _words(parsed_question["object"]),
        ):
            continue
        owners.append(clause)
    return len(owners) == 1


def _source_owned_prohibition_ellipsis_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Allow ``Что запрещается?`` to supply only the prohibition predicate."""
    parsed = re.fullmatch(
        r"(?:категорически\s+)?запрещается\s+(?P<action>.+)",
        _phrase(component),
        re.I,
    )
    if parsed is None or not _unique_positive_source_component(component, sources):
        return False
    question = _question_line(stem)
    if question is None or re.match(
        r"^что\s+(?:категорически\s+)?запрещается\b",
        question,
        re.I,
    ) is None:
        return False
    source_contracts = [
        (_words(match["actor"]), _words(match["proposition"]))
        for clause in _source_clauses(sources)
        if (match := re.search(
            r"(?<!\w)(?P<actor>[а-яё-]+)\s+(?:категорически\s+)?"
            rf"запрещается\s+(?P<proposition>{re.escape(parsed['action'])}"
            r"(?:\s+.+)?)$",
            clause,
            re.I,
        )) is not None
    ]
    question_actor = re.match(
        r"^что\s+(?:категорически\s+)?запрещается\s+(?P<actor>[а-яё-]+)\b",
        question,
        re.I,
    )
    if len(source_contracts) != 1 or question_actor is None:
        return False
    candidate_actor = _words(question_actor["actor"])
    source_actor, source_proposition = source_contracts[0]
    if not _prohibition_actor_matches(source_actor, candidate_actor):
        return False
    action = parsed["action"]
    if re.search(rf"(?<!\w){re.escape(action)}(?!\w)", question, re.I):
        return False
    answer_words = _words(answer)

    def split_guard(words: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...] | None]:
        if words.count("если") > 1:
            return words, None
        if "если" not in words:
            return words, None
        condition_index = words.index("если")
        base_end = condition_index
        if words[max(0, condition_index - 2):condition_index] == ("в", "случае"):
            base_end -= 2
        return words[:base_end], words[condition_index + 1:]

    source_base, source_condition = split_guard(source_proposition)
    answer_base, answer_condition = split_guard(answer_words)
    if source_condition is None or answer_base != source_base:
        return source_condition is None and answer_words == source_proposition
    if answer_condition is not None:
        return answer_condition == source_condition
    _, question_condition = split_guard(_words(question))
    return question_condition == source_condition


def _closed_responsibility_reference_owned(
    question_reference: tuple[str, ...],
    source_clause: str,
) -> bool:
    """Match the optional contract reference with one closed case rewrite."""
    if not question_reference:
        return True
    reference = question_reference[1:]
    source_words = _words(source_clause)
    return any(
        all(
            source_word == question_word
            or (source_word == "договора" and question_word == "договору")
            for source_word, question_word in zip(window, reference, strict=True)
        )
        for window in (
            source_words[index:index + len(reference)]
            for index in range(len(source_words) - len(reference) + 1)
        )
    )


def _closed_responsibility_cause_shapes(
    source_clause: str,
    owned_predicate: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    """Return only explicitly closed full-cause omissions owned by the source."""
    predicate = r"\s+".join(re.escape(word) for word in owned_predicate)
    matched = re.search(
        rf"(?<!\w){predicate}\s+за\s+(?P<cause>.+?)"
        rf"(?=,\s+а\s+также\b|[.!?](?:\s|$)|$)",
        _phrase(source_clause),
        re.I,
    )
    if matched is None:
        return ()
    cause = matched["cause"]
    raw_shapes = [cause]
    without_parenthetical = re.sub(r"\s*\([^()]*\)", "", cause)
    if without_parenthetical != cause:
        raw_shapes.append(without_parenthetical)
    without_examples = re.sub(
        r",\s*в\s+том\s+числе\s+.+?,\s*(?=причинивш[а-яё]*\b)",
        " ",
        without_parenthetical,
        count=1,
        flags=re.I,
    )
    if without_examples != without_parenthetical:
        raw_shapes.append(without_examples)
    shapes: list[tuple[str, ...]] = []
    for raw_shape in raw_shapes:
        shape = _words(raw_shape)
        if shape and shape not in shapes:
            shapes.append(shape)
        if shape[:1] == ("осуществление",) and shape[1:] not in shapes:
            shapes.append(shape[1:])
    return tuple(shapes)


def _source_owned_responsibility_ellipsis_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Allow ``За что ... несут ответственность?`` to supply its predicate."""
    component_words = _words(component)
    if component_words != ("солидарную", "ответственность"):
        return False
    if not _unique_positive_source_component(component, sources):
        return False
    question = _question_line(stem)
    if question is None:
        return False
    parsed = re.fullmatch(
        r"^за\s+что\s+(?P<actor>.+?)\s+несут\s+"
        r"солидарную(?P<modifier>\s+материальную)?\s+ответственность"
        r"(?P<reference>\s+(?:согласно|по)\s+договору\s+о\s+полной\s+коллективной"
        r"(?:\s+\(солидарной\))?\s+материальной\s+ответственности)?",
        question,
        re.I,
    )
    if parsed is None:
        return False
    actor_words = _words(parsed["actor"])
    if not actor_words or actor_words[-1] == "не":
        return False
    owned_predicate = actor_words + ("несут",) + component_words
    owners: list[tuple[str, tuple[str, ...]]] = []
    for clause in _source_clauses(sources):
        clause_words = _words(clause)
        predicate_indexes = [
            index
            for index in range(len(clause_words) - len(owned_predicate) + 1)
            if clause_words[index:index + len(owned_predicate)] == owned_predicate
        ]
        if len(predicate_indexes) == 1:
            owners.append((clause, clause_words[predicate_indexes[0] + len(owned_predicate):]))
    if parsed["modifier"] and not all(
        re.search(r"(?<!\w)материальн[а-яё]*(?!\w)", owner, re.I)
        for owner, _ in owners
    ):
        return False
    answer_words = _words(answer)
    if len(owners) != 1 or answer_words[:1] != ("за",):
        return False
    question_reference = _words(parsed["reference"] or "")
    if not _closed_responsibility_reference_owned(
        question_reference,
        owners[0][0],
    ):
        return False
    answer_cause = answer_words[1:]
    source_shapes: tuple[tuple[str, ...], ...] = _closed_responsibility_cause_shapes(
        owners[0][0],
        owned_predicate,
    )
    return bool(answer_cause) and any(
        len(source_shape) == len(answer_cause)
        and all(
            _closed_case_word_satisfied(required, candidate)
            for required, candidate in zip(source_shape, answer_cause, strict=True)
        )
        for source_shape in source_shapes
    )


def _voice_stem(word: str, endings: tuple[str, ...]) -> str | None:
    return next(
        (word[:-len(ending)] for ending in endings if word.endswith(ending)),
        None,
    )


def _instrumental_actor_projects_to_nominative(
    instrumental: tuple[str, ...],
    nominative: tuple[str, ...],
) -> bool:
    if len(instrumental) != len(nominative) or not instrumental:
        return False
    for index, (source_word, answer_word) in enumerate(zip(instrumental, nominative, strict=True)):
        if index < len(instrumental) - 1:
            if source_word.endswith("ым") and answer_word == source_word[:-2] + "ый":
                continue
            if source_word.endswith("им") and answer_word == source_word[:-2] + "ий":
                continue
            return False
        if source_word.endswith("ом") and answer_word == source_word[:-2]:
            continue
        return False
    return True


def _source_owned_actor_projection_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Project one closed passive instrumental actor into a ``Кто?`` answer."""
    instrumental = _words(component)
    if not _instrumental_actor_projects_to_nominative(instrumental, _words(answer)):
        return False

    questions = list(re.finditer(r"(?<!\w)кто\b(?P<body>[^?]{2,600})\?", _phrase(stem), re.I))
    if len(questions) != 1:
        return False
    question_words = _words(questions[0]["body"])

    source_contracts: list[tuple[str, tuple[str, ...]]] = []
    for source in sources:
        for sentence_match in re.finditer(r"[^.!?;\r\n]+", _phrase(source)):
            sentence_words = _words(sentence_match.group(0))
            if (
                len(sentence_words) <= len(instrumental)
                or sentence_words[-len(instrumental):] != instrumental
            ):
                continue
            passive = sentence_words[-len(instrumental) - 1]
            passive_stem = _voice_stem(passive, ("ются", "ется", "ятся", "ится", "атся"))
            if passive_stem is None:
                continue
            source_head = sentence_words[:-len(instrumental) - 1]
            if not source_head or source_head[-1:] == ("не",):
                continue
            source_contracts.append((passive_stem, source_head))
    if len(source_contracts) != 1:
        return False

    passive_stem, source_head = source_contracts[0]
    active_indexes = [
        index
        for index, word in enumerate(question_words)
        if _voice_stem(word, ("ет", "ит")) == passive_stem
    ]
    if len(active_indexes) != 1:
        return False
    action_index = active_indexes[0]
    modifiers = question_words[:action_index]
    object_words = question_words[action_index + 1:]
    if not object_words or "не" in modifiers:
        return False
    return source_head == object_words + modifiers


def _source_owned_stop_work_proposition(
    component: str,
    sources: Sequence[str],
) -> tuple[str, ...] | None:
    component_words = _words(component)
    if component_words != ("прекратить", "все", "работы"):
        return None

    propositions: list[tuple[str, ...]] = []
    for source in sources:
        for sentence_match in re.finditer(r"[^.!?;\r\n]+", _phrase(source)):
            sentence_words = _words(sentence_match.group(0))
            for index in range(len(sentence_words) - len(component_words) + 1):
                if sentence_words[index:index + len(component_words)] != component_words:
                    continue
                if index and sentence_words[index - 1] == "не":
                    continue
                proposition = sentence_words[index:]
                try:
                    exception_index = proposition.index("кроме")
                except ValueError:
                    continue
                if exception_index <= len(component_words) or exception_index == len(proposition) - 1:
                    continue
                propositions.append(proposition)
    return propositions[0] if len(propositions) == 1 else None


def _source_owned_stop_work_voice_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
) -> bool:
    """Accept only the closed source-owned stop-all-work passive rendering."""
    proposition = _source_owned_stop_work_proposition(component, sources)
    if proposition is None:
        return False

    answer_words = _words(answer)
    return (
        bool(answer_words)
        and answer_words[0] == "прекращаются"
        and answer_words[1:] == proposition[1:]
    )


def _source_owned_stop_work_ellipsis_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    stem: str,
) -> bool:
    """Allow only a matching interrogative to supply the closed stop predicate."""
    proposition = _source_owned_stop_work_proposition(component, sources)
    if proposition is None:
        return False
    exception_index = proposition.index("кроме")
    scope_words = proposition[3:exception_index]
    answer_words = _words(answer)
    if answer_words not in (
        proposition[1:],
        proposition[1:3] + proposition[exception_index:],
    ):
        return False

    questions = list(re.finditer(
        r"(?<!\w)какие\s+работы\b(?P<body>[^?]{2,500})\?",
        _phrase(stem),
        re.I,
    ))
    if len(questions) != 1:
        return False
    question_words = ("какие", "работы") + _words(questions[0]["body"])
    action_indexes = [
        index for index, word in enumerate(question_words) if word == "прекращаются"
    ]
    if len(action_indexes) != 1:
        return False
    action_index = action_indexes[0]
    if action_index and question_words[action_index - 1] == "не":
        return False
    if "исключение" not in question_words[action_index + 1:]:
        return False
    return any(
        question_words[index:index + len(scope_words)] == scope_words
        for index in range(len(question_words) - len(scope_words) + 1)
    )


def answer_component_satisfied(
    component: str,
    answer: str,
    sources: Sequence[str],
    *,
    stem: str = "",
) -> bool:
    """Check one required answer component without inventing source meaning.

    ``stem`` is optional for compatibility. Only the closed source-owned actor
    and stop-work ellipsis contracts use it; declarative preambles never satisfy
    a component by themselves.
    """
    contract = source_action_requirement(component, sources)
    if contract is not None:
        if contract.satisfied(answer):
            return True
    elif _literal_component_satisfied(component, answer):
        return True
    phone_actor_projection = _source_owned_phone_actor_case_projection(
        component,
        answer,
        sources,
        stem,
    )
    if phone_actor_projection is not None:
        return phone_actor_projection
    if _source_owned_case_projection_satisfied(component, answer, sources):
        return True
    if _source_owned_condition_method_ellipsis_satisfied(component, answer, sources, stem):
        return True
    if _source_owned_prohibition_condition_ellipsis_satisfied(
        component,
        answer,
        sources,
        stem,
    ):
        return True
    if _source_owned_prohibition_ellipsis_satisfied(component, answer, sources, stem):
        return True
    if _source_owned_responsibility_ellipsis_satisfied(component, answer, sources, stem):
        return True
    if _source_owned_stop_work_voice_satisfied(component, answer, sources):
        return True
    if _source_owned_stop_work_ellipsis_satisfied(component, answer, sources, stem):
        return True
    return _source_owned_actor_projection_satisfied(component, answer, sources, stem)


def source_branch_issue(
    source: str, quote: str, stem: str, visible_options: Sequence[str] = (),
) -> str | None:
    """Require an exact quote's explicit numbered geographic parent branch.

    The supported quote selects the proposition; this seam never chooses a key.
    Only one literal occurrence and one recognizable geographic branch can own
    the proposition. Unknown or duplicated conditional ownership stays review-
    required instead of borrowing a convenient scope from elsewhere.
    """
    if not quote:
        return "ambiguous_conditional_ownership: supported quote is empty"
    occurrences = []
    start = 0
    while (position := source.find(quote, start)) >= 0:
        occurrences.append(position)
        start = position + 1
    if len(occurrences) != 1:
        return "ambiguous_conditional_ownership: supported quote is not uniquely owned by source"

    quote_start = occurrences[0]
    quote_end = quote_start + len(quote)
    markers = list(_NUMBERED_BRANCH.finditer(source))
    owner_index = next(
        (index for index in range(len(markers) - 1, -1, -1)
         if markers[index].start() <= quote_start),
        None,
    )
    if owner_index is None:
        return None
    owner = markers[owner_index]
    branch_end = markers[owner_index + 1].start() if owner_index + 1 < len(markers) else len(source)
    branch = source[owner.start():branch_end]
    source_in_city = bool(_IN_CITY_SCOPE.search(branch) and not _NEGATED_IN_CITY_SCOPE.search(branch))
    source_out_city = bool(_OUT_CITY_SCOPE.search(branch))
    if not source_in_city and not source_out_city:
        return None
    if quote_end > branch_end:
        return "ambiguous_conditional_ownership: supported quote crosses a numbered sibling boundary"
    if source_in_city and source_out_city:
        return "ambiguous_conditional_ownership: parent branch contains contrary geographic scopes"

    stem_in_city = bool(_IN_CITY_SCOPE.search(stem) and not _NEGATED_IN_CITY_SCOPE.search(stem))
    stem_out_city = bool(_OUT_CITY_SCOPE.search(stem))
    if not stem_in_city and not stem_out_city and len(visible_options) >= 2:
        # An identical source-owned prefix in EVERY option is learner-visible
        # applicability, not a key cue. Require the whole branch selector and
        # an owned common prefix, never merely matching geographic keywords.
        prefix = source[owner.end():quote_start].strip()
        selector = re.split(r"\s[-–—]\s", prefix, maxsplit=1)[0].strip()
        words = [option.split() for option in visible_options]
        common: list[str] = []
        for column in zip(*words, strict=False):
            if len({word.casefold() for word in column}) != 1:
                break
            common.append(column[0])
        shared = " ".join(common)
        if (selector and literal_source_span(selector, shared) is not None
                and literal_source_span(shared, branch) is not None
                and all(
                    bool(_IN_CITY_SCOPE.search(option) and not _NEGATED_IN_CITY_SCOPE.search(option)) == source_in_city
                    and bool(_OUT_CITY_SCOPE.search(option)) == source_out_city
                    for option in visible_options
                )):
            stem_in_city, stem_out_city = source_in_city, source_out_city
    if stem_in_city and stem_out_city:
        return "ambiguous_geographic_branch: question states contrary geographic scopes"
    if source_in_city:
        if stem_out_city:
            return "contrary_geographic_branch: source proposition belongs to the in-city branch"
        if not stem_in_city:
            return "missing_geographic_branch: source proposition belongs to the in-city branch"
    elif stem_in_city:
        return "contrary_geographic_branch: source proposition belongs to the out-of-city branch"
    elif not stem_out_city:
        return "missing_geographic_branch: source proposition belongs to the out-of-city branch"
    return None


@dataclass(frozen=True)
class SigningScopeContract:
    """Same-day signing with source-owned location and out-of-hours branches."""

    source: str
    in_city_required: bool
    normal_hours_cutoff: str | None

    def rejection(self, stem: str) -> str | None:
        positive_in_city = bool(_IN_CITY_SCOPE.search(stem) and not _NEGATED_IN_CITY_SCOPE.search(stem))
        if self.in_city_required and not positive_in_city:
            return ("missing_geographic_branch: same-day signing belongs to the in-city branch; "
                    "state its source-owned location scope")
        if self.normal_hours_cutoff is not None:
            cutoff = tuple(map(int, self.normal_hours_cutoff.split(":")))
            times = [tuple(map(int, match.groups())) for match in re.finditer(
                r"(?:до|не\s+позднее)\s+(\d{1,2}):(\d{2})", stem, re.I)]
            if not re.search(r"в\s+рабочий\s+день", stem, re.I) or not any(t <= cutoff for t in times):
                return ("missing_schedule_exception_scope: same-day signing has an out-of-hours "
                        "first-working-day exception; state the normal working-day/time scope explicitly "
                        "or test the exception itself")
        return None


def source_signing_scope(source: str, stem: str, key: str) -> SigningScopeContract | None:
    """Project one same-day signing action and only its connected source branch."""
    normalized_key, normalized_stem, normalized_source = map(_phrase, (key, stem, source))
    candidate = _SIGNING_SAME_DAY.search(normalized_key)
    if candidate is None and re.search(r"в\s+день\s+оформления", normalized_key):
        candidate = _SIGNING_ACTION.search(normalized_stem)
    if candidate is None or candidate["negation"]:
        return None
    object_and_modifiers = candidate["object"].strip().rstrip(" ,")
    source_matches = [
        match for match in _SIGNING_SAME_DAY.finditer(normalized_source)
        if not match["negation"]
        and _object_prefix_related(
            object_and_modifiers,
            match["object"].strip().rstrip(" ,"),
        )
    ]
    if len(source_matches) != 1:
        return None
    source_match = source_matches[0]

    branches = list(_SIGNING_BRANCH.finditer(normalized_source))
    previous = next((marker for marker in reversed(branches) if marker.start() < source_match.start()), None)
    following = next((marker for marker in branches if marker.start() > source_match.start()), None)
    if previous is None:
        branch_start = normalized_source.rfind(".", 0, source_match.start()) + 1
        in_city = False
    else:
        branch_start = previous.start()
        in_city = previous["outside"] is None
    branch_end = min(
        following.start() if following is not None else len(normalized_source),
        branch_start + 2500,
    )
    next_same_day = next(
        (match for match in _SIGNING_SAME_DAY.finditer(normalized_source, source_match.end())
         if match.start() < branch_end),
        None,
    )
    if next_same_day is not None:
        branch_end = next_same_day.start()
    branch = normalized_source[branch_start:branch_end]
    after = re.search(r"после\s+(\d{1,2}:\d{2})", branch, re.I)
    cutoff = after[1] if after and re.search(r"первый\s+рабочий\s+день", branch, re.I) else None
    if not in_city and cutoff is None:
        return None
    return SigningScopeContract(source_match.group(0), in_city, cutoff)


def _owned_instruction_timing(
    value: str,
    *,
    correct_timing: str,
    source_actor: str,
    activity_marker: str,
) -> str | None:
    normalized = _phrase(value).rstrip(".")
    if normalized == correct_timing:
        return normalized
    if normalized.count(activity_marker) != 1:
        return None
    actor, projected_timing = normalized.split(activity_marker, 1)
    if not actor or not (actor == source_actor or source_actor.startswith(actor + " ")):
        return None
    return projected_timing or None


_MINIMUM_INTERVAL_QUESTION = re.compile(
    r"\bминимальн(?:ый|ого|ому|ым|ом)\s+"
    r"(?:срок(?:а|у|ом|е)?|интервал(?:а|у|ом|е)?|период(?:а|у|ом|е)?)\b",
    re.I,
)


def _final_stem_line(stem: str) -> str | None:
    candidate = stem.strip().rsplit("\n", 1)[-1].strip()
    return _phrase(candidate) if candidate else None


def _minimum_frequency_stem_issue(stem: str) -> str | None:
    final_line = _final_stem_line(stem)
    if final_line is None or _MINIMUM_INTERVAL_QUESTION.search(final_line) is None:
        return None
    return (
        "instruction_schedule_minimum_frequency_asked_as_minimum_interval: "
        "rewrite the stem to ask for minimum frequency ('минимальная периодичность'), "
        "not a minimum срок/период/интервал"
    )


def instruction_option_issue(
    source: str,
    key: str,
    options: Sequence[str],
    *,
    stem: str = "",
) -> str | None:
    """Reuse the exact legacy producer and its negative-only timing predicate."""
    from app.modules.ai.evidence_engine.assessment_axes import source_instruction_schedule_contracts
    from app.modules.ai.evidence_engine.models import SourceFact
    from app.modules.ai.evidence_engine.operational_schedule import (
        MINIMUM_FREQUENCY_LITERAL,
        instruction_schedule_option_rejection,
    )

    fact = SourceFact("source-owned", "", "", source, "source-owned-cycle")
    for contract in source_instruction_schedule_contracts(fact):
        correct_timing = _phrase(contract.correct_value).rstrip(".")
        source_actor = _phrase(contract.actor)
        activity_marker = " проходят " + _phrase(contract.activity) + " "
        if _owned_instruction_timing(
            key,
            correct_timing=correct_timing,
            source_actor=source_actor,
            activity_marker=activity_marker,
        ) != correct_timing:
            continue
        if (
            contract.kind == MINIMUM_FREQUENCY_LITERAL
            and (stem_issue := _minimum_frequency_stem_issue(stem))
        ):
            return stem_issue
        for option in options:
            option_timing = _owned_instruction_timing(
                option,
                correct_timing=correct_timing,
                source_actor=source_actor,
                activity_marker=activity_marker,
            )
            checked_option = option_timing if option_timing is not None else option
            if (option != key
                    and (issue := instruction_schedule_option_rejection(contract, checked_option))):
                return issue + ": a supposedly false option also satisfies the source-owned instruction rule"
    return None
