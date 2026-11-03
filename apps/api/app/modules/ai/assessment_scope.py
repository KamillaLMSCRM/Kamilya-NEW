"""Conservative source-owned attachment vetoes, not a general Russian parser.

Related numeric words cannot establish what a duration governs. Unknown grammar
does not establish a positive proof: the ordinary source review still applies.
"""

from __future__ import annotations

import re

from app.modules.ai.assessment_preservation import (
    component_preservation_issue,
    is_bounded_conditional_tail,
    is_bounded_source_condition,
)

_MAX_CONDITIONAL_COMPONENT_CHARS = 512
_MAX_CONDITIONAL_OPTION_CHARS = 512
_MAX_CONDITIONAL_SOURCE_CONTEXT_CHARS = 65_536
_CONDITION_ENVELOPE_RE = re.compile(r"\([^()\n]{1,160}\)")
_BARE_CONDITION_RE = re.compile(r"^(?:при|если)\s+(?P<body>.+)$", re.IGNORECASE)
_INDEPENDENCE_RE = re.compile(
    r"(?<!\w)(?:независимо\s+от|вне\s+зависимости\s+от)(?!\w)",
    re.IGNORECASE,
)
_INDEPENDENCE_FORM_PATTERNS = (
    (
        "independent_of",
        re.compile(r"(?<!\w)независимо\s+от(?!\w)", re.IGNORECASE),
    ),
    (
        "outside_dependence_on",
        re.compile(r"(?<!\w)вне\s+зависимости\s+от(?!\w)", re.IGNORECASE),
    ),
)
_NECESSARY_CONDITION_RE = re.compile(
    r"(?<!\w)(?:только|лишь|исключительно)\s+(?:при|если)(?!\w)",
    re.IGNORECASE,
)
_OUTSIDE_RESTRICTION_RE = re.compile(
    r"(?<!\w)(?:нельзя|запрещено|не\s+допускается|кроме|за\s+исключением)(?!\w)",
    re.IGNORECASE,
)
_CONDITIONAL_EXTENSION_ISSUE = "unproved_conditional_option_contradiction"
_CONDITIONAL_CHOICE_FORM_ISSUE = "conditional_choice_requires_explicit_counterfactual"


