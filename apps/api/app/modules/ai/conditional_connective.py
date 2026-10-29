"""Exact custody for one Russian conditional-connective restatement.

This module proves only that an anchored ``в случае если C`` component and an
anchored ``если C`` learner quote have the same complete, ordered ``C`` after
bounded horizontal-space normalization.  It does not prove source truth,
semantic entailment, target coverage, or learner readiness.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.assessment_preservation import (
    canonical_option_typography,
    unsupported_option_spacing,
)
from app.modules.ai.source_layout import SOURCE_HORIZONTAL_SPACE

CONDITIONAL_CONNECTIVE_POLICY = "conditional-connective-v1"
MAX_CONDITIONAL_CONNECTIVE_CHARS = 4_096

_HSPACE = f"[{re.escape(SOURCE_HORIZONTAL_SPACE)}]"
_SOURCE_SHAPE = re.compile(
    rf"\A(?P<leading>{_HSPACE}*)"
    rf"(?P<connector>в{_HSPACE}+случае{_HSPACE}*,?{_HSPACE}+если)"
    rf"(?P<separator>{_HSPACE}+)(?P<tail>.*?)(?P<trailing>{_HSPACE}*)\Z",
    re.IGNORECASE,
)
_LEARNER_SHAPE = re.compile(
    rf"\A(?P<leading>{_HSPACE}*)"
    rf"(?P<connector>если)(?P<separator>{_HSPACE}+)"
    rf"(?P<tail>.*?)(?P<trailing>{_HSPACE}*)\Z",
    re.IGNORECASE,
)
_NESTED_IF = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])если(?![A-Za-zА-Яа-яЁё])",
    re.IGNORECASE,
)
_LINE_BREAKS = frozenset("\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _body_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _raw_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConditionalConnectiveReceipt:
    """Raw-addressed, rederivable grammatical-form receipt."""

    policy: str
    source_sha256: str
    learner_sha256: str
    source_connector_start: int
    source_connector_end: int
    source_tail_start: int
    source_tail_end: int
    learner_connector_start: int
    learner_connector_end: int
    learner_tail_start: int
    learner_tail_end: int
    source_connector_sha256: str
    source_tail_sha256: str
    learner_connector_sha256: str
    learner_tail_sha256: str
    canonical_tail_sha256: str
    not_semantic_approval: bool
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class _ParsedConditional:
    connector_start: int
    connector_end: int
    tail_start: int
    tail_end: int
    connector: str
    tail: str
    canonical_tail: str


def _parse(value: Any, *, source: bool) -> _ParsedConditional | None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_CONDITIONAL_CONNECTIVE_CHARS
        or unsupported_option_spacing(value)
        or any(character in _LINE_BREAKS for character in value)
    ):
        return None
    match = (_SOURCE_SHAPE if source else _LEARNER_SHAPE).fullmatch(value)
    if match is None:
        return None
    tail = match.group("tail")
    canonical_tail = canonical_option_typography(tail)
    if not canonical_tail or canonical_tail != canonical_tail.strip():
        return None
    if _NESTED_IF.search(canonical_tail):
        return None
    return _ParsedConditional(
        connector_start=match.start("connector"),
        connector_end=match.end("connector"),
        tail_start=match.start("tail"),
        tail_end=match.end("tail"),
        connector=match.group("connector"),
        tail=tail,
        canonical_tail=canonical_tail,
    )


def _receipt_body(
    source_component: str,
    learner_quote: str,
    source: _ParsedConditional,
    learner: _ParsedConditional,
) -> dict[str, Any]:
    return {
        "policy": CONDITIONAL_CONNECTIVE_POLICY,
        "source_sha256": _raw_sha256(source_component),
        "learner_sha256": _raw_sha256(learner_quote),
        "source_connector_start": source.connector_start,
        "source_connector_end": source.connector_end,
        "source_tail_start": source.tail_start,
        "source_tail_end": source.tail_end,
        "learner_connector_start": learner.connector_start,
        "learner_connector_end": learner.connector_end,
        "learner_tail_start": learner.tail_start,
        "learner_tail_end": learner.tail_end,
        "source_connector_sha256": _raw_sha256(source.connector),
        "source_tail_sha256": _raw_sha256(source.tail),
        "learner_connector_sha256": _raw_sha256(learner.connector),
        "learner_tail_sha256": _raw_sha256(learner.tail),
        "canonical_tail_sha256": _raw_sha256(source.canonical_tail),
        "not_semantic_approval": True,
    }


def conditional_connective_receipt(
    source_component: str,
    learner_quote: str,
) -> ConditionalConnectiveReceipt | None:
    """Prove only the anchored complex-to-simple connector realization."""

    source = _parse(source_component, source=True)
    learner = _parse(learner_quote, source=False)
    if (
        source is None
        or learner is None
        or source.canonical_tail != learner.canonical_tail
    ):
        return None
    body = _receipt_body(source_component, learner_quote, source, learner)
    return ConditionalConnectiveReceipt(
        **body,
        receipt_sha256=_body_sha256(body),
    )


def conditional_connective_receipt_valid(
    receipt: Any,
    *,
    source_component: str,
    learner_quote: str,
) -> bool:
    """Rederive the complete raw-addressed receipt; never trust a boolean hint."""

    if not isinstance(receipt, ConditionalConnectiveReceipt):
        return False
    expected = conditional_connective_receipt(source_component, learner_quote)
    return expected is not None and asdict(receipt) == asdict(expected)
