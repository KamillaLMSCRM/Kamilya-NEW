"""Negative-only critical-boundary candidate for mapped assessment components.

The caller owns comparison-mode and source/role custody.  This module never
selects a key, creates a role, or authorizes admission.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Literal

from app.modules.ai.assessment_preservation import _morph, _word_info

Status = Literal["contradiction", "unresolved_unbound", "residual_nonliteral"]
Mode = Literal["normative_restatement", "validated_case_application"]

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)")
_OPERATORS = (
    (re.compile(r"\bне\s+(?:более|позднее)\b|\bв\s+течение\b", re.I), "max"),
    (re.compile(r"\bне\s+менее\b", re.I), "min"),
    (re.compile(r"\b(?:более|свыше)\b", re.I), "gt"),
    (re.compile(r"\bменее\b", re.I), "lt"),
)
_UNITS = (
    (re.compile(r"\bрабоч\w*\s+(?:дн\w*|день)\b", re.I), "working_days"),
    (re.compile(r"\bкалендарн\w*\s+(?:дн\w*|день)\b", re.I), "calendar_days"),
    (re.compile(r"%|\bпроцент\w*\b", re.I), "percent"),
    (re.compile(r"\bмесяц\w*\b", re.I), "months"),
)
_PROHIBITION = re.compile(r"\b(?:категорически\s+)?(?:запрещается|запрещено|нельзя)\b", re.I)
_REFUSAL = re.compile(r"\b(?:отказать\w*|не\s+(?:разреш\w*|допуск\w*))\b", re.I)
_CONDITION = re.compile(r"\b(?:если|когда|при\s+условии)\b", re.I)
_TIMING = re.compile(r"\b(?:после|перед|до)\b", re.I)
_BINDING_KEYS = {"facet_id", "source_id", "quote", "role", "branch_effect", "quote_start", "quote_end"}
_ROLES = {"actor", "recipient", "condition", "exception", "timing", "quantity", "operator", "scope"}


def _out(status: Status, code: str) -> dict[str, object]:
    return {"status": status, "code": code, "authorizes_admission": False}


def _operator(text: str) -> str | None:
    return next((name for pattern, name in _OPERATORS if pattern.search(text)), None)


def _unit(text: str) -> str | None:
    return next((name for pattern, name in _UNITS if pattern.search(text)), None)


def _numbers(text: str) -> Counter[Decimal]:
    return Counter(Decimal(value.replace(",", ".")) for value in _NUMBER.findall(text))


def _pure_bound_component(text: str) -> bool:
    """A numeric case point may replace only a bound, never other source facts."""
    value = text.strip()
    operator = next((match for pattern, _name in _OPERATORS
                     if (match := pattern.match(value)) is not None), None)
    if operator is None:
        return False
    value = value[operator.end():].lstrip()
    number = _NUMBER.match(value)
    if number is None:
        return False
    value = value[number.end():].lstrip()
    unit = next((match for pattern, _name in _UNITS
                 if (match := pattern.match(value)) is not None), None)
    return unit is not None and not value[unit.end():].strip(" \t\r\n.,;:")


def _flat_unmodified_object_list(text: str) -> bool:
    """Close only one infinitive with a flat list of bare nominal objects.

    Equal word inventories do not preserve attachments between several actions
    or modified objects. Those constructions require separate typed evidence.
    """
    parts = text.strip().removesuffix(".").split(maxsplit=1)
    if len(parts) != 2:
        return False
    predicate = _word_info(parts[0])
    if not predicate.known or predicate.parts_of_speech != {"INFN"} or len(predicate.lemmas) != 1:
        return False
    objects = re.split(r"\s+и\s+|\s*,\s*", parts[1])
    if not 2 <= len(objects) <= 16:
        return False
    for item in objects:
        if _WORD.fullmatch(item) is None:
            return False
        nominal = _word_info(item)
        if not nominal.known or nominal.parts_of_speech != {"NOUN"} or len(nominal.lemmas) != 1:
            return False
    return True


def _literal_issue_codes(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return None
    if any(not isinstance(code, str) or not code for code in value):
        return None
    return tuple(value)


def _lemmas(text: str, *, predicates: bool = False) -> frozenset[str]:
    result: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        info = _word_info(word)
        if not predicates or info.parts_of_speech & {"INFN", "VERB", "PRTS", "GRND"}:
            result.update(info.lemmas)
    return frozenset(result)


def _negative_predicates(text: str) -> frozenset[str]:
    words = _WORD.findall(text.casefold())
    result: set[str] = set()
    for index, word in enumerate(words):
        info = _word_info(word)
        if index and words[index - 1] in {"не", "ни"} and info.parts_of_speech & {"INFN", "VERB", "PRTS"}:
            result.update(info.lemmas)
    return frozenset(result)


def _unambiguous_case_nouns(text: str, case: str) -> frozenset[str]:
    result: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        parses = [parsed for parsed in _morph().parse(word) if parsed.tag.POS == "NOUN"]
        cases = {value for parsed in parses for value in parsed.tag.grammemes
                 if value in {"nomn", "gent", "datv", "accs", "ablt", "loct"}}
        if cases == {case}:
            result.update(parsed.normal_form for parsed in parses if case in parsed.tag.grammemes)
    return frozenset(result)


def _finite_predicate_present(text: str) -> bool:
    return any(parsed.tag.POS == "VERB" for word in _WORD.findall(text.casefold())
               for parsed in _morph().parse(word))


def _noun_lemmas(text: str) -> frozenset[str]:
    return frozenset(parsed.normal_form for word in _WORD.findall(text.casefold())
                     for parsed in _morph().parse(word) if parsed.tag.POS == "NOUN")


def _lemma_inventory(text: str, parts_of_speech: frozenset[str]) -> Counter[str]:
    inventory: Counter[str] = Counter()
    for word in _WORD.findall(text.casefold()):
        info = _word_info(word)
        if info.parts_of_speech & parts_of_speech and len(info.lemmas) == 1:
            inventory[next(iter(info.lemmas))] += 1
    return inventory


def _nominal_role_inventory(text: str) -> Counter[tuple[str, tuple[str, ...]]] | None:
    inventory: Counter[tuple[str, tuple[str, ...]]] = Counter()
    cases = {"nomn", "gent", "datv", "accs", "ablt", "loct"}
    for word in _WORD.findall(text.casefold()):
        parses = [parsed for parsed in _morph().parse(word) if parsed.tag.POS == "NOUN"]
        if not parses:
            continue
        lemmas = {parsed.normal_form for parsed in parses}
        possible_cases = {case for parsed in parses for case in parsed.tag.grammemes if case in cases}
        if len(lemmas) != 1 or not possible_cases:
            return None
        inventory[(next(iter(lemmas)), tuple(sorted(possible_cases)))] += 1
    return inventory


def _explicit_first_actor(text: str) -> frozenset[str] | None:
    """Return only a closed first-subject/finite-verb agreement witness.

    Only a first nominal followed immediately by one agreeing transitive finite
    verb and a non-nominative nominal tail is closed. Infinitives, postposed
    subjects, ambiguous tails, and multi-predicate clauses abstain.
    """
    words = _WORD.findall(text.casefold())
    if len(words) < 2:
        return None
    first_parses = [parsed for parsed in _morph().parse(words[0])
                    if parsed.tag.POS == "NOUN" and "nomn" in parsed.tag.grammemes]
    actors = frozenset(parsed.normal_form for parsed in first_parses)
    if not actors:
        return None
    actor_numbers = {parsed.tag.number for parsed in first_parses
                     if parsed.tag.number in {"sing", "plur"}}
    finite = [(index, parsed) for index, word in enumerate(words[1:], 1)
              for parsed in _morph().parse(word) if parsed.tag.POS == "VERB"
              and parsed.tag.number in {"sing", "plur"}]
    predicate_positions = {index for index, _parsed in finite}
    if predicate_positions != {1} or len(actor_numbers) != 1:
        return None
    predicate_parses = [parsed for _index, parsed in finite]
    if (not any(parsed.tag.number in actor_numbers for parsed in predicate_parses)
            or not all("tran" in parsed.tag.grammemes for parsed in predicate_parses)):
        return None
    if any(parsed.tag.POS in {"INFN", "PRTS", "GRND"}
           for index, word in enumerate(words) if index not in predicate_positions
           for parsed in _morph().parse(word)):
        return None
    tail_nouns = 0
    for word in words[2:]:
        if word in {"и", "или", "либо"}:
            continue
        parses = [parsed for parsed in _morph().parse(word) if parsed.tag.POS == "NOUN"]
        if not parses:
            return None
        cases = {case for parsed in parses for case in parsed.tag.grammemes
                 if case in {"nomn", "gent", "datv", "accs", "ablt", "loct"}}
        if "nomn" in cases or not cases & {"gent", "datv", "accs", "ablt", "loct"}:
            return None
        tail_nouns += 1
    return actors if tail_nouns else None


def _parts(rows: object) -> dict[str, tuple[str, ...]] | None:
    if not isinstance(rows, Sequence) or isinstance(rows, str | bytes):
        return None
    result: dict[str, list[str]] = {"stem": [], "answer": [], "given": []}
    expected_role = {"stem": "fixed_context", "answer": "discriminating_answer", "given": "given_context"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"part", "role", "text"}:
            return None
        part, role, text = row["part"], row["role"], row["text"]
        if part not in result or role != expected_role[part] or not isinstance(text, str) or not text.strip():
            return None
        result[part].append(text.strip())
    if not result["answer"]:
        return None
    return {key: tuple(value) for key, value in result.items()}


def _inside(value: Decimal, boundary: Decimal, operator: str) -> bool:
    return {"max": value <= boundary, "min": value >= boundary,
            "gt": value > boundary, "lt": value < boundary}[operator]


def _validated_bindings(source: str, source_id: str, rows: object) -> tuple[dict[str, Any], ...] | None:
    if not isinstance(rows, Sequence) or isinstance(rows, str | bytes):
        return None
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _BINDING_KEYS or row.get("role") not in _ROLES:
            return None
        start, end, quote = row.get("quote_start"), row.get("quote_end"), row.get("quote")
        if (row.get("source_id") != source_id or type(start) is not int or type(end) is not int
                or not isinstance(quote, str) or not 0 <= start < end <= len(source)
                or source[start:end] != quote):
            return None
        result.append(row)
    return tuple(result)


def critical_preservation_status(
    component: object,
    mapped_parts: object,
    *,
    authoritative_answer: object,
    literal_issue_codes: object,
    claimed_component_count: object,
    source_context: object,
    source_id: str,
    comparison_mode: Mode | None,
    validated_governing_bindings: object,
    custody_valid: bool,
) -> dict[str, object]:
    if (not custody_valid or not isinstance(component, str) or not component.strip()
            or not isinstance(source_context, str) or component not in source_context):
        return _out("unresolved_unbound", "component_custody_unproved")
    parts = _parts(mapped_parts)
    issue_codes = _literal_issue_codes(literal_issue_codes)
    bindings = _validated_bindings(source_context, source_id, validated_governing_bindings)
    if type(claimed_component_count) is not int or claimed_component_count != 1:
        return _out("unresolved_unbound", "multi_component_boundary_not_eligible")
    if (comparison_mode not in {"normative_restatement", "validated_case_application"}
            or parts is None or issue_codes is None
            or not isinstance(authoritative_answer, str) or not authoritative_answer.strip()):
        return _out("unresolved_unbound", "comparison_protocol_unbound")
    if bindings is None:
        return _out("unresolved_unbound", "governing_bindings_invalid")
    stem = "\n".join(parts["stem"])
    if any(mapped not in authoritative_answer for mapped in parts["answer"]):
        return _out("unresolved_unbound", "mapped_answer_not_authoritative")
    answer = authoritative_answer.strip()
    given = "\n".join(parts["given"])
    visible_context = "\n".join((stem, given))

    binding_roles = {row["role"] for row in bindings}
    if _CONDITION.search(component) and not binding_roles & {"condition", "exception"}:
        return _out("unresolved_unbound", "source_condition_role_unbound")
    if _TIMING.search(component) and "timing" not in binding_roles:
        return _out("unresolved_unbound", "source_timing_role_unbound")

    source_operator, answer_operator = _operator(component), _operator(answer)
    source_unit, answer_unit = _unit(component), _unit(answer)
    source_numbers, answer_numbers = _numbers(component), _numbers(answer)
    context_operator, context_unit = _operator(visible_context), _unit(visible_context)
    context_numbers = _numbers(visible_context)
    if source_unit and answer_unit and source_unit != answer_unit:
        return _out("contradiction", "answer_changed_unit_category")
    case_point_proved = False
    if comparison_mode == "normative_restatement":
        if answer_operator is not None and source_operator != answer_operator:
            return _out("contradiction", "answer_changed_bound_operator")
        if answer_numbers and source_numbers != answer_numbers:
            return _out("contradiction", "answer_changed_normative_quantity")
        if source_operator and answer_operator is None and context_operator != source_operator:
            return _out("unresolved_unbound", "source_bound_operator_not_mapped")
        if source_unit and answer_unit is None and context_unit != source_unit:
            return _out("unresolved_unbound", "source_unit_not_mapped")
        if source_numbers and not answer_numbers and context_numbers != source_numbers:
            return _out("unresolved_unbound", "source_quantity_not_mapped")
    else:
        # A case is a point, not a competing restatement of the rule.
        if answer_operator is not None:
            if answer_operator != source_operator or source_numbers != answer_numbers:
                return _out("contradiction", "case_introduces_competing_normative_bound")
        elif source_operator and len(source_numbers) == len(answer_numbers) == 1:
            if not _inside(next(iter(answer_numbers)), next(iter(source_numbers)), source_operator):
                return _out("contradiction", "case_violates_source_bound")
            case_point_proved = True
        elif source_numbers:
            return _out("unresolved_unbound", "case_quantity_unproved")
        if source_unit and answer_unit is None and context_unit != source_unit:
            return _out("unresolved_unbound", "case_unit_unproved")

    for binding in bindings:
        quote, role = binding["quote"], binding["role"]
        if quote not in visible_context and quote not in answer:
            return _out("unresolved_unbound", f"required_{role}_not_visible")
        # A supplied premise may carry a role, but an explicit answer-side role
        # cannot contradict it. Only bounded marker/lemma evidence is used.
        if quote in visible_context and quote not in answer:
            if role == "actor":
                source_nouns = {lemma for word in _WORD.findall(quote.casefold())
                    for parsed in _morph().parse(word) if parsed.tag.POS == "NOUN"
                    for lemma in (parsed.normal_form,)}
                answer_subjects = _explicit_first_actor(answer)
                if source_nouns and answer_subjects and source_nouns.isdisjoint(answer_subjects):
                    return _out("contradiction", "answer_introduces_actor_conflict")
                if answer_subjects is None and _finite_predicate_present(answer):
                    return _out("unresolved_unbound", "answer_actor_role_unresolved")
            if role == "recipient":
                source_recipients = _lemmas(quote)
                answer_recipients = _unambiguous_case_nouns(answer, "datv")
                if source_recipients and answer_recipients and source_recipients.isdisjoint(answer_recipients):
                    return _out("contradiction", "answer_introduces_recipient_conflict")
                if source_recipients & _lemmas(answer) and quote not in answer:
                    return _out("unresolved_unbound", "answer_recipient_case_unresolved")
            marker = _CONDITION if role in {"condition", "exception"} else _TIMING if role == "timing" else None
            if marker is not None and marker.search(answer) and not (_lemmas(quote) <= _lemmas(answer)):
                return _out("contradiction", f"answer_introduces_{role}_conflict")

    source_predicates, answer_predicates = _lemmas(component, predicates=True), _lemmas(answer, predicates=True)
    shared = source_predicates & answer_predicates
    if _PROHIBITION.search(component) and not (_PROHIBITION.search(answer) or _REFUSAL.search(answer)):
        if shared:
            return _out("contradiction", "answer_weakened_normative_force")
        if comparison_mode != "validated_case_application":
            return _out("unresolved_unbound", "corrective_relation_unproved")
    source_negative, answer_negative = _negative_predicates(component), _negative_predicates(answer)
    if (comparison_mode == "normative_restatement" and any(
            (lemma in source_negative) != (lemma in answer_negative) for lemma in shared)):
        return _out("contradiction", "answer_changed_action_polarity")
    if (not binding_roles & {"actor", "recipient"}
            and _finite_predicate_present(component) and _finite_predicate_present(answer)):
        source_actor, answer_actor = _explicit_first_actor(component), _explicit_first_actor(answer)
        if source_actor is None or answer_actor is None:
            return _out("unresolved_unbound", "finite_clause_roles_unbound")
        if source_actor.isdisjoint(answer_actor):
            return _out("contradiction", "answer_reversed_actor_patient_roles")
        if _noun_lemmas(component) != _noun_lemmas(answer):
            return _out("unresolved_unbound", "finite_clause_nonactor_roles_unbound")
    source_predicate_inventory = _lemma_inventory(component, frozenset({"INFN", "VERB", "PRTS", "GRND"}))
    answer_predicate_inventory = _lemma_inventory(answer, frozenset({"INFN", "VERB", "PRTS", "GRND"}))
    source_nominal_inventory = _nominal_role_inventory(component)
    answer_nominal_inventory = _nominal_role_inventory(answer)
    if source_nominal_inventory is None or answer_nominal_inventory is None:
        return _out("unresolved_unbound", "nominal_role_inventory_unproved")
    if case_point_proved:
        if not _pure_bound_component(component):
            return _out("unresolved_unbound", "case_bound_component_not_pure")
        if (source_predicate_inventory and source_predicate_inventory != answer_predicate_inventory
                or source_nominal_inventory and source_nominal_inventory != answer_nominal_inventory):
            return _out("unresolved_unbound", "case_predicate_inventory_unproved")
        return _out("residual_nonliteral", "validated_case_point_within_bound")
    if issue_codes != ("source_word_order_unproved",):
        return _out("unresolved_unbound", "literal_relationship_unproved")
    if not (_flat_unmodified_object_list(component) and _flat_unmodified_object_list(answer)):
        return _out("unresolved_unbound", "predicate_object_attachments_unproved")
    if (source_predicate_inventory != answer_predicate_inventory
            or source_nominal_inventory != answer_nominal_inventory):
        return _out("unresolved_unbound", "component_inventory_unproved")
    return _out("residual_nonliteral", "critical_roles_bound_no_contradiction")
