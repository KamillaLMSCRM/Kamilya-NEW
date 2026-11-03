"""Document-level custody for one reviewed source working edition.

The recognized text remains immutable evidence.  A working edition is a
separate, receipt-bound view whose offsets address recognized Unicode text,
never PDF bytes, pages, or model-inferred locations.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.modules.ai.source_editorial import (
    SourceEditorialProposal,
    compile_source_editorial_proposal,
)
from app.modules.ai.source_editorial_model import (
    SourceEditorialRejection,
    SourceEditorialResult,
    SourceEditorialUnboundDiagnostic,
    restore_source_editorial_result,
    source_editorial_result_valid,
)

_SOURCE_REVISION = re.compile(r"document:[0-9a-f]{64}")
_CHUNK_PREFIX = "editorial-doc:"
_MAX_OPAQUE_ID_CHARS = 200
_MAX_SERIALIZED_METADATA_BYTES = 8 * 1024 * 1024
_DOCUMENT_FIELDS = frozenset(
    {"document_id", "source_revision", "recognized_text", "result"}
)
_RESULT_FIELDS = frozenset(
    {
        "author_wire",
        "proposal",
        "review_wire",
        "edition",
        "model_calls",
        "unbound_diagnostics",
        "independent_rejections",
        "result_receipt_sha256",
    }
)
_PROPOSAL_FIELDS = frozenset(
    {
        "source_id",
        "chunk_id",
        "raw_sha256",
        "patches",
        "unresolved",
        "proposal_sha256",
        "policy",
    }
)
_UNBOUND_FIELDS = frozenset(
    {
        "alias",
        "reported_excerpt",
        "category",
        "reason",
        "code",
        "not_a_source_span",
    }
)
_REJECTION_FIELDS = frozenset(
    {"patch_alias", "reason", "reviewer_id", "evidence_sha256", "proposal_sha256"}
)


@dataclass(frozen=True, slots=True)
class SourceEditorialDocument:
    """Immutable original identity paired with one validated working view."""

    document_id: str
    source_revision: str
    recognized_text: str
    result: SourceEditorialResult

    @property
    def working_text(self) -> str:
        return self.result.edition.working_text

    @property
    def editorial_revision(self) -> str:
        return "editorial:" + self.result.result_receipt_sha256


@dataclass(frozen=True, slots=True)
class SourceEditorialSpanMapping:
    """A conservative working-range address in immutable recognized text."""

    document_id: str
    source_revision: str
    editorial_revision: str
    raw_start: int
    raw_end: int
    working_start: int
    working_end: int
    raw_quote: str
    working_quote: str
    patch_aliases: tuple[str, ...]
    is_verbatim_original: bool


def _object(value: object, fields: frozenset[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(code)
    return value


def _document_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(_CHUNK_PREFIX + value) > _MAX_OPAQUE_ID_CHARS
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError("source_editorial_document_invalid_document_id")
    return value


def _source_revision(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_REVISION.fullmatch(value) is None:
        raise ValueError("source_editorial_document_invalid_revision")
    return value


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source_editorial_document_invalid_metadata") from exc


def _bounded_metadata(value: object) -> None:
    if len(_canonical_json(value).encode("utf-8")) > _MAX_SERIALIZED_METADATA_BYTES:
        raise ValueError("source_editorial_document_metadata_too_large")


def bind_source_editorial_document(
    *,
    document_id: str,
    source_revision: str,
    recognized_text: str,
    result: SourceEditorialResult,
) -> SourceEditorialDocument:
    """Bind an already reviewed result to one immutable document identity."""
    checked_id = _document_id(document_id)
    checked_revision = _source_revision(source_revision)
    chunk_id = _CHUNK_PREFIX + checked_id
    if not source_editorial_result_valid(
        result,
        source_text=recognized_text,
        source_id=checked_revision,
        chunk_id=chunk_id,
    ):
        raise ValueError("source_editorial_document_invalid_result")
    document = SourceEditorialDocument(
        document_id=checked_id,
        source_revision=checked_revision,
        recognized_text=recognized_text,
        result=result,
    )
    _bounded_metadata(asdict(document))
    return document


def source_editorial_document_valid(
    document: SourceEditorialDocument,
    *,
    document_id: str,
    source_revision: str,
    recognized_text: str | None = None,
) -> bool:
    """Rederive exact document/result identity without applying a new policy."""
    if not isinstance(document, SourceEditorialDocument):
        return False
    try:
        checked_id = _document_id(document_id)
        checked_revision = _source_revision(source_revision)
        if (
            document.document_id != checked_id
            or document.source_revision != checked_revision
            or (recognized_text is not None and document.recognized_text != recognized_text)
        ):
            return False
        if not source_editorial_result_valid(
            document.result,
            source_text=document.recognized_text,
            source_id=document.source_revision,
            chunk_id=_CHUNK_PREFIX + document.document_id,
        ):
            return False
        _bounded_metadata(asdict(document))
    except (TypeError, ValueError):
        return False
    return True


def _proposal_from_dict(
    value: object, *, source_text: str, source_revision: str, chunk_id: str,
) -> SourceEditorialProposal:
    stored = _object(
        value,
        _PROPOSAL_FIELDS,
        "source_editorial_document_invalid_proposal",
    )
    if stored.get("source_id") != source_revision or stored.get("chunk_id") != chunk_id:
        raise ValueError("source_editorial_document_invalid_proposal")
    patches = stored.get("patches")
    unresolved = stored.get("unresolved")
    if not isinstance(patches, list | tuple) or not isinstance(unresolved, list | tuple):
        raise ValueError("source_editorial_document_invalid_proposal")
    try:
        proposal = compile_source_editorial_proposal(
            source_text,
            source_id=source_revision,
            chunk_id=chunk_id,
            patches=patches,
            unresolved=unresolved,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source_editorial_document_invalid_proposal") from exc
    if _canonical_json(asdict(proposal)) != _canonical_json(stored):
        raise ValueError("source_editorial_document_proposal_changed")
    return proposal


def _unbound_diagnostics(value: object) -> tuple[SourceEditorialUnboundDiagnostic, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError("source_editorial_document_invalid_diagnostics")
    result = []
    for row in value:
        checked = _object(
            row,
            _UNBOUND_FIELDS,
            "source_editorial_document_invalid_diagnostics",
        )
        try:
            result.append(SourceEditorialUnboundDiagnostic(**checked))
        except TypeError as exc:
            raise ValueError("source_editorial_document_invalid_diagnostics") from exc
    return tuple(result)


def _independent_rejections(value: object) -> tuple[SourceEditorialRejection, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError("source_editorial_document_invalid_rejections")
    result = []
    for row in value:
        checked = _object(
            row,
            _REJECTION_FIELDS,
            "source_editorial_document_invalid_rejections",
        )
        try:
            result.append(SourceEditorialRejection(**checked))
        except TypeError as exc:
            raise ValueError("source_editorial_document_invalid_rejections") from exc
    return tuple(result)


def source_editorial_document_from_dict(value: object) -> SourceEditorialDocument:
    """Restore one saved result from compiled custody, with zero inference."""
    _bounded_metadata(value)
    stored = _object(
        value,
        _DOCUMENT_FIELDS,
        "source_editorial_document_invalid_shape",
    )
    document_id = _document_id(stored.get("document_id"))
    source_revision = _source_revision(stored.get("source_revision"))
    recognized_text = stored.get("recognized_text")
    if not isinstance(recognized_text, str):
        raise ValueError("source_editorial_document_invalid_recognized_text")
    result_value = stored.get("result")
    result_fields = (_RESULT_FIELDS | {"ingress_policy"}
                     if isinstance(result_value, Mapping) and "ingress_policy" in result_value else _RESULT_FIELDS)
    stored_result = _object(result_value, result_fields, "source_editorial_document_invalid_result")
    chunk_id = _CHUNK_PREFIX + document_id
    proposal = _proposal_from_dict(
        stored_result.get("proposal"),
        source_text=recognized_text,
        source_revision=source_revision,
        chunk_id=chunk_id,
    )
    diagnostics = _unbound_diagnostics(stored_result.get("unbound_diagnostics"))
    rejections = _independent_rejections(stored_result.get("independent_rejections"))
    try:
        result = restore_source_editorial_result(
            recognized_text,
            source_id=source_revision,
            chunk_id=chunk_id,
            proposal=proposal,
            author_wire=stored_result.get("author_wire"),
            review_wire=stored_result.get("review_wire"),
            unbound_diagnostics=diagnostics,
            independent_rejections=rejections,
            ingress_policy=stored_result.get("ingress_policy") if "ingress_policy" in stored_result else None,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source_editorial_document_invalid_result") from exc
    if _canonical_json(asdict(result)) != _canonical_json(stored_result):
        raise ValueError("source_editorial_document_result_changed")
    return bind_source_editorial_document(
        document_id=document_id,
        source_revision=source_revision,
        recognized_text=recognized_text,
        result=result,
    )


def map_source_editorial_span(
    document: SourceEditorialDocument,
    working_start: int,
    working_end: int,
) -> SourceEditorialSpanMapping:
    """Map a nonempty working range to a conservative recognized-text span.

    Any overlap with an editorial replacement maps the whole original patch.
    Therefore a partial replacement can never be reported as verbatim source.
    """
    if not source_editorial_document_valid(
        document,
        document_id=getattr(document, "document_id", ""),
        source_revision=getattr(document, "source_revision", ""),
        recognized_text=getattr(document, "recognized_text", None),
    ):
        raise ValueError("source_editorial_document_invalid")
    if (
        type(working_start) is not int
        or type(working_end) is not int
        or not 0 <= working_start < working_end <= len(document.working_text)
    ):
        raise ValueError("source_editorial_document_invalid_span")
    overlaps = tuple(
        span
        for span in document.result.edition.span_map
        if span.working_start < working_end and working_start < span.working_end
    )
    if not overlaps:
        raise ValueError("source_editorial_document_invalid_span")
    raw_ranges: list[tuple[int, int]] = []
    aliases: list[str] = []
    for span in overlaps:
        left = max(working_start, span.working_start)
        right = min(working_end, span.working_end)
        if span.origin == "original":
            raw_ranges.append(
                (
                    span.raw_start + left - span.working_start,
                    span.raw_start + right - span.working_start,
                )
            )
        else:
            raw_ranges.append((span.raw_start, span.raw_end))
            if span.patch_alias is not None and span.patch_alias not in aliases:
                aliases.append(span.patch_alias)
    raw_start = raw_ranges[0][0]
    raw_end = raw_ranges[-1][1]
    raw_quote = document.recognized_text[raw_start:raw_end]
    working_quote = document.working_text[working_start:working_end]
    patch_aliases = tuple(aliases)
    return SourceEditorialSpanMapping(
        document_id=document.document_id,
        source_revision=document.source_revision,
        editorial_revision=document.editorial_revision,
        raw_start=raw_start,
        raw_end=raw_end,
        working_start=working_start,
        working_end=working_end,
        raw_quote=raw_quote,
        working_quote=working_quote,
        patch_aliases=patch_aliases,
        is_verbatim_original=not patch_aliases and raw_quote == working_quote,
    )
