"""Deterministic reconstruction and command validation for source review."""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TEXT = 1_000_000
POLICY = "human-source-editorial-review-v1"
SOURCE_PINS = "source_editorial_snapshots"


def text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class ReviewConflictError(ValueError):
    """The requested change does not apply to the current review."""


@dataclass(frozen=True, slots=True)
class ApprovedEditorialDocument:
    document_id: str
    source_revision: str
    approval_id: str
    recognized_text: str = field(repr=False)
    working_text: str = field(repr=False)
    working_sha256: str
    spans: tuple[dict[str, Any], ...] = field(repr=False)
    fidelity: dict[str, Any] = field(repr=False)

    @property
    def editorial_revision(self) -> str:
        return "editorial:" + self.working_sha256

    def valid(self, *, document_id: str, source_revision: str) -> bool:
        if (self.document_id != document_id or self.source_revision != source_revision
                or text_hash(self.working_text) != self.working_sha256):
            return False
        try:
            edits = [
                {"start": row["raw_start"], "end": row["raw_end"], "id": row["item_id"],
                 "before": self.recognized_text[row["raw_start"]:row["raw_end"]],
                 "after": self.working_text[row["working_start"]:row["working_end"]]}
                for row in self.spans if row["item_id"] is not None
            ]
            text, spans = render_text(self.recognized_text, edits)
            return text == self.working_text and tuple(spans) == self.spans
        except (TypeError, KeyError, ReviewConflictError):
            return False


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    request_id: UUID
    action: Literal["start", "resolve", "reopen_issue", "undo_auto", "approve", "reopen", "add_edit"]
    item_id: str | None = Field(default=None, min_length=1, max_length=80)
    decision: Literal["replace", "keep"] | None = None
    replacement: str | None = Field(default=None, min_length=1, max_length=5000)
    reason: str | None = Field(default=None, min_length=3, max_length=1500)
    quote: str | None = Field(default=None, min_length=1, max_length=5000)

    @model_validator(mode="after")
    def validate_fields(self) -> "ReviewCommand":
        if self.action in {"resolve", "reopen_issue", "undo_auto"}:
            if not self.item_id or not self.reason:
                raise ValueError("item and reason required")
        elif self.action == "add_edit":
            if self.item_id is not None or not self.reason or not self.quote or not self.replacement or self.decision:
                raise ValueError("exact quote, replacement and reason required for a manual edit")
        elif self.item_id is not None or self.reason is not None:
            raise ValueError("unexpected item or reason")
        if self.action == "resolve":
            if self.decision is None or (self.replacement is not None) != (self.decision == "replace"):
                raise ValueError("an explicit decision and matching replacement are required")
        elif self.action != "add_edit" and (self.decision is not None or self.replacement is not None or self.quote is not None):
            raise ValueError("unexpected decision")
        if self.replacement and ("\x00" in self.replacement or "\r" in self.replacement):
            raise ValueError("invalid replacement")
        return self