def _normalized(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _month_dimensions(value: str) -> set[int]:
    """Recognize bounded month dimensions for a negative ownership guard only.

    No source/key is rewritten and an unrecognized quantity never proves truth.
    Nominal and adjectival forms share a dimension (12 months/12-month period).
    """
    roots = {"одн": 1, "двух": 2, "дву": 2, "два": 2, "три": 3, "трех": 3,
             "четыр": 4, "пят": 5, "шест": 6, "сем": 7, "восем": 8, "восьм": 8,
             "девят": 9, "десят": 10, "одиннадцат": 11, "двенадцат": 12}
    result = set()
    for match in re.finditer(r"(?<!\w)(?P<n>[0-9]{1,4}|[а-я]{2,24})[-\s]*(?:месяц[а-я]*|месячн[а-я]*)(?!\w)", value):
        token = match["n"]
        if token.isascii() and token.isdigit():
            result.add(int(token))
        else:
            candidates = {number for root, number in roots.items() if token.startswith(root)}
            if len(candidates) == 1:
                result.update(candidates)
    return result


def _bounded_literal_pattern(value: str) -> str:
    return ((r"(?<!\w)" if value[:1].isalnum() else "") + re.escape(value)
            + (r"(?!\w)" if value[-1:].isalnum() else ""))


def _single_top_level_independence(value: str) -> re.Match[str] | None:
    """Return one unparenthesized independence operator, else fail closed."""
    matches = list(_INDEPENDENCE_RE.finditer(value))
    if len(matches) != 1:
        return None
    match = matches[0]
    depth = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                return None
        if index == match.start() and depth != 0:
            return None
    return match if depth == 0 else None


def conditional_choice_form_issue(
    component: str,
    option: str,
    *,
    source_context: str,
) -> str | None:
    """Reject an added independence form without classifying option truth."""
    if (
        not isinstance(component, str)
        or not isinstance(option, str)
        or not isinstance(source_context, str)
        or not component
        or component != component.strip()
        or not option.strip()
        or len(component) > _MAX_CONDITIONAL_COMPONENT_CHARS
        or len(option) > _MAX_CONDITIONAL_OPTION_CHARS
        or len(source_context) > _MAX_CONDITIONAL_SOURCE_CONTEXT_CHARS
        or source_context.count(component) != 1
    ):
        return None

    envelopes = list(_CONDITION_ENVELOPE_RE.finditer(component))
    if (
        len(envelopes) != 1
        or component.count("(") != 1
        or component.count(")") != 1
    ):
        return None
    envelope = envelopes[0]
    condition = _BARE_CONDITION_RE.fullmatch(
        component[envelope.start() + 1 : envelope.end() - 1].strip()
    )
    if condition is None or not is_bounded_source_condition(condition["body"]):
        return None

    source_forms = {
        name for name, pattern in _INDEPENDENCE_FORM_PATTERNS if pattern.search(component)
    }
    option_forms = {
        name for name, pattern in _INDEPENDENCE_FORM_PATTERNS if pattern.search(option)
    }
    if option_forms - source_forms:
        return _CONDITIONAL_CHOICE_FORM_ISSUE
    return None


def conditional_extension_option_issue(
    component: str,
    option: str,
    *,
    source_context: str,
) -> str | None:
    """Veto one unsupported extension of a source-conditional proposition.

    This is only a negative guard. It requires literal, unique provenance and
    strict bidirectional lexical equivalence of the option prefix and the
    source proposition with its sole parenthetical condition removed.
    """
    if (
        not isinstance(component, str)
        or not isinstance(option, str)
        or not isinstance(source_context, str)
        or not component
        or component != component.strip()
        or not option.strip()
        or len(component) > _MAX_CONDITIONAL_COMPONENT_CHARS
        or len(option) > _MAX_CONDITIONAL_OPTION_CHARS
        or len(source_context) > _MAX_CONDITIONAL_SOURCE_CONTEXT_CHARS
        or source_context.count(component) != 1
    ):
        return None

    envelopes = list(_CONDITION_ENVELOPE_RE.finditer(component))
    if (
        len(envelopes) != 1
        or component.count("(") != 1
        or component.count(")") != 1
    ):
        return None
    envelope = envelopes[0]
    condition = _BARE_CONDITION_RE.fullmatch(
        component[envelope.start() + 1 : envelope.end() - 1].strip()
    )
    if condition is None or not is_bounded_source_condition(condition["body"]):
        return None

    component_start = source_context.find(component)
    outside = (
        source_context[:component_start]
        + " "
        + source_context[component_start + len(component) :]
    )
    if _NECESSARY_CONDITION_RE.search(outside) or _OUTSIDE_RESTRICTION_RE.search(outside):
        return None

    independence = _single_top_level_independence(option)
    if independence is None:
        return None
    prefix = option[: independence.start()].strip()
    tail = option[independence.end() :].strip()
    if not prefix or not is_bounded_conditional_tail(tail):
        return None

    core = (component[: envelope.start()] + " " + component[envelope.end() :]).strip()
    if (
        component_preservation_issue(core, prefix, source_context=source_context)
        is not None
        or component_preservation_issue(prefix, core, source_context=source_context)
        is not None
    ):
        return None
    return _CONDITIONAL_EXTENSION_ISSUE


def _parenthetical_coordination_issue(source: str, answer: str, explanation: str) -> str | None:
    """Veto a literal local-condition rewrite; never infer an unknown attachment."""
    pattern = re.compile(
        r"(?P<left>[^,;:.!?\n()]{3,160}),\s*"
        r"(?P<right>[^,;:.!?\n()]{3,100}?)\s*"
        r"\(\s*(?P<condition>(?:при|если)\s+[^()\n]{1,100}?)\s*\)", re.I,
    )
    for match in pattern.finditer(source):
        left, right, condition = (_normalized(match[group]).strip() for group in ("left", "right", "condition"))
        if any(len(re.findall(_bounded_literal_pattern(part), _normalized(source))) != 1
               for part in (left, right, condition)):
            continue
        combined = re.compile(
            _bounded_literal_pattern(left) + r"\s+и\s+" + _bounded_literal_pattern(right)
            + r"\s*(?:\(\s*)?" + re.escape(condition) + r"(?!\w)", re.I,
        )
        if any(combined.search(_normalized(part)) for part in (answer, explanation)):
            return (
                "unproved_parenthetical_condition_scope: do not broaden a trailing local "
                "source condition across the combined list. Preserve the original local "
                "clause/parentheses or split differently qualified objects. Where the source "
                "attachment is ambiguous, retain that ambiguity rather than grade an exclusive reading"
            )
    return None


def source_scope_issue(source: str, quote: str, stem: str, answer: str, explanation: str) -> str | None:
    """Veto a changed/ambiguous attachment only within its owned source quote."""
    if not quote or quote not in source:
        return "unproved_scope_owner: supporting quote must belong to the original source"
    # A short numeric quote cannot hide its governing predicate. Extend only
    # inside the uniquely owned sentence; never borrow a sibling rule/action.
    start = source.find(quote)
    if source.find(quote, start + 1) >= 0:
        return "ambiguous_scope_owner: supporting quote occurs in multiple source positions"
    if issue := _open_enumeration_issue(quote, stem):
        return issue
    if issue := _parenthetical_coordination_issue(quote, answer, explanation):
        return issue
    end = start + len(quote)
    before = list(re.finditer(r"[.!?;\n]", source[:start]))
    sentence_start = before[-1].end() if before else 0
    after = re.search(r"[.!?;\n]", source[end:])
    sentence_end = end if re.search(r"[.!?;]\s*$", quote) else (end + after.start() if after else len(source))
    evidence = _normalized(source[sentence_start:sentence_end])
    candidate = _normalized(stem + "\n" + answer + "\n" + explanation)
    amendment = re.search(r"решени\w*\s+о\s+соглас\w*\s+с\s+(?:предложенн\w*\s+)?изменени\w*", evidence)
    duration = re.search(r"\bна\s+срок\b.{0,90}\b(?:месяц\w*|дн\w*|лет|год\w*)\b", evidence)
    formation = r"\b(?:заключа\w*|оформля\w*)\b.{0,45}\bдоговор\w*\b|\bдоговор\w*\b.{0,70}\b(?:заключа\w*|оформля\w*)\b"
    nominal_term = r"\bсрок\w*\s+(?:(?:действия|самого|первоначального)\s+)?договор\w*\b"
    contract_owner = formation + "|" + nominal_term
    if amendment and duration and re.search(contract_owner, candidate):
        if re.search(contract_owner, evidence):
            return (
                "ambiguous_duration_owner: supporting evidence contains both amendment and original-contract "
                "owners; a sibling owner is not proof of the tested duration. Cite only its uniquely governing "
                "clause or leave the source-dependent interpretation unresolved"
            )
        return (
            "unsupported_duration_owner: source discusses agreement to amendments, not an original-contract "
            "formation prerequisite. Preserve the governing action and all borrower/application conditions; "
            "do not assign an ambiguously attached duration to a different action"
        )
    # Two available nominal governors: "при условии [X ... либо Y]"
    # versus "месяцу [Z ... либо Y]". Nearest attachment is not unique proof.
    ambiguous = re.search(
        r"\bпри\s+условии\s+[а-я]+(?:ения|ания|ости)\b[^;.!?]{0,1800}"
        r"(?P<comparison>\bпо\s+сравнению\b[^;.!?]{0,1400})\bпредшествующ[а-я]*\s+месяцу\s+"
        r"(?P<first_anchor>[а-я]+(?:ения|ания|ости))\b"
        r"[^;.!?]{0,600}?\s+либо\s+(?P<alternative>[а-я]+(?:ения|ания|ости))\b",
        evidence,
    )
    tested = _normalized(stem + "\n" + answer)
    second_attachment_claimed = bool(ambiguous and re.search(
        r"\b" + re.escape(ambiguous["alternative"][:-2]) + r"[а-я]*\b", tested))
    # Omitting the alternative cannot establish the other reading either. The
    # source owns the first nominal anchor; only a question testing comparison
    # with that anchor is vetoed. Independent current-period counts and reduction
    # thresholds do not become ambiguous simply by sharing this source sentence.
    answer_months = _month_dimensions(_normalized(answer))
    anchor_pattern = (r"\b" + re.escape(ambiguous["first_anchor"][:-2]) + r"[а-я]*\b") if ambiguous else ""
    first_attachment_claimed = bool(ambiguous
        and ((bool(answer_months & _month_dimensions(ambiguous["comparison"])) and re.search(anchor_pattern, tested))
             or (not answer_months and re.search(anchor_pattern, _normalized(answer)))))
    if second_attachment_claimed or first_attachment_claimed:
        return (
            "ambiguous_source_attachment: both nominal governors remain grammatically possible in the original; "
            "do not grade either exclusive attachment as truth. Preserve the unresolved source rule for review; "
            "test only independent unambiguous facts instead of guessing the intended scope"
        )
    return None


def _open_enumeration_issue(quote: str, stem: str) -> str | None:
    """Veto exhaustive permission wording over a literal residual list member.

    This is a negative scope check, not a general list classifier or approval.
    Only the owned quote is inspected: an unrelated open list cannot qualify it.
    Questions about the categories explicitly listed still use ordinary review.
    """
    request = "\n".join(" ".join(line.split()) for line in stem.splitlines() if not line.startswith("Условие:"))
    # An explicitly source-bounded category list is different from the universe
    # of permitted instances. This does not approve the answer or its contents.
    source_bound_pattern = re.compile(
        r"\b(?:прямо\s+)?(?:перечислен[а-я]*|указан[а-я]*|назван[а-я]*|приведен[а-я]*)\s+"
        r"в\s+(?:(?:этом|данном|исходном)\s+)?(?:источнике|документе|перечне|списке|тексте)\b",
        re.I,
    )
    permission = r"(?:допустим[а-я]*|разреш[а-я]*|возможн[а-я]*)\b"
    # Match positive predicate shapes, not arbitrary text up to a permission
    # word: negation separated by a copula must not become positive permission.
    noun_word = r"(?!(?:не|ни|которые|являются|относятся|считаются|могут|быть)\b)[а-я]+"
    noun_phrase = noun_word + r"(?:\s+" + noun_word + r"){0,3}"
    permitted_domain = (
        r"(?:(?:всех\s+)?" + permission
        + r"|" + noun_phrase + r"\s*,?\s*которые\s+(?:являются\s+)?" + permission
        + r"|" + noun_phrase + r"\s+являются\s+" + permission + r")"
    )
    exhaustive_pattern = re.compile(
        r"\b(?:полны[йех]|исчерпывающ[а-я]*|весь|вся|всё|все)\s+(?:перечень|список|набор)\s+"
        + permitted_domain + r"|\bвсе\s+" + permitted_domain,
        re.I,
    )
    # Each request owns its restriction: a question about a source's named
    # categories cannot exempt a separate complete-permission request.
    clauses = re.split(r"[.!?;\n]+|,\s*(?=(?:назовите|укажите|перечислите|какие|какой)\b)", request, flags=re.I)
    unbounded = False
    for clause in clauses:
        for match in exhaustive_pattern.finditer(clause):
            source_bound = source_bound_pattern.search(clause, match.end())
            negative_bound = re.search(
                r"\bне\s+(?:только|прямо|перечислен[а-я]*|указан[а-я]*|назван[а-я]*|приведен[а-я]*)\b",
                clause, re.I,
            )
            if source_bound is None or negative_bound is not None:
                unbounded = True
                break
        if unbounded:
            break
    if not unbounded:
        return None
    residual = re.search(
        r"(?:^[ \t]*(?:(?:[-*•])[ \t]*(?:\d{1,3}[.)][ \t]*)?|\d{1,3}[.)][ \t]*)"
        r"|;[ \t]*(?:\d{1,3}[.)][ \t]*)?)"
        r"(?:ин(?:ое|ая|ые|ой|ого|ую|ым|ыми|ых)|друг(?:ое|ая|ие|ой|ого|ую|им|ими|их)|"
        r"проч(?:ее|ая|ие|ий|его|ую|им|ими|их))[ \t]+[^\W\d_]{3,}",
        quote, re.I | re.M,
    )
    explicit_open = re.search(
        r"\b(?:перечень|список|набор)\b[^.!?\n]{0,100}\bне\s+явля[а-я]*\s+исчерпывающ[а-я]*\b",
        quote, re.I,
    )
    if residual is None and explicit_open is None:
        return None
    return (
        "open_source_set_cannot_be_exhaustive: the owned source contains a residual category or explicitly "
        "non-exhaustive list; it does not establish the complete universe of permitted instances. "
        "Test a concrete membership decision or the categories explicitly listed in the source, "
        "retaining its residual category and qualifications. Do not silently close the source list"
    )
