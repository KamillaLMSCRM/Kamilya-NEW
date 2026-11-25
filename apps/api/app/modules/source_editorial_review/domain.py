"""Deterministic reconstruction and command validation for source review."""

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.source_preparation.domain import PreparedSource, validate_binding

MAX_TEXT = 1_000_000
POLICY = "human-source-editorial-review-v1"
SOURCE_PINS = "source_editorial_snapshots"


def text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class ReviewConflictError(ValueError):
    """The requested change does not apply to the current review."""


def validated_preparation(value: object, original_blob_sha256: str | None = None,
                          recognized_text: str | None = None) -> tuple[PreparedSource, list[str]]:
    manifest, ids = validate_binding(value, original_blob_sha256, recognized_text)
    if not isinstance(value, dict) or value.get("selected_part_ids") != ids:
        raise ValueError("source_preparation_selection_order_invalid")
    return manifest, ids


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
    preparation: dict[str, Any] | None = field(default=None, repr=False)
    decision_context: tuple[dict[str, Any], ...] = field(default=(), repr=False)

    @property
    def editorial_revision(self) -> str:
        return "editorial:" + self.working_sha256

    def valid(self, *, document_id: str, source_revision: str) -> bool:
        if (self.document_id != document_id or self.source_revision != source_revision
                or text_hash(self.working_text) != self.working_sha256):
            return False
        try:
            if not isinstance(self.decision_context, tuple):
                return False
            seen_decisions = set()
            for row in self.decision_context:
                if (not isinstance(row, dict)
                        or set(row) != {'item_id', 'decision', 'quote', 'reason', 'start', 'end'}
                        or type(row['item_id']) is not str or not row['item_id'].strip()
                        or row['item_id'] in seen_decisions or row['decision'] not in {'keep', 'replace'}
                        or type(row['reason']) is not str or not row['reason'].strip()
                        or type(row['quote']) is not str):
                    return False
                unanchored = row['start'] is None and row['end'] is None and row['decision'] == 'keep'
                anchored = (type(row['start']) is int and type(row['end']) is int
                    and 0 <= row['start'] < row['end'] <= len(self.recognized_text)
                    and self.recognized_text[row['start']:row['end']] == row['quote'])
                if not unanchored and not anchored:
                    return False
                seen_decisions.add(row['item_id'])
            if self.preparation is not None:
                if not source_revision.startswith("document:"):
                    return False
                validated_preparation(self.preparation, source_revision.removeprefix("document:"), self.recognized_text)
            edits = [
                {"start": row["raw_start"], "end": row["raw_end"], "id": row["item_id"],
                 "before": self.recognized_text[row["raw_start"]:row["raw_end"]],
                 "after": self.working_text[row["working_start"]:row["working_end"]]}
                for row in self.spans if row["item_id"] is not None
            ]
            text, spans = render_text(self.recognized_text, edits)
            return text == self.working_text and tuple(spans) == self.spans
        except (TypeError, KeyError, ValueError):
            return False