@dataclass
class ReviewState:
    revision: int = 0
    status: str = "not_started"
    original: str = field(default="", repr=False)
    issues: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    automatic: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    disabled_auto: set[str] = field(default_factory=set)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    approval: dict[str, Any] | None = field(default=None, repr=False)
    fidelity: dict[str, Any] = field(default_factory=dict, repr=False)
    error: str | None = None

    def apply(self, sequence: int, kind: str, payload: dict[str, Any]) -> None:
        if sequence != self.revision + 1:
            raise ReviewConflictError("source_review_history_invalid")
        self.revision = sequence
        if kind == "queued":
            self.status, self.error = "queued", None
        elif kind in {"running", "analysis_block"}:
            self.status = "running"
        elif kind == "failed":
            self.status, self.error = "failed", payload["code"]
        elif kind == "analyzed":
            self.original = payload["original"]
            self.fidelity = payload.get("fidelity", {})
            self.issues = {row["id"]: row for row in payload["issues"]}
            self.automatic = {row["id"]: row for row in payload["automatic"]}
            self.decisions.clear()
            self.disabled_auto.clear()
            self.status, self.error = "in_review", None
        elif kind == "resolved":
            if "manual_issue" in payload:
                self.issues[payload["item_id"]] = payload["manual_issue"]
            self.decisions[payload["item_id"]] = payload
        elif kind == "issue_reopened":
            self.decisions.pop(payload["item_id"])
        elif kind == "auto_undone":
            self.disabled_auto.add(payload["item_id"])
        elif kind == "approved":
            self.status, self.approval = "approved", payload
        elif kind == "reopened":
            self.status, self.approval = "in_review", None
        else:
            raise ReviewConflictError("source_review_history_invalid")

    def active_edits(self) -> list[dict[str, Any]]:
        return [
            *(row for key, row in self.automatic.items() if key not in self.disabled_auto),
            *(row for row in self.decisions.values() if row["decision"] == "replace"),
        ]

    def working(self) -> tuple[str, list[dict[str, Any]]]:
        return render_text(self.original, self.active_edits())

    def plan(self, command: ReviewCommand) -> tuple[str, dict[str, Any]]:
        if command.expected_revision != self.revision:
            raise ReviewConflictError("source_review_revision_conflict")
        if command.action == "start" and self.status in {"not_started", "failed"}:
            return "queued", {}
        if command.action == "reopen" and self.status == "approved":
            return "reopened", {}
        if self.status != "in_review":
            raise ReviewConflictError("source_review_action_not_available")
        item = command.item_id or ""
        if command.action == "approve":
            if self.issues.keys() - self.decisions.keys():
                raise ReviewConflictError("source_review_questions_open")
            working, spans = self.working()
            return "approved", {"working": working, "working_sha256": text_hash(working),
                                "original_sha256": text_hash(self.original), "spans": spans,
                                "policy": POLICY}
        if command.action == "undo_auto" and item in self.automatic and item not in self.disabled_auto:
            row = self.automatic[item]
            return "auto_undone", {"item_id": item, "start": row["start"], "end": row["end"],
                                   "before": row["after"], "after": row["before"], "reason": command.reason}
        if command.action == "reopen_issue" and item in self.decisions:
            row = self.decisions[item]
            return "issue_reopened", {"item_id": item, "start": row["start"], "end": row["end"],
                                      "before": row["after"], "after": row["before"], "reason": command.reason}
        if command.action == "add_edit":
            quote = command.quote or ""
            if not quote or self.original.count(quote) != 1:
                raise ReviewConflictError("source_review_quote_not_unique")
            if command.replacement == quote:
                raise ReviewConflictError("source_review_replacement_requires_exact_change")
            start = self.original.index(quote)
            end = start + len(quote)
            if any(row["start"] is not None and start < row["end"] and row["start"] < end
                   for row in self.issues.values()):
                raise ReviewConflictError("source_review_overlapping_or_stale_edit")
            item = f"m-{command.request_id}"
            payload = {"item_id": item, "id": item, "start": start, "end": end, "before": quote,
                       "after": command.replacement, "decision": "replace", "reason": command.reason,
                       "manual_issue": {"id": item, "start": start, "end": end, "quote": quote,
                                        "category": "manual", "reason": command.reason}}
            render_text(self.original, [*self.active_edits(), payload])
            return "resolved", payload
        if command.action != "resolve" or item not in self.issues or item in self.decisions:
            raise ReviewConflictError("source_review_action_not_available")
        issue = self.issues[item]
        start, end, before = issue["start"], issue["end"], issue["quote"]
        if start is None and command.quote:
            if self.original.count(command.quote) != 1:
                raise ReviewConflictError("source_review_quote_not_unique")
            start = self.original.index(command.quote)
            before, end = command.quote, start + len(command.quote)
        elif command.quote:
            raise ReviewConflictError("source_review_quote_already_bound")
        if command.decision == "replace" and (start is None or command.replacement == before):
            raise ReviewConflictError("source_review_replacement_requires_exact_change")
        payload = {"item_id": item, "id": item, "start": start, "end": end, "before": before,
                   "after": command.replacement if command.decision == "replace" else before,
                   "decision": command.decision, "reason": command.reason}
        if command.decision == "replace":
            render_text(self.original, [*self.active_edits(), payload])
        return "resolved", payload


def render_text(original: str, edits: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Compile only disjoint, exact original-coordinate edits with provenance."""
    if not original.strip() or len(original) > MAX_TEXT:
        raise ReviewConflictError("source_review_original_invalid")
    position = output_pos = 0
    pieces: list[str] = []
    spans: list[dict[str, Any]] = []

    def add(start: int, end: int, value: str, item: str | None) -> None:
        nonlocal output_pos
        pieces.append(value)
        spans.append({"raw_start": start, "raw_end": end, "working_start": output_pos,
                      "working_end": output_pos + len(value), "item_id": item})
        output_pos += len(value)

    for row in sorted(edits, key=lambda x: x["start"]):
        start, end = row["start"], row["end"]
        if not (type(start) is int and type(end) is int and position <= start < end <= len(original)
                and original[start:end] == row["before"] and isinstance(row["after"], str)
                and row["after"].strip() and "\x00" not in row["after"]):
            raise ReviewConflictError("source_review_overlapping_or_stale_edit")
        if position < start:
            add(position, start, original[position:start], None)
        add(start, end, row["after"], row["id"])
        position = end
    if position < len(original):
        add(position, len(original), original[position:], None)
    if output_pos > MAX_TEXT:
        raise ReviewConflictError("source_review_working_text_too_large")
    return "".join(pieces), spans
