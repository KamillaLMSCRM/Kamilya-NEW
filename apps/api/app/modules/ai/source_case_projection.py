"""Exact zero-credit display projection for closed source case forks.

This module never decides semantics, truth, coverage or an answer key.  It only
proves that caller-proposed case selectors are exact current source spans and
that a complete, still-retained material fork may be hidden from the learner
display without hiding any answer-bearing bytes.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Literal, NoReturn

_MAX_ID_CHARS = 192
_MAX_SOURCE_CHARS = 65_536
_MAX_QUOTE_CHARS = 4_096
_MAX_SOURCES = 256
_MAX_TARGETS = 32
_MAX_BINDINGS = 32

_ROLES = frozenset({
    "actor",
    "recipient",
    "timing",
    "condition",
    "exception",
    "scope",
    "quantity",
    "operator",
})
_EFFECTS = frozenset({
    "none",
    "scopes_action",
    "changes_action",
    "changes_recipient",
    "changes_timing",
    "changes_outcome",
})
MATERIAL_BRANCH_EFFECTS = frozenset({
    "changes_action",
    "changes_recipient",
    "changes_timing",
    "changes_outcome",
})

CaseContextDomain = Literal["original", "context"]


@dataclass(frozen=True, slots=True)
class CaseProjectionSource:
    source_id: str
    text: str
    original_text: str


@dataclass(frozen=True, slots=True)
class CaseContextBinding:
    source_id: str
    quote: str
    start: int
    end: int
    domain: CaseContextDomain
    source_sha256: str
    original_sha256: str
    quote_sha256: str


@dataclass(frozen=True, slots=True)
class CaseProjectionQualification:
    facet_id: str
    role: str
    branch_effect: str
    binding: CaseContextBinding


@dataclass(frozen=True, slots=True)
class CaseProjectionTarget:
    target_id: str
    component: str
    source_id: str
    qualification_bindings: tuple[CaseProjectionQualification, ...]
    context_bindings: tuple[CaseContextBinding, ...]


@dataclass(frozen=True, slots=True)
class CaseScopeProjection:
    hidden_facet_ids: tuple[str, ...]
    given_bindings: tuple[CaseContextBinding, ...]
    not_semantic_approval: Literal[True] = True


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fail(code: str) -> NoReturn:
    raise ValueError("source_case_projection_" + code)


def _valid_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= _MAX_ID_CHARS
        and not any(character.isspace() for character in value)
    )


def _wordish(character: str) -> bool:
    category = unicodedata.category(character)
    return character == "_" or category[:1] in {"L", "M", "N"}


def _cuts_word(value: str, boundary: int) -> bool:
    return (
        0 < boundary < len(value)
        and _wordish(value[boundary - 1])
        and _wordish(value[boundary])
    )


def _metadata_start(source: CaseProjectionSource) -> int | None:
    if (
        not isinstance(source, CaseProjectionSource)
        or not _valid_id(source.source_id)
        or not isinstance(source.original_text, str)
        or not source.original_text
        or len(source.original_text) > _MAX_SOURCE_CHARS
        or not isinstance(source.text, str)
        or not source.text
        or len(source.text) > _MAX_SOURCE_CHARS
    ):
        _fail("source")
    if source.text == source.original_text:
        return None
    prefix = source.original_text + "\n"
    if not source.text.startswith(prefix) or len(source.text) == len(prefix):
        _fail("source_layout")
    return len(prefix)


def _unique_lexical_span(value: str, quote: str) -> tuple[int, int] | None:
    if (
        not isinstance(quote, str)
        or not quote
        or quote != quote.strip()
        or len(quote) > _MAX_QUOTE_CHARS
        or not any(_wordish(character) for character in quote)
    ):
        return None
    spans: list[tuple[int, int]] = []
    cursor = 0
    while (start := value.find(quote, cursor)) >= 0:
        end = start + len(quote)
        if not _cuts_word(value, start) and not _cuts_word(value, end):
            spans.append((start, end))
            if len(spans) > 1:
                return None
        cursor = start + 1
    return spans[0] if len(spans) == 1 else None


def bind_case_context(
    source: CaseProjectionSource,
    quote: str,
    *,
    within_quote: str | None = None,
) -> CaseContextBinding:
    """Bind a global unique span or an original duplicate inside a unique fork."""
    metadata_start = _metadata_start(source)
    span = _unique_lexical_span(source.text, quote)
    if span is None and within_quote is not None:
        container_span = _unique_lexical_span(source.original_text, within_quote)
        relative_span = _unique_lexical_span(within_quote, quote)
        original_span = _unique_lexical_span(source.original_text, quote)
        if (
            original_span is None
            and container_span is not None
            and relative_span is not None
        ):
            span = (
                container_span[0] + relative_span[0],
                container_span[0] + relative_span[1],
            )
    if span is None:
        _fail("not_unique_literal")
    start, end = span
    if end <= len(source.original_text):
        domain: CaseContextDomain = "original"
    elif metadata_start is not None and start >= metadata_start:
        domain = "context"
    else:
        _fail("cross_domain")
    return CaseContextBinding(
        source_id=source.source_id,
        quote=quote,
        start=start,
        end=end,
        domain=domain,
        source_sha256=_sha256(source.text),
        original_sha256=_sha256(source.original_text),
        quote_sha256=_sha256(quote),
    )


def _valid_binding(
    binding: object,
    source: CaseProjectionSource,
    *,
    within_quote: str | None = None,
) -> bool:
    if not isinstance(binding, CaseContextBinding) or binding.source_id != source.source_id:
        return False
    try:
        return bind_case_context(
            source,
            binding.quote,
            within_quote=within_quote,
        ) == binding
    except ValueError:
        return False


def _relative_unique_span(container: str, quote: str) -> tuple[int, int] | None:
    return _unique_lexical_span(container, quote)


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def _contains_lexical(value: str, quote: str) -> bool:
    cursor = 0
    while (start := value.find(quote, cursor)) >= 0:
        end = start + len(quote)
        if not _cuts_word(value, start) and not _cuts_word(value, end):
            return True
        cursor = start + 1
    return False


def _validated_source_map(
    sources: tuple[CaseProjectionSource, ...],
) -> dict[str, CaseProjectionSource] | None:
    if not isinstance(sources, tuple) or not 1 <= len(sources) <= _MAX_SOURCES:
        return None
    result: dict[str, CaseProjectionSource] = {}
    try:
        for source in sources:
            _metadata_start(source)
            if source.source_id in result:
                return None
            result[source.source_id] = source
    except ValueError:
        return None
    return result


def _validated_target(
    target: object,
    sources: dict[str, CaseProjectionSource],
) -> tuple[CaseProjectionSource, CaseProjectionQualification, tuple[int, int]] | None:
    if (
        not isinstance(target, CaseProjectionTarget)
        or not _valid_id(target.target_id)
        or not _valid_id(target.source_id)
        or target.source_id not in sources
        or not isinstance(target.component, str)
        or not target.component
        or target.component != target.component.strip()
        or len(target.component) > _MAX_QUOTE_CHARS
        or not isinstance(target.qualification_bindings, tuple)
        or not 1 <= len(target.qualification_bindings) <= _MAX_BINDINGS
        or not isinstance(target.context_bindings, tuple)
        or not 1 <= len(target.context_bindings) <= _MAX_BINDINGS
    ):
        return None
    source = sources[target.source_id]
    component_span = _unique_lexical_span(source.original_text, target.component)
    if component_span is None:
        return None

    fork_candidates: list[CaseProjectionQualification] = []
    seen_facets: set[str] = set()
    seen_bindings: set[tuple[int, int, str]] = set()
    for qualification in target.qualification_bindings:
        if (
            not isinstance(qualification, CaseProjectionQualification)
            or not _valid_id(qualification.facet_id)
            or qualification.facet_id in seen_facets
            or qualification.role not in _ROLES
            or qualification.branch_effect not in _EFFECTS
            or not _valid_binding(qualification.binding, source)
            or qualification.binding.domain != "original"
        ):
            return None
        seen_facets.add(qualification.facet_id)
        signature = (
            qualification.binding.start,
            qualification.binding.end,
            qualification.branch_effect,
        )
        if signature in seen_bindings:
            return None
        seen_bindings.add(signature)
        contains_component = _relative_unique_span(
            qualification.binding.quote,
            target.component,
        ) is not None
        if contains_component and (
            qualification.role == "actor"
            or qualification.branch_effect not in MATERIAL_BRANCH_EFFECTS
        ):
            return None
        if qualification.branch_effect in MATERIAL_BRANCH_EFFECTS:
            if qualification.role == "actor" or not contains_component:
                return None
            fork_candidates.append(qualification)
    if len(fork_candidates) != 1:
        return None
    return source, fork_candidates[0], component_span


def project_case_scope(
    target: CaseProjectionTarget,
    sources: tuple[CaseProjectionSource, ...],
    peers: tuple[CaseProjectionTarget, ...],
) -> CaseScopeProjection | None:
    """Project exact case selectors while retaining the complete fork as proof."""
    source_map = _validated_source_map(sources)
    if (
        source_map is None
        or not isinstance(peers, tuple)
        or not 1 <= len(peers) < _MAX_TARGETS
    ):
        return None
    group = (target, *peers)
    if len({row.target_id for row in group if isinstance(row, CaseProjectionTarget)}) != len(group):
        return None

    validated = [_validated_target(row, source_map) for row in group]
    if any(row is None for row in validated):
        return None
    checked = [row for row in validated if row is not None]
    if len({row.source_id for row in group}) != 1:
        return None
    fork_signatures = {
        (row[1].binding.quote, row[1].role, row[1].branch_effect)
        for row in checked
    }
    components = [row.component for row in group]
    if len(fork_signatures) != 1 or len(set(components)) != len(components):
        return None
    fork_quote, _fork_role, _fork_effect = next(iter(fork_signatures))

    answer_spans: list[tuple[int, int]] = []
    for component in components:
        span = _relative_unique_span(fork_quote, component)
        if span is None or any(_overlaps(span, existing) for existing in answer_spans):
            return None
        answer_spans.append(span)

    selector_signatures: set[tuple[str, ...]] = set()
    for row, (source, fork, _component_span) in zip(group, checked, strict=True):
        if fork.binding.quote != fork_quote:
            return None
        fork_start, fork_end = fork.binding.start, fork.binding.end
        seen_selectors: set[tuple[int, int, str]] = set()
        original_selectors = 0
        metadata_selectors = 0
        for binding in row.context_bindings:
            if not _valid_binding(binding, source, within_quote=fork_quote):
                return None
            if any(_contains_lexical(binding.quote, component) for component in components):
                return None  # Metadata is no more entitled to disclose an answer than original text.
            signature = (binding.start, binding.end, binding.domain)
            if signature in seen_selectors:
                return None
            seen_selectors.add(signature)
            if binding.domain == "original":
                if not fork_start <= binding.start < binding.end <= fork_end:
                    return None
                relative = (binding.start - fork_start, binding.end - fork_start)
                if binding.quote == fork_quote or any(
                    _overlaps(relative, answer_span) for answer_span in answer_spans
                ):
                    return None
                original_selectors += 1
            else:
                metadata_selectors += 1
        if original_selectors == 0:
            return None
        if source.text != source.original_text and metadata_selectors == 0:
            return None
        visible_signature = tuple(sorted(binding.quote for binding in row.context_bindings))
        if visible_signature in selector_signatures:
            return None
        selector_signatures.add(visible_signature)

    target_fork = checked[0][1]
    return CaseScopeProjection(
        hidden_facet_ids=(target_fork.facet_id,),
        given_bindings=target.context_bindings,
        not_semantic_approval=True,
    )
