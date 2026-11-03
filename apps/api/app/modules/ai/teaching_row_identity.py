"""Source-bound grammatical projection of a native table row identity.

This helper has one deliberately narrow purpose: it may replace one inflected
Russian ``данный + NOUN`` reference in an exact source component with the
complete first-cell label of the same native Markdown table row.  The returned
receipt proves byte custody and a conservative grammatical comparison only.  It
does not prove meaning, coverage, correctness, admission, or assessment credit.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any
from urllib.parse import unquote

from app.modules.ai.assessment_preservation import (
    _word_info,
    component_preservation_issue,
)
from app.modules.ai.evidence_engine.models import SourceFact

TEACHING_ROW_IDENTITY_POLICY = "teaching-row-identity-restatement-v1"
MAX_FACT_ID_CHARS = 160
MAX_LABEL_CHARS = 1_000
MAX_COMPONENT_CHARS = 2_000
MAX_SOURCE_VALUE_CHARS = 60_000
MAX_LOCATOR_CHARS = 4_000

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_OPEN_SET = re.compile(
    r"(?:\bи\s+т\.\s*(?:п|д)\.|\betc\.?\b|\bи\s+проч(?:ее|ие|\.)\b)",
    re.IGNORECASE,
)
_LABEL_LIST = re.compile(r"(?:[,;/\n]|\b(?:и|или|либо)\b)", re.IGNORECASE)
_FORBIDDEN_LOCATOR_FIELDS = frozenset({"sheet", "title", "heading", "paragraph"})


@dataclass(frozen=True, slots=True)
class RowIdentityRestatementReceipt:
    """Immutable custody receipt for one row-label grammatical projection."""

    policy: str
    source_fact_id: str
    source_fact_sha256: str
    source_value_sha256: str
    raw_component: str
    component_start: int
    component_end: int
    component_sha256: str
    raw_subject_label: str
    subject_label_sha256: str
    subject_identity_sha256: str
    source_locator: str
    source_locator_sha256: str
    doc_id: str
    source_revision: str
    table: int
    row: int
    column: int
    deictic_start: int
    deictic_end: int
    deictic_text: str
    referenced_noun_lemma: str
    subject_noun_start: int
    subject_noun_end: int
    projected_component: str
    projection_subject_start: int
    projection_subject_end: int
    projected_component_sha256: str
    learner_quote_sha256: str
    binding_sha256: str


def _digest(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _bounded_text(value: object, maximum: int, *, allow_empty: bool = False) -> str | None:
    if type(value) is not str or value != value.strip() or len(value) > maximum:
        return None
    if not allow_empty and not value:
        return None
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        return None
    return value


def _locator_values(locator: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    for item in locator.split(";"):
        key, separator, raw = item.partition("=")
        if not separator or not key or key in values:
            return None
        decoded = unquote(raw)
        if not decoded or decoded != decoded.strip():
            return None
        values[key] = decoded
    if _FORBIDDEN_LOCATOR_FIELDS & values.keys():
        return None
    return values


def _positive_integer(value: object) -> int | None:
    if type(value) is not str or not re.fullmatch(r"[1-9]\d*", value):
        return None
    result = int(value)
    return result if result <= 2_147_483_647 else None


def _native_table_identity(fact: SourceFact) -> tuple[str, str, int, int, int] | None:
    locator = _locator_values(fact.source_locator)
    if locator is None:
        return None
    doc_id = locator.get("doc_id")
    source_revision = locator.get("source_revision")
    table = _positive_integer(locator.get("table"))
    row = _positive_integer(locator.get("row"))
    column = _positive_integer(locator.get("column"))
    if not doc_id or not source_revision or table is None or row is None or column is None:
        return None
    return doc_id, source_revision, table, row, column


def _unique_occurrence(owner: str, value: str) -> tuple[int, int] | None:
    start = owner.find(value)
    if start < 0 or owner.find(value, start + 1) >= 0:
        return None
    return start, start + len(value)


def _deictic_reference(
    component: str,
) -> tuple[int, int, str, str] | None:
    words = list(_WORD.finditer(component))
    matches: list[tuple[int, int, str, str]] = []
    for deictic, noun in zip(words, words[1:], strict=False):
        if not component[deictic.end():noun.start()].isspace():
            continue
        noun_info = _word_info(noun.group().casefold())
        deictic_parses = {
            (parse.normal_form, parse.tag.POS)
            for parse in _morph_parse(deictic.group().casefold())
            if parse.tag.POS == "ADJF" and parse.normal_form == "данный"
        }
        if (
            deictic_parses == {("данный", "ADJF")}
            and noun_info.known
            and noun_info.parts_of_speech == {"NOUN"}
            and len(noun_info.noun_lemmas) == 1
        ):
            matches.append(
                (
                    deictic.start(),
                    noun.end(),
                    component[deictic.start():noun.end()],
                    next(iter(noun_info.noun_lemmas)),
                )
            )
    return matches[0] if len(matches) == 1 else None


def _subject_noun(
    label: str,
    noun_lemma: str,
) -> tuple[int, int] | None:
    matches: list[tuple[int, int]] = []
    for word in _WORD.finditer(label):
        info = _word_info(word.group().casefold())
        if noun_lemma not in info.noun_lemmas:
            continue
        if (
            not info.known
            or info.parts_of_speech != {"NOUN"}
            or info.noun_lemmas != {noun_lemma}
        ):
            return None
        matches.append((word.start(), word.end()))
    return matches[0] if len(matches) == 1 else None


def _pronoun_inventory(value: str) -> Counter[str] | None:
    result: Counter[str] = Counter()
    for word in _WORD.finditer(value):
        info = _word_info(word.group().casefold())
        if "NPRO" not in info.parts_of_speech:
            continue
        lemmas = {
            lemma
            for lemma in info.lemmas
            if any(
                parse.tag.POS == "NPRO" and parse.normal_form == lemma
                for parse in _morph_parse(word.group().casefold())
            )
        }
        if len(lemmas) != 1:
            return None
        result[next(iter(lemmas))] += 1
    return result


def _morph_parse(word: str) -> tuple[Any, ...]:
    # Reuse the same analyzer as the strict preservation checker so dictionary
    # support cannot silently diverge between the projection and comparison.
    from app.modules.ai.assessment_preservation import _morph

    return tuple(_morph().parse(word))


def _protected_relations(value: str) -> tuple[tuple[str, str], ...] | None:
    # The relation guard currently lives beside the strict native restatement
    # path.  Import lazily so this pure sidecar can later be called from that
    # module without creating an import cycle.
    from app.modules.ai.final_teaching_eligibility import (
        _protected_operator_attachment_signature,
    )

    return _protected_operator_attachment_signature(value)


def bind_row_identity_restatement(
    fact: SourceFact,
    component: str,
    learner_quote: str,
) -> RowIdentityRestatementReceipt | None:
    """Bind one exact component to its current native table row label.

    The projection is a comparison-only view.  The raw ``SourceFact.value``,
    component, and row label remain authoritative and are all independently
    digested in the receipt.
    """

    if not isinstance(fact, SourceFact):
        return None
    fact_id = _bounded_text(fact.fact_id, MAX_FACT_ID_CHARS)
    label = _bounded_text(fact.subject, MAX_LABEL_CHARS)
    attribute = _bounded_text(fact.attribute, MAX_LABEL_CHARS)
    value = _bounded_text(fact.value, MAX_SOURCE_VALUE_CHARS)
    locator_text = _bounded_text(fact.source_locator, MAX_LOCATOR_CHARS)
    raw_component = _bounded_text(component, MAX_COMPONENT_CHARS)
    quote = _bounded_text(learner_quote, MAX_SOURCE_VALUE_CHARS)
    if None in {fact_id, label, attribute, value, locator_text, raw_component, quote}:
        return None
    assert fact_id is not None and label is not None and value is not None
    assert locator_text is not None and raw_component is not None and quote is not None
    if (
        type(fact.confidence) is not float
        or not math.isfinite(fact.confidence)
        or fact.confidence != 1.0
        or fact.uncertainty != ""
        or _OPEN_SET.search(raw_component)
        or _OPEN_SET.search(label)
        or _LABEL_LIST.search(label)
    ):
        return None

    native_identity = _native_table_identity(fact)
    component_span = _unique_occurrence(value, raw_component)
    if native_identity is None or component_span is None:
        return None
    doc_id, source_revision, table, row, column = native_identity

    try:
        deictic = _deictic_reference(raw_component)
        if deictic is None:
            return None
        deictic_start, deictic_end, deictic_text, noun_lemma = deictic
        subject_noun = _subject_noun(label, noun_lemma)
        if subject_noun is None:
            return None
        subject_noun_start, subject_noun_end = subject_noun

        projected = raw_component[:deictic_start] + label + raw_component[deictic_end:]
        projection_subject_start = deictic_start
        projection_subject_end = projection_subject_start + len(label)
        if (
            component_preservation_issue(
                projected,
                quote,
                source_context=projected,
            )
            is not None
        ):
            return None
        projected_relations = _protected_relations(projected)
        quote_relations = _protected_relations(quote)
        if projected_relations is None or projected_relations != quote_relations:
            return None
        projected_pronouns = _pronoun_inventory(projected)
        quote_pronouns = _pronoun_inventory(quote)
        if (
            projected_pronouns is None
            or quote_pronouns is None
            or any(quote_pronouns[lemma] < count for lemma, count in projected_pronouns.items())
        ):
            return None
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None

    component_start, component_end = component_span
    fact_sha256 = _digest(asdict(fact))
    subject_identity = {
        "source_fact_id": fact_id,
        "raw_subject_label": label,
        "source_locator": locator_text,
        "doc_id": doc_id,
        "source_revision": source_revision,
        "table": table,
        "row": row,
        "column": column,
    }
    body = {
        "policy": TEACHING_ROW_IDENTITY_POLICY,
        "source_fact_sha256": fact_sha256,
        "component_start": component_start,
        "component_end": component_end,
        "component_sha256": sha256(raw_component.encode("utf-8")).hexdigest(),
        "subject_identity_sha256": _digest(subject_identity),
        "deictic_start": deictic_start,
        "deictic_end": deictic_end,
        "referenced_noun_lemma": noun_lemma,
        "projected_component_sha256": sha256(projected.encode("utf-8")).hexdigest(),
        "learner_quote_sha256": sha256(quote.encode("utf-8")).hexdigest(),
    }
    return RowIdentityRestatementReceipt(
        policy=TEACHING_ROW_IDENTITY_POLICY,
        source_fact_id=fact_id,
        source_fact_sha256=fact_sha256,
        source_value_sha256=sha256(value.encode("utf-8")).hexdigest(),
        raw_component=raw_component,
        component_start=component_start,
        component_end=component_end,
        component_sha256=sha256(raw_component.encode("utf-8")).hexdigest(),
        raw_subject_label=label,
        subject_label_sha256=sha256(label.encode("utf-8")).hexdigest(),
        subject_identity_sha256=_digest(subject_identity),
        source_locator=locator_text,
        source_locator_sha256=sha256(locator_text.encode("utf-8")).hexdigest(),
        doc_id=doc_id,
        source_revision=source_revision,
        table=table,
        row=row,
        column=column,
        deictic_start=deictic_start,
        deictic_end=deictic_end,
        deictic_text=deictic_text,
        referenced_noun_lemma=noun_lemma,
        subject_noun_start=subject_noun_start,
        subject_noun_end=subject_noun_end,
        projected_component=projected,
        projection_subject_start=projection_subject_start,
        projection_subject_end=projection_subject_end,
        projected_component_sha256=sha256(projected.encode("utf-8")).hexdigest(),
        learner_quote_sha256=sha256(quote.encode("utf-8")).hexdigest(),
        binding_sha256=_digest(body),
    )


def row_identity_restatement_valid(
    receipt: RowIdentityRestatementReceipt,
    fact: SourceFact,
    component: str,
    learner_quote: str,
) -> bool:
    """Rederive every receipt field from current immutable inputs."""

    if not isinstance(receipt, RowIdentityRestatementReceipt):
        return False
    try:
        return bind_row_identity_restatement(fact, component, learner_quote) == receipt
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False