class ReviewPageRange(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    first_page: int = Field(ge=1, le=10000)
    last_page: int = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def ordered(self) -> "ReviewPageRange":
        if self.last_page < self.first_page:
            raise ValueError("last page must not precede first page")
        return self


class ScopedSourceReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_ref: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=5000)
    replacement: str = Field(min_length=1, max_length=5000)
    all_occurrences: bool = False

    @model_validator(mode="after")
    def valid_text(self) -> "ScopedSourceReplacement":
        if not self.replacement.strip() or "\x00" in self.replacement or "\r" in self.replacement:
            raise ValueError("invalid replacement")
        return self


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_revision: int = Field(ge=0)
    request_id: UUID
    action: Literal["start", "resolve", "reopen_issue", "undo_auto", "approve", "reopen", "add_edit", "select_parts"]
    item_id: str | None = Field(default=None, min_length=1, max_length=80)
    decision: Literal["replace", "keep"] | None = None
    replacement: str | None = Field(default=None, min_length=1, max_length=5000)
    reason: str | None = Field(default=None, min_length=3, max_length=1500)
    quote: str | None = Field(default=None, min_length=1, max_length=5000)
    source_changes: list[ScopedSourceReplacement] | None = Field(default=None, min_length=1, max_length=256)
    pages: ReviewPageRange | None = None
    selected_part_ids: list[str] | None = Field(default=None, min_length=1, max_length=5000)
    preparation_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    acknowledge_outcome_and_cost_unknown: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_fields(self) -> "ReviewCommand":
        if "acknowledge_outcome_and_cost_unknown" in self.model_fields_set and self.action != "start":
            raise ValueError("acknowledgement only allowed when starting a review")
        if self.action == "select_parts":
            if self.selected_part_ids is None or self.preparation_sha256 is None:
                raise ValueError("selection and preparation identity required")
        elif self.selected_part_ids is not None or self.preparation_sha256 is not None:
            raise ValueError("selection only allowed when selecting parts")
        if self.pages is not None and self.action != "start":
            raise ValueError("pages are allowed only when starting a review")
        if self.action in {"resolve", "reopen_issue", "undo_auto"}:
            if not self.item_id or not self.reason:
                raise ValueError("item and reason required")
        elif self.action == "add_edit":
            if self.item_id is not None or not self.reason or not self.quote or not self.replacement or self.decision:
                raise ValueError("exact quote, replacement and reason required for a manual edit")
        elif self.item_id is not None or self.reason is not None:
            raise ValueError("unexpected item or reason")
        if self.action == "resolve":
            if (self.decision is None
                    or (self.decision == "replace" and (self.replacement is None) == (self.source_changes is None))
                    or (self.decision == "keep" and (self.replacement is not None or self.source_changes is not None))
                    or (self.source_changes is not None and self.quote is not None)):
                raise ValueError("an explicit decision and matching replacement are required")
        elif self.action != "add_edit" and (self.decision is not None or self.replacement is not None or self.quote is not None):
            raise ValueError("unexpected decision")
        if self.source_changes is not None and self.action != "resolve":
            raise ValueError("scoped changes only allowed when resolving an issue")
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
    pages: dict[str, int] | None = None
    preparation: dict[str, Any] | None = field(default=None, repr=False)
    pending_preparation: dict[str, Any] | None = field(default=None, repr=False)

    def hydrate_manifest(self, value: object, blob_sha: str) -> None:
        """Expose a completed first preparation without declaring editorial analysis complete."""
        if self.preparation is not None or self.pending_preparation is not None or self.original:
            return
        try:
            package = PreparedSource.model_validate(value)
            if package.original_blob_sha256 != blob_sha:
                raise ValueError("source_preparation_binding_changed")
            ids = [part.id for part in package.parts if part.role == "learning"]
            if not ids:
                ids = [part.id for part in package.parts if part.role == "supporting"]
            if not ids:
                ids = [package.parts[0].id]
            self.preparation = package.binding(ids)
            self.original = package.selected(ids)[0]
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            raise ReviewConflictError("source_review_preparation_invalid") from exc

    def apply(self, sequence: int, kind: str, payload: dict[str, Any]) -> None:
        if sequence != self.revision + 1:
            raise ReviewConflictError("source_review_history_invalid")
        self.revision = sequence
        if kind == "queued":
            self.status, self.error = "queued", None
            self.pages = payload.get("pages")
            self.pending_preparation = payload.get("preparation")
        elif kind in {"running", "analysis_block"}:
            self.status = "running"
        elif kind == "failed":
            self.status, self.error = "failed", payload["code"]
        elif kind == "analyzed":
            preparation = payload.get("preparation")
            if self.pending_preparation is not None and preparation != self.pending_preparation:
                raise ReviewConflictError("source_review_preparation_changed")
            if preparation is not None:
                try:
                    validated_preparation(preparation, recognized_text=payload["original"])
                except (TypeError, ValueError, KeyError) as exc:
                    raise ReviewConflictError("source_review_preparation_invalid") from exc
            self.preparation = preparation
            self.pending_preparation = None
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
            *(edit for row in self.decisions.values() if row["decision"] == "replace"
              for edit in row.get("source_changes", [row])),
        ]

    def decision_context(self) -> tuple[dict[str, Any], ...]:
        return tuple({'item_id': edit.get('id', item), 'decision': row['decision'],
                      'quote': edit['before'], 'reason': row['reason'], 'start': edit['start'], 'end': edit['end']}
                     for item, row in sorted(self.decisions.items()) for edit in row.get('source_changes', [row]))

    def scoped_changes(self, issue: dict[str, Any], command: ReviewCommand) -> list[dict[str, Any]]:
        edits: list[dict[str, Any]] = []
        for change in command.source_changes or []:
            scopes = [s for s in issue.get('source_scopes', []) if s.get('source_ref') == change.source_ref]
            if len(scopes) != 1:
                raise ReviewConflictError('source_review_evidence_scope_invalid')
            scope = scopes[0]
            left, right = scope.get('start'), scope.get('end')
            if (type(left) is not int or type(right) is not int or not 0 <= left < right <= len(self.original)
                    or self.original[left:right] != scope.get('text')):
                raise ReviewConflictError('source_review_evidence_scope_invalid')
            text = self.original[left:right]
            positions: list[int] = []
            position = 0
            while (found := text.find(change.quote, position)) >= 0:
                positions.append(found)
                position = found + len(change.quote)
            if not positions or (not change.all_occurrences and len(positions) != 1):
                raise ReviewConflictError('source_review_quote_not_unique')
            if change.replacement == change.quote:
                raise ReviewConflictError('source_review_replacement_requires_exact_change')
            for position in positions:
                if len(edits) >= 256:
                    raise ReviewConflictError('source_review_too_many_changes')
                edits.append({'id': f'{command.item_id}:{len(edits)}', 'item_id': command.item_id,
                    'source_ref': change.source_ref, 'start': left + position,
                    'end': left + position + len(change.quote), 'before': change.quote,
                    'after': change.replacement, 'reason': command.reason})
        return edits

    def working(self) -> tuple[str, list[dict[str, Any]]]:
        return render_text(self.original, self.active_edits())

    def plan(self, command: ReviewCommand) -> tuple[str, dict[str, Any]]:
        if command.expected_revision != self.revision:
            raise ReviewConflictError("source_review_revision_conflict")
        if command.action == "start" and self.status in {"not_started", "failed"}:
            binding = self.pending_preparation or (self.preparation if self.status == "failed" else None)
            if binding is not None:
                if command.pages is not None and command.pages.model_dump() != self.pages:
                    raise ReviewConflictError("source_review_preparation_changed")
                return "queued", {"preparation": binding, **({"pages": self.pages} if self.pages else {})}
            return "queued", {"pages": command.pages.model_dump()} if command.pages else {}
        if command.action == "reopen" and self.status == "approved":
            return "reopened", {}
        if command.action == "select_parts" and self.status in {"in_review", "failed"}:
            try:
                manifest, _ = validated_preparation(self.preparation, recognized_text=self.original)
                if manifest.sha256 != command.preparation_sha256:
                    raise ValueError("source_preparation_binding_changed")
                binding = manifest.binding(command.selected_part_ids or [])
                if binding == self.preparation and self.status == "in_review":
                    raise ValueError("source_preparation_selection_unchanged")
            except (TypeError, KeyError, ValueError) as exc:
                raise ReviewConflictError("source_review_preparation_invalid") from exc
            return "queued", {"preparation": binding, **({"pages": self.pages} if self.pages else {})}
        if self.status != "in_review":
            raise ReviewConflictError("source_review_action_not_available")
        item = command.item_id or ""
        if command.action == "approve":
            if self.issues.keys() - self.decisions.keys():
                raise ReviewConflictError("source_review_questions_open")
            working, spans = self.working()
            return "approved", {"working": working, "working_sha256": text_hash(working),
                                "original_sha256": text_hash(self.original), "spans": spans,
                                "policy": POLICY, **({"pages": self.pages} if self.pages else {}),
                                **({"preparation": self.preparation} if self.preparation else {})}
        if command.action == "undo_auto" and item in self.automatic and item not in self.disabled_auto:
            row = self.automatic[item]
            return "auto_undone", {"item_id": item, "start": row["start"], "end": row["end"],
                                   "before": row["after"], "after": row["before"], "reason": command.reason}
        if command.action == "reopen_issue" and item in self.decisions:
            row = self.decisions[item]
            return "issue_reopened", {"item_id": item, "start": row["start"], "end": row["end"],
                                      "before": row["after"], "after": row["before"], "reason": command.reason,
                                      **({'source_changes': [{**edit, 'before': edit['after'], 'after': edit['before'],
                                                              'reason': command.reason} for edit in row['source_changes']]}
                                         if row.get('source_changes') else {})}
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
        if issue.get('source_scopes') and command.decision == 'replace' and command.source_changes is None:
            raise ReviewConflictError('source_review_evidence_scope_invalid')
        if command.source_changes is not None:
            edits = self.scoped_changes(issue, command)
            render_text(self.original, [*self.active_edits(), *edits])
            return "resolved", {**edits[0], 'id': item, 'item_id': item, 'decision': 'replace', 'source_changes': edits}
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


def source_edit_matches(original: str, start: object, end: object, before: object, after: object) -> bool:
    """Check a single edit at its exact original coordinate."""
    return (
        type(start) is int and type(end) is int and 0 <= start < end <= len(original)
        and isinstance(before, str) and original[start:end] == before and isinstance(after, str)
        # A layout edit can affect whitespace alone, but cannot erase source words.
        and bool(after.strip() or (before.isspace() and after.isspace())) and "\x00" not in after
    )


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
        before, after = row["before"], row["after"]
        if not source_edit_matches(original, start, end, before, after) or position > start:
            raise ReviewConflictError("source_review_overlapping_or_stale_edit")
        if position < start:
            add(position, start, original[position:start], None)
        add(start, end, after, row["id"])
        position = end
    if position < len(original):
        add(position, len(original), original[position:], None)
    if output_pos > MAX_TEXT:
        raise ReviewConflictError("source_review_working_text_too_large")
    return "".join(pieces), spans
