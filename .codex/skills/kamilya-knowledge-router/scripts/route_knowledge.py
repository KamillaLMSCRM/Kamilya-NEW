#!/usr/bin/env python3
"""Pure local routing over one sanitized, ephemeral, cited-record envelope."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any, TextIO

SCHEMA_FIELDS = {"schema_version", "project", "query", "limit", "records"}
RECORD_FIELDS = {
    "record_id", "project", "source_kind", "path", "citation", "evidence_label",
    "text", "candidate_id", "activation_state", "sensitive",
}
ALLOWED_PROJECTS = {"Kamilya-NEW", "kamilya-landing"}
KIND_LABELS = {
    "canonical_doc": {"GIT-DERIVED"},
    "graphify": {"GRAPH-DERIVED"},
    "source": {"GIT-DERIVED"},
    "test": {"GIT-DERIVED"},
    "migration": {"GIT-DERIVED"},
    "git": {"GIT-DERIVED"},
    "hermes_candidate": {"NOT VERIFIED"},
}
CANONICAL_DOCS = {
    "AGENTS.md", "ERRORS.md", "PROJECT.md", "docs/PROJECT-CONTEXT.md",
    "docs/PRODUCTION_READINESS.md", "docs/PRODUCT_BACKLOG.md",
    "docs/CODEX_HANDOFF.md",
}
RECORD_ID_RE = re.compile(r"^KR-[0-9a-f]{16,64}$")
CANDIDATE_ID_RE = re.compile(r"^LC-[0-9a-f]{20}$")
GIT_PATH_RE = re.compile(r"^git:commit/[0-9a-f]{40}$")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
SECRET_RE = re.compile(r"(?i)(password|passwd|secret|api[_-]?key|authorization|cookie)\s*[:=]")
EMAIL_RE = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()\-]{7,}\d)(?!\w)")
MAX_INPUT_BYTES = 1024 * 1024
MAX_RECORDS = 500
MAX_TEXT_CHARS = 4000
MAX_QUERY_CHARS = 500
MAX_RESULTS = 20
MAX_CITATION_CHARS = 300
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class RouterContractError(ValueError):
    """Raised when an input crosses the local knowledge-router contract."""


@dataclass(frozen=True, slots=True)
class RoutedResult:
    record_id: str
    source_kind: str
    path: str
    citation: str
    evidence_label: str
    text: str
    score: float
    candidate_id: str | None
    activation_state: str | None


def _unsafe_text(value: str) -> bool:
    return bool(SECRET_RE.search(value) or EMAIL_RE.search(value) or PHONE_RE.search(value))


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in TOKEN_RE.findall(value) if len(token) > 1)


def _safe_relative_path(path: str) -> bool:
    return (
        bool(path)
        and "\\" not in path
        and not path.startswith(("/", ".", "~"))
        and ":" not in path
        and ".." not in path.split("/")
    )


def _path_matches_kind(kind: str, path: str) -> bool:
    if kind == "git":
        return bool(GIT_PATH_RE.fullmatch(path))
    if kind == "graphify":
        return (
            path.startswith(".graphify/")
            and ".." not in path.split("/")
            and "\\" not in path
            and path.endswith((".json", ".md"))
        )
    if kind == "hermes_candidate":
        return (
            path.startswith(".codex/skills/kamilya-learning-candidate-triage/")
            and ".." not in path.split("/")
            and "\\" not in path
        )
    if not _safe_relative_path(path):
        return False
    if kind == "canonical_doc":
        return path in CANONICAL_DOCS or path.startswith("docs/adr/")
    if kind == "source":
        return path.startswith(("apps/", "src/")) and path.endswith((".py", ".ts", ".tsx", ".js", ".sql"))
    if kind == "test":
        return ("/tests/" in f"/{path}" or path.startswith("tests/")) and path.endswith((".py", ".ts", ".tsx", ".js"))
    if kind == "migration":
        return path.startswith("apps/api/alembic/versions/") and path.endswith(".py")
    return False


def _validate_record(raw: Any, project: str, item_number: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != RECORD_FIELDS:
        raise RouterContractError(f"record_{item_number}_schema_invalid")
    if raw["sensitive"] is not False:
        raise RouterContractError(f"record_{item_number}_sensitive_forbidden")
    string_fields = RECORD_FIELDS - {"candidate_id", "activation_state", "sensitive"}
    if any(not isinstance(raw[field], str) for field in string_fields):
        raise RouterContractError(f"record_{item_number}_string_required")
    if raw["project"] != project:
        raise RouterContractError(f"record_{item_number}_project_scope_mismatch")
    if raw["source_kind"] not in KIND_LABELS:
        raise RouterContractError(f"record_{item_number}_source_kind_invalid")
    if raw["evidence_label"] not in KIND_LABELS[raw["source_kind"]]:
        raise RouterContractError(f"record_{item_number}_evidence_label_invalid")
    if not RECORD_ID_RE.fullmatch(raw["record_id"]):
        raise RouterContractError(f"record_{item_number}_id_invalid")
    if not _path_matches_kind(raw["source_kind"], raw["path"]):
        raise RouterContractError(f"record_{item_number}_path_invalid")
    citation_pattern = re.compile(
        rf"^{re.escape(raw['path'])}:[1-9][0-9]*(?::[1-9][0-9]*)?$"
    )
    if (
        len(raw["citation"]) > MAX_CITATION_CHARS
        or CONTROL_RE.search(raw["citation"])
        or _unsafe_text(raw["citation"])
        or not citation_pattern.fullmatch(raw["citation"])
    ):
        raise RouterContractError(f"record_{item_number}_citation_invalid")
    if not raw["text"] or len(raw["text"]) > MAX_TEXT_CHARS or _unsafe_text(raw["text"]):
        raise RouterContractError(f"record_{item_number}_text_unsafe")
    if raw["source_kind"] == "hermes_candidate":
        if (
            not isinstance(raw["candidate_id"], str)
            or not CANDIDATE_ID_RE.fullmatch(raw["candidate_id"])
            or raw["activation_state"] != "CANDIDATE_ONLY"
        ):
            raise RouterContractError(f"record_{item_number}_candidate_must_remain_inert")
    elif raw["candidate_id"] is not None or raw["activation_state"] is not None:
        raise RouterContractError(f"record_{item_number}_candidate_fields_forbidden")
    return dict(raw)


def validate_request(raw: Any) -> tuple[str, str, int, list[dict[str, Any]]]:
    if not isinstance(raw, dict) or set(raw) != SCHEMA_FIELDS:
        raise RouterContractError("request_schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise RouterContractError("schema_version_invalid")
    if raw["project"] not in ALLOWED_PROJECTS:
        raise RouterContractError("project_scope_forbidden")
    if (
        not isinstance(raw["query"], str)
        or not raw["query"].strip()
        or len(raw["query"]) > MAX_QUERY_CHARS
        or _unsafe_text(raw["query"])
    ):
        raise RouterContractError("query_unsafe")
    if type(raw["limit"]) is not int or not 1 <= raw["limit"] <= MAX_RESULTS:
        raise RouterContractError("limit_invalid")
    if not isinstance(raw["records"], list) or len(raw["records"]) > MAX_RECORDS:
        raise RouterContractError("records_invalid")
    records = [
        _validate_record(record, raw["project"], index)
        for index, record in enumerate(raw["records"], start=1)
    ]
    if len({record["record_id"] for record in records}) != len(records):
        raise RouterContractError("record_ids_must_be_unique")
    return raw["project"], raw["query"].strip(), raw["limit"], records


def route(raw: Any) -> dict[str, Any] | None:
    """Validate and rank an ephemeral request without side effects."""
    project, query, limit, records = validate_request(raw)
    query_terms = set(_tokens(query))
    ranked: list[RoutedResult] = []
    for record in records:
        text_terms = _tokens(record["text"])
        overlap = sum(1 for term in text_terms if term in query_terms)
        if overlap == 0:
            continue
        score = overlap / math.sqrt(max(1, len(text_terms)))
        ranked.append(RoutedResult(
            record_id=record["record_id"], source_kind=record["source_kind"],
            path=record["path"], citation=record["citation"],
            evidence_label=record["evidence_label"], text=record["text"],
            score=score, candidate_id=record["candidate_id"],
            activation_state=record["activation_state"],
        ))
    ranked.sort(key=lambda item: (-item.score, item.path, item.citation, item.record_id))
    if not ranked:
        return None
    selected = ranked[:limit]
    return {
        "schema_version": 1,
        "status": "RESULTS",
        "project": project,
        "query_hash": f"QH-{hashlib.sha256(query.encode('utf-8')).hexdigest()[:20]}",
        "result_count": len(selected),
        "truncated": len(ranked) > limit,
        "results": [asdict(item) for item in selected],
        "authority": "NONE; EVIDENCE MUST BE VERIFIED AT SOURCE",
    }


def read_request(stream: TextIO | None = None) -> Any:
    if stream is None:
        payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(payload) > MAX_INPUT_BYTES:
            raise RouterContractError("input_size_exceeded")
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RouterContractError("input_utf8_required") from exc
    else:
        text = stream.read(MAX_INPUT_BYTES + 1)
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_INPUT_BYTES:
            raise RouterContractError("input_size_exceeded")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterContractError("input_json_invalid") from exc


def main(stdin: TextIO | None = None) -> int:
    try:
        result = route(read_request(stdin))
    except RouterContractError as exc:
        print(f"kamilya-knowledge-router: {exc}", file=sys.stderr)
        return 2
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
