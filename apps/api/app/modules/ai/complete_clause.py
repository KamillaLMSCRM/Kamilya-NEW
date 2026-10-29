"""Fail-closed surface contract for server-rendered complete-clause questions.

This module proves only a narrow presentation shape.  It deliberately does not
select an answer, establish truth, award target coverage, or relax any source
preservation or semantic-review contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

COMPLETE_CLAUSE_FORM = "complete_clause"
COMPLETE_CLAUSE_QUESTION = "Какой вариант полностью соответствует правилу?"
_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)?")
_PREDICATE_POS = frozenset({"VERB", "INFN", "PRTS"})
_NOMINAL_POS = frozenset({"NOUN", "ADJF", "ADJS", "PRTF", "PRTS", "NUMR", "NPRO", "PREP", "CONJ", "PRCL"})
_SUBJECT_PREFIX_POS = frozenset({"NOUN", "ADJF", "PRTF", "NUMR", "NPRO"})
_SUBJECT_HEAD_POS = frozenset({"NOUN", "NPRO"})
_MODAL_POS = frozenset({"ADJS", "PRED", "PRTS"})
_RESERVED_EXISTING_FORMS = frozenset({"full_set"})


@dataclass(frozen=True)
class CompleteClauseSpec:
    target_id: str
    component_source_id: str
    component: str
    rendered_question: str
    premise_prefix_chars: int
    inventory_key: str


@lru_cache(maxsize=1)
def _morphology() -> Any:
    import pymorphy3  # type: ignore[import-untyped]

    return pymorphy3.MorphAnalyzer()


def _known_parts_of_speech(token: str) -> frozenset[str]:
    analyzer = _morphology()
    normalized = token.casefold()
    if not analyzer.word_is_known(normalized):
        return frozenset()
    return frozenset(parse.tag.POS for parse in analyzer.parse(normalized) if parse.tag.POS is not None)


def _known_primary_part_of_speech(token: str) -> str | None:
    analyzer = _morphology()
    normalized = token.casefold()
    if not analyzer.word_is_known(normalized):
        return None
    parses = analyzer.parse(normalized)
    return parses[0].tag.POS if parses else None


def _is_actor_acronym(token: str) -> bool:
    return re.fullmatch(r"[А-ЯЁ]{2,8}(?:-[А-ЯЁ]{2,8})?", token) is not None


def _is_bounded_subject_prefix(words: list[str], primary: list[str | None]) -> bool:
    """Accept a short nominal actor surface, including generic Cyrillic acronyms."""
    if not 1 <= len(words) <= 4 or len(words) != len(primary):
        return False
    if not all(pos in _SUBJECT_PREFIX_POS or _is_actor_acronym(word)
               for word, pos in zip(words, primary, strict=True)):
        return False
    return primary[-1] in _SUBJECT_HEAD_POS or _is_actor_acronym(words[-1])


def _has_main_clause_shape(words: list[str]) -> bool:
    """Recognize one early main predicate, never an embedded noun modifier.

    This is intentionally not a Russian grammar engine.  The typed form accepts
    an early finite/short predicate, a bounded modal-plus-infinitive shape, or an
    initial (optionally negated) infinitive decision.  Source truth, agreement,
    government and educational quality remain separate mandatory reviews.
    """
    if len(words) < 2 or not any("NOUN" in _known_parts_of_speech(word) for word in words):
        return False
    primary = [_known_primary_part_of_speech(word) for word in words]
    if primary[0] in {"PREP", "CONJ"}:
        return False  # Conditions belong in the server premise, not before the option's decision.
    if primary[0] == "INFN" or (words[0].casefold() == "не" and len(words) > 1 and primary[1] == "INFN"):
        return True
    if any(pos in {"VERB", "PRTS"} for pos in primary[:4]):
        return True
    for index, pos in enumerate(primary):
        if pos != "INFN" or index == 0:
            continue
        modal_index = index - 1
        if words[modal_index].casefold() == "не":
            modal_index -= 1
        if modal_index < 1 or primary[modal_index] not in _MODAL_POS:
            continue
        subject_end = modal_index
        if words[modal_index - 1].casefold() == "не":
            subject_end -= 1
        if _is_bounded_subject_prefix(words[:subject_end], primary[:subject_end]):
            return True
    return False


def _is_unique_nominal_fragment(value: object, source_text: str, *, governed_leaf: bool = False) -> bool:
    if not isinstance(value, str) or value != value.strip() or not 2 <= len(value) <= 240 or "\n" in value:
        return False
    if source_text.count(value) != 1 or any(char.isdigit() for char in value):
        return False
    words = _WORD.findall(value)
    if not (1 if governed_leaf else 2) <= len(words) <= 32 or any(word.casefold() in {"не", "ни"} for word in words):
        return False
    parts = [_known_parts_of_speech(word) for word in words]
    if any(not item or item & _PREDICATE_POS for item in parts):
        return False
    return any("NOUN" in item for item in parts) and all(item <= _NOMINAL_POS for item in parts)


def _owned_checklist_leaf(target: Any, component: str, owner: str, original: str) -> bool:
    """Prove list custody, not meaning: retain the complete actor/time line and governor.

    A bare noun may use complete authored clauses only when its exact source list
    supplies an owned common premise. Never manufacture an actor from nearby text
    or treat another required list member as a false answer.
    """
    if (not isinstance(component, str) or not re.fullmatch(_WORD.pattern + r"[,;.]?", component)
            or original.count(component) != 1):
        return False
    bindings = getattr(target, "qualification_bindings", ())
    if not isinstance(bindings, tuple | list):
        return False
    actors = [row for row in bindings if isinstance(row, dict) and row.get("role") == "actor"]
    governors = [row for row in bindings if isinstance(row, dict) and row.get("role") == "scope"
                 and isinstance(row.get("quote"), str) and row["quote"].endswith(":")]
    if len(actors) != 1 or len(governors) != 1:
        return False
    actor, governor = actors[0], governors[0]
    for row in (actor, governor):
        if (row.get("source_id") != owner or not isinstance(row.get("quote"), str)
                or original.count(row["quote"]) != 1 or type(row.get("quote_start")) is not int
                or type(row.get("quote_end")) is not int
                or not 0 <= row["quote_start"] < row["quote_end"] <= len(original)
                or original[row["quote_start"]:row["quote_end"]] != row["quote"]):
            return False
    if actor["quote_end"] > governor["quote_start"]:
        return False
    # A suffix such as an actor's acronym cannot silently drop the timing on its line.
    if actor["quote_start"] != 0 and original[actor["quote_start"] - 1] not in "\r\n":
        return False
    if not re.fullmatch(r"\s*(?:\d+[.)]\s*)?", original[actor["quote_end"]:governor["quote_start"]]):
        return False
    start = original.index(component)
    if governor["quote_end"] >= start:
        return False
    between = original[governor["quote_end"]:start]
    # Prove the COMPLETE physical leaf, not a noun prefix losing an object suffix.
    line_end = original.find("\n", start)
    if line_end < 0:
        line_end = len(original)
    suffix = original[start + len(component):line_end].rstrip("\r")
    punctuation = "" if component[-1:] in {",", ";", "."} else r"[,;.]?"
    if not re.fullmatch(r"[ \t]*" + punctuation + r"[ \t]*", suffix):
        return False
    # All traversed rows must be same-level, same-marker siblings of this governor.
    rows = between.splitlines()
    marker = re.fullmatch(r"([ \t]*)([-–—•])[ \t]+", rows[-1]) if rows else None
    if not marker or rows[0].strip():
        return False
    sibling = re.escape(marker[1] + marker[2]) + r"[ \t]+"
    for line in rows[1:-1]:
        if not re.fullmatch(sibling + r"[А-Яа-яЁё]+[,;.]?[ \t]*", line):
            return False
    if line_end < len(original):
        following = original[line_end + 1:].split("\n", 1)[0].rstrip("\r")
        if following.strip() and not re.match(sibling, following):
            # An indented/wrapped continuation can contain a mandatory object.
            # A new top-level numbered rule is a closed list boundary.
            if not re.match(r"\d+[.)][ \t]+", following):
                return False
    return True


def _binding_prefix(target: Any, sources: dict[str, Any], component: str) -> str | None:
    bindings = getattr(target, "qualification_bindings", ())
    if not isinstance(bindings, tuple | list):
        return None
    rows: list[tuple[str, int, int, str]] = []
    for binding in bindings:
        if (not isinstance(binding, dict)
                or set(binding) != {"facet_id", "source_id", "quote", "role", "branch_effect", "quote_start", "quote_end"}
                or binding["branch_effect"] not in {"none", "scopes_action"}
                or binding["source_id"] not in getattr(target, "source_ids", ())
                or binding["source_id"] not in sources
                or not isinstance(binding["quote"], str)
                or type(binding["quote_start"]) is not int
                or type(binding["quote_end"]) is not int):
            return None
        source = sources[binding["source_id"]]
        original = getattr(source, "original_text", "") or getattr(source, "text", "")
        quote = binding["quote"]
        if (not quote or original[binding["quote_start"]:binding["quote_end"]] != quote
                or component in quote):
            return None
        label = ("Фрагмент источника об участнике:" if binding["role"] == "actor"
                 else "Основание из источника:")
        rows.append((binding["source_id"], binding["quote_start"], binding["quote_end"], f"{label} «{quote}»"))
    return "\n".join(row[3] for row in sorted(rows)) + ("\n" if rows else "")


def build_complete_clause_spec(target: Any, sources: tuple[Any, ...], *, enabled: bool) -> CompleteClauseSpec | None:
    """Return a deterministic presentation spec for one exact nominal component."""
    if (enabled is not True or getattr(target, "answer_surface", "") != COMPLETE_CLAUSE_FORM
            or getattr(target, "assessment_level", "") == "operational_decision"
            or getattr(target, "question_format", "") in _RESERVED_EXISTING_FORMS
            or getattr(target, "question_format", "") not in {"", None}
            or getattr(target, "construction_mode", "")
            or getattr(target, "component_construction", False)
            or getattr(target, "fixed_source_context", None) is not None
            or getattr(target, "original_context_bindings", ())
            or getattr(target, "assessed_focus", "")
            or getattr(target, "source_quote_proposition", None) is not None):
        return None
    requirements = getattr(target, "answer_requirements", ())
    owners = getattr(target, "component_source_ids", ())
    if (not isinstance(requirements, tuple | list) or len(requirements) != 1
            or not isinstance(requirements[0], tuple | list) or len(requirements[0]) != 1
            or not isinstance(owners, tuple | list) or len(owners) != 1
            or not isinstance(owners[0], tuple | list) or len(owners[0]) != 1):
        return None
    component = requirements[0][0]
    owner = owners[0][0]
    source_map = {source_id: source for source in sources
                  if isinstance((source_id := getattr(source, "source_id", None)), str)}
    if owner not in getattr(target, "source_ids", ()) or owner not in source_map:
        return None
    original = getattr(source_map[owner], "original_text", "") or getattr(source_map[owner], "text", "")
    if not _is_unique_nominal_fragment(component, original,
            governed_leaf=_owned_checklist_leaf(target, component, owner, original)):
        return None
    prefix = _binding_prefix(target, source_map, component)
    if prefix is None:
        return None
    context = getattr(target, "context", "")
    binding_quotes = tuple(binding["quote"] for binding in getattr(target, "qualification_bindings", ()))
    if context and context not in binding_quotes:
        return None
    rendered = prefix + COMPLETE_CLAUSE_QUESTION
    if len(rendered) > 1200:
        return None
    inventory = hashlib.sha256(json.dumps({
        "form": COMPLETE_CLAUSE_FORM,
        "component_source_id": owner,
        "component": component,
        "rendered_question": rendered,
    }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return CompleteClauseSpec(
        target_id=getattr(target, "target_id", ""),
        component_source_id=owner,
        component=component,
        rendered_question=rendered,
        premise_prefix_chars=len(prefix),
        inventory_key="complete-clause:" + inventory,
    )


def parse_complete_clause_options(options: object) -> tuple[str, ...]:
    """Validate only bounded main-clause-shaped option surfaces."""
    if not isinstance(options, list | tuple) or not 2 <= len(options) <= 4:
        raise ValueError("complete_clause_invalid_options")
    result: list[str] = []
    for option in options:
        if (not isinstance(option, str) or option != option.strip() or not option
                or len(option) > 240 or "\n" in option):
            raise ValueError("complete_clause_invalid_options")
        if option.endswith(("?", "？")):
            raise ValueError("complete_clause_incomplete_option")
        words = _WORD.findall(option)
        if not words:
            raise ValueError("complete_clause_incomplete_option")
        if not _has_main_clause_shape(words):
            raise ValueError("complete_clause_incomplete_option")
        result.append(option)
    if len({option.casefold() for option in result}) != len(result):
        raise ValueError("complete_clause_duplicate_option")
    return tuple(result)
