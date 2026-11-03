"""Typed compiler-copy boundary codec; literal custody never grants meaning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.modules.ai.evidence_engine.models import SourceFact
from app.modules.ai.source_assessment_graph import SourceGraphError, _fields, _quote
from app.modules.ai.source_frame_patch import _validate_json

POLICY = "typed-source-quote-wire-v1"
_SCHEMA = "source_frame_quote_wire_schema"
_RESOURCES = "source_frame_quote_wire_resources"
_CUSTODY = "nonliteral_ambiguous_or_foreign_quote"
_COMMON = {"handle", "kind", "ref", "label", "context", "bindings"}
_EXTRA = {"decision": {"dimension", "answer"}, "checklist": {"dimension", "owner", "leaves"},
          "timing_case": {"fork", "action", "purposes", "branches"}}
Path = tuple[str | int, ...]


class _QuoteCustodyError(SourceGraphError):
    """A strict custody refusal retaining its complete negative diagnostics."""

    def __init__(self, findings: list[dict[str, Any]]):
        super().__init__(findings[0]["code"])
        self.findings = deepcopy(findings)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pointer(path: Path) -> str:
    return "/" + "/".join(str(item) for item in path)


def _unique(text: str, quote: str) -> int:
    start = text.find(quote)
    if not quote or start < 0 or text.find(quote, start + 1) >= 0:
        raise SourceGraphError(_CUSTODY)
    return start


def _at(raw: Any, path: Path) -> Any:
    for key in path:
        raw = raw[key]
    return raw


def _raw_quote(value: Any, maximum: int) -> None:
    if not isinstance(value, str):
        raise SourceGraphError(_SCHEMA)
    if len(value) > maximum:
        raise SourceGraphError(_RESOURCES)


def _text_row(row: Any, keys: set[str]) -> None:
    _fields(row, keys, _SCHEMA)
    if any(not isinstance(value, str) for value in row.values()):
        raise SourceGraphError(_SCHEMA)


def inspect_frame_quotes(
    raw: Any, refs: Mapping[str, SourceFact], primary_refs: set[str], *, applications: bool,
) -> dict[str, Any]:
    """Inspect every literal after validating the original closed wire.

    Failed literals remain raw diagnostic data. Selectors require successful
    parent-fork custody; no diagnostic result grants compiler or edit authority.
    """
    _validate_json(raw)
    if len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 256 * 1024:
        raise SourceGraphError(_RESOURCES)
    _fields(raw, {"frames", "qualifiers"}, _SCHEMA)
    if (not isinstance(raw["frames"], list) or not 1 <= len(raw["frames"]) <= 96
            or not isinstance(raw["qualifiers"], list) or len(raw["qualifiers"]) > 96):
        raise SourceGraphError(_RESOURCES)
    if (not isinstance(refs, Mapping) or not isinstance(primary_refs, set) or not primary_refs
            or not primary_refs <= set(refs) or any(not isinstance(fact, SourceFact)
                or not isinstance(fact.value, str) or not isinstance(fact.fact_id, str) for fact in refs.values())):
        raise SourceGraphError(_CUSTODY)
    literals: list[tuple[Path, str, Path | None]] = []

    def add(path: Path, ref: Any, maximum: int, fork_path: Path | None = None) -> None:
        _raw_quote(_at(raw, path), maximum)
        if not isinstance(ref, str):
            raise SourceGraphError(_SCHEMA)
        literals.append((path, ref, fork_path))

    for index, row in enumerate(raw["qualifiers"]):
        _text_row(row, {"handle", "ref", "quote"} if applications else {"handle", "ref", "quote", "role", "effect"})
        add(("qualifiers", index, "quote"), row["ref"], 65536)
    total_bindings = 0
    for index, frame in enumerate(raw["frames"]):
        if not isinstance(frame, dict) or not isinstance(frame.get("kind"), str) or frame["kind"] not in _EXTRA:
            raise SourceGraphError(_SCHEMA)
        _fields(frame, _COMMON | _EXTRA[frame["kind"]], _SCHEMA)
        if (any(not isinstance(frame[key], str) for key in ("handle", "kind", "ref", "label"))
                or not frame["label"].strip() or len(frame["label"]) > 240):
            raise SourceGraphError(_SCHEMA)
        if not isinstance(frame["context"], list) or len(frame["context"]) > 16:
            raise SourceGraphError(_RESOURCES)
        for row in frame["context"]:
            _text_row(row, {"ref", "text"})
            if not row["text"].strip():
                raise SourceGraphError(_RESOURCES)
        if not isinstance(frame["bindings"], list) or len(frame["bindings"]) > 96:
            raise SourceGraphError(_RESOURCES)
        total_bindings += len(frame["bindings"])
        if applications:
            for row in frame["bindings"]:
                _fields(row, {"evidence_handle", "kind", "predecessor_frame"}, _SCHEMA)
                if (not isinstance(row["evidence_handle"], str) or not isinstance(row["kind"], str)
                        or not (row["predecessor_frame"] is None or isinstance(row["predecessor_frame"], str))):
                    raise SourceGraphError(_SCHEMA)
        elif any(not isinstance(binding, str) for binding in frame["bindings"]):
            raise SourceGraphError(_SCHEMA)
        base = ("frames", index)
        if frame["kind"] in {"decision", "checklist"} and not isinstance(frame["dimension"], str):
            raise SourceGraphError(_SCHEMA)
        if frame["kind"] == "decision":
            add((*base, "answer"), frame["ref"], 320)
        elif frame["kind"] == "checklist":
            _text_row(frame["owner"], {"quote", "role", "effect"})
            add((*base, "owner", "quote"), frame["ref"], 65536)
            if not isinstance(frame["leaves"], list) or not 1 <= len(frame["leaves"]) <= 12:
                raise SourceGraphError(_RESOURCES)
            for leaf in range(len(frame["leaves"])):
                add((*base, "leaves", leaf), frame["ref"], 320)
        else:
            declared_fork_path: Path = (*base, "fork")
            add(declared_fork_path, frame["ref"], 65536)
            _text_row(frame["action"], {"label", "answer"})
            add((*base, "action", "answer"), frame["ref"], 320)
            if not isinstance(frame["purposes"], list) or len(frame["purposes"]) > 12:
                raise SourceGraphError(_RESOURCES)
            for purpose, row in enumerate(frame["purposes"]):
                _text_row(row, {"label", "answer"})
                add((*base, "purposes", purpose, "answer"), frame["ref"], 320)
            if not isinstance(frame["branches"], list) or not 2 <= len(frame["branches"]) <= 12:
                raise SourceGraphError(_RESOURCES)
            for branch, row in enumerate(frame["branches"]):
                _text_row(row, {"label", "answer", "selector"})
                add((*base, "branches", branch, "answer"), frame["ref"], 320)
                add((*base, "branches", branch, "selector"), frame["ref"], 65536, declared_fork_path)
    if applications and total_bindings > 512:
        raise SourceGraphError(_RESOURCES)

    canonical = deepcopy(raw)
    receipts: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    failed_paths: set[Path] = set()
    for path, ref, fork_path in literals:
        original = _at(raw, path)
        value = original.strip()
        source = refs.get(ref)
        dependency_failed = fork_path is not None and fork_path in failed_paths
        try:
            if dependency_failed:
                raise SourceGraphError("source_frame_quote_fork_dependency")
            if ref not in primary_refs or source is None:
                raise SourceGraphError(_CUSTODY)
            if fork_path is None:
                _quote(ref, original, refs)
                _quote(ref, value, refs)
                start, end_start = _unique(source.value, original), _unique(source.value, value)
            else:
                raw_fork, canonical_fork = _at(raw, fork_path), _at(canonical, fork_path)
                fork_start = _unique(source.value, raw_fork)
                canonical_fork_start = _unique(source.value, canonical_fork)
                start = fork_start + _unique(raw_fork, original)
                end_start = canonical_fork_start + _unique(canonical_fork, value)
            if not value or end_start != start + len(original) - len(original.lstrip()):
                raise SourceGraphError(_CUSTODY)
        except SourceGraphError as exc:
            finding: dict[str, Any] = {"code": str(exc), "json_path": _pointer(path), "ref": ref,
                "original_quote_sha256": _sha(original), "original_quote_length": len(original),
                "semantic_approval": False}
            if source is not None:
                finding["source_sha256"] = _sha(source.value)
            if dependency_failed:
                assert fork_path is not None
                finding["dependency_json_path"] = _pointer(fork_path)
            findings.append(finding)
            failed_paths.add(path)
            if len(findings) > 4096:
                raise SourceGraphError(_RESOURCES) from exc
            continue
        assert source is not None
        _at(canonical, path[:-1])[path[-1]] = value
        if original == value:
            continue
        receipt = {"policy": POLICY, "json_path": _pointer(path), "ref": ref, "source_id": source.fact_id,
            "source_sha256": _sha(source.value), "original_quote_sha256": _sha(original), "canonical_quote_sha256": _sha(value),
            "original_span": {"start": start, "end": start + len(original)},
            "canonical_span": {"start": end_start, "end": end_start + len(value)},
            "custody": "global_unique" if fork_path is None else "fork_local_unique", "semantic_approval": False}
        if fork_path is not None:
            receipt.update(fork_json_path=_pointer(fork_path), original_fork_sha256=_sha(_at(raw, fork_path)),
                           canonical_fork_sha256=_sha(_at(canonical, fork_path)))
        receipts.append(receipt)
        if len(receipts) > 4096:
            raise SourceGraphError(_RESOURCES)
    return {"canonical_wire": canonical, "quote_normalizations": tuple(receipts), "findings": findings,
            "complete": not findings, "semantic_approval": False}


def normalize_frame_quotes(
    raw: Any, refs: Mapping[str, SourceFact], primary_refs: set[str], *, applications: bool,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Return only a complete compiler copy; inspection findings never waive it."""
    inspected = inspect_frame_quotes(raw, refs, primary_refs, applications=applications)
    if not inspected["complete"]:
        raise _QuoteCustodyError(inspected["findings"])
    return inspected["canonical_wire"], inspected["quote_normalizations"]
