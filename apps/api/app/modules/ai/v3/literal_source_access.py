"""Frozen approved reference rows and bounded model views; index labels are not evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.v3.practical_contract import _digest
from app.modules.ai.v3.practical_model_view import PracticalModelView
from app.modules.ai.v3.simple_semantic_source_plan import build_semantic_slices
from app.modules.ai.v3.simple_source_origin import source_origin_blocks
from app.modules.ai.v3.source_units import plan_source_units
from app.modules.source_editorial_review.domain import validated_preparation

_SLICE_FIELDS = (
    "source_slices", "primary_slices", "supporting_slices", "missing_slices", "literal_neighbor_context",
)


@dataclass(frozen=True, slots=True)
class ReferenceRow:
    handle: str
    document_id: str
    source_ref: str
    start: int
    end: int
    label: str
    key: str
    header: str
    text: str = field(repr=False)

    def literal(self) -> dict[str, Any]:
        return {
            "id": self.handle,
            "document_id": self.document_id,
            "source_ref": self.source_ref,
            "start": self.start,
            "end": self.end,
            "table_header": self.header,
            "text": self.text,
            "text_sha256": hashlib.sha256(self.text.encode()).hexdigest(),
        }


def _merged(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for left, right in sorted(ranges):
        if result and left <= result[-1][1]:
            result[-1] = result[-1][0], max(result[-1][1], right)
        else:
            result.append((left, right))
    return result


def _working_ranges(approval: Any, raw_ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result = []
    for span in approval.spans:
        rs, re = span["raw_start"], span["raw_end"]
        ws, we = span["working_start"], span["working_end"]
        for start, end in raw_ranges:
            if span["item_id"] is not None:
                if start <= rs and re <= end:
                    result.append((ws, we))
            elif rs < end and start < re:
                result.append((ws + max(start, rs) - rs, ws + min(end, re) - rs))
    return _merged(result)


def _supporting_ranges(approval: Any) -> list[tuple[int, int]]:
    if approval.preparation is None:
        return []
    package, selected = validated_preparation(
        approval.preparation, approval.source_revision.removeprefix("document:"), approval.recognized_text
    )
    _, _, blocks = package.selected(selected)
    indexes = {block.id: i for i, block in enumerate(package.blocks)}
    roles = {
        block.id: part.role
        for part in package.parts
        for block in package.blocks[indexes[part.first_block] : indexes[part.last_block] + 1]
    }
    position = 0
    raw = []
    first = True
    for block in blocks:
        if not block.text.strip():
            continue
        if not first:
            position += 2
        first = False
        if roles[block.id] == "supporting" and not block.asset_ids:
            raw.append((position, position + len(block.text)))
        position += len(block.text)
    if position != len(approval.recognized_text):
        raise ValueError("source_access_preparation_binding_invalid")
    return _working_ranges(approval, raw)


class LiteralSourceAccess:
    """Per-generation immutable source store; lookup never consults another tenant or revision."""

    def __init__(self, packet: Any, corpus: Any, *, literal_budget: int, reference_decisions: tuple[Any, ...] = ()):
        if type(literal_budget) is not int or literal_budget < 1000:
            raise ValueError("source_access_budget_invalid")
        self.packet = packet
        self.corpus = corpus
        self.budget = literal_budget
        self.view = PracticalModelView(packet)
        self.origins = {row["id"]: row for row in source_origin_blocks(packet, corpus)}
        self.slices = build_semantic_slices(packet, corpus)
        self.rows: tuple[ReferenceRow, ...]
        rows = []
        self.decisions: dict[tuple[str, str], list[tuple[int, int]] | None] = {}
        for doc in corpus.documents:
            approved = doc.editorial_document
            source = doc.source_text
            support = _supporting_ranges(approved)
            for decision in approved.decision_context:
                self.decisions[(doc.doc_id, decision["item_id"])] = (
                    None
                    if decision["start"] is None
                    else _working_ranges(approved, [(decision["start"], decision["end"])])
                )
            for unit in plan_source_units(source, allow_spaced_tables=True):
                if unit.kind != "table_row" or "source-asset:" in unit.text:
                    continue
                # Blank separators belong to their original parent; only the whole
                # literal row is indexed. No mid-row or word-level truncation.
                start = unit.start + len(unit.text) - len(unit.text.lstrip("\r\n"))
                end = unit.end - len(unit.text) + len(unit.text.rstrip("\r\n"))
                if not any(left <= start < end <= right for left, right in support):
                    continue
                if any(
                    d.document_id == doc.doc_id and d.target_start < end and start < d.target_end
                    for d in reference_decisions
                ):
                    continue  # explicit normative dependency stays in literal parent context
                owners = [
                    b
                    for b in packet.blocks
                    if b.doc_id == doc.doc_id and b.start <= start < end <= b.end and b.text.strip()
                ]
                if len(owners) != 1:
                    continue
                text = source[start:end]
                cells = [cell.strip() for cell in text.strip().strip("|").split("|")]
                if not cells or not cells[0]:
                    continue
                # Navigation only. Oversize labels are explicitly absent rather
                # than being shortened into purported source evidence.
                label = " | ".join(cells[:2])
                if len(label) > 300:
                    label = cells[0] if len(cells[0]) <= 300 else "[label available by lookup]"
                handle = (
                    "ROW-"
                    + _digest([packet.tenant_id, doc.doc_id, doc.source_revision, approved.working_sha256, start, end])[
                        :24
                    ]
                )
                rows.append(
                    ReferenceRow(
                        handle,
                        doc.doc_id,
                        self.view.canonical_to_alias[owners[0].block_id],
                        start,
                        end,
                        label,
                        cells[0],
                        unit.context,
                        text,
                    )
                )
        self.rows = tuple(rows)
        self.by_id = {row.handle: row for row in self.rows}
        if len(self.by_id) != len(self.rows):
            raise ValueError("source_access_duplicate_identity")
        self.slice_rows: dict[str, str] = {}
        for part in self.slices:
            for row in self.rows:
                if (
                    part["document_id"] == row.document_id
                    and row.start < part["end"]
                    and part["start"] < row.end
                    and not part["text"].strip() == ""
                    and not next(d.source_text for d in corpus.documents if d.doc_id == row.document_id)[
                        part["start"] : min(row.start, part["end"])
                    ].strip()
                    and not next(d.source_text for d in corpus.documents if d.doc_id == row.document_id)[
                        max(row.end, part["start"]) : part["end"]
                    ].strip()
                ):
                    self.slice_rows[part["id"]] = row.handle
                    break
        self.fingerprint = _digest(
            [packet.fingerprint, [[r.handle, hashlib.sha256(r.text.encode()).hexdigest()] for r in self.rows]]
        )
        self.plan: dict[str, Any] | None = None

    def lookup(self, handles: list[str], *, source_fingerprint: str) -> list[dict[str, Any]]:
        if (
            source_fingerprint != self.packet.fingerprint
            or type(handles) is not list
            or any(type(x) is not str or x not in self.by_id for x in handles)
            or len(set(handles)) != len(handles)
        ):
            raise ValueError("source_access_lookup_unowned")
        result = []
        for handle in handles:
            row = self.by_id[handle]
            source = next(d.source_text for d in self.corpus.documents if d.doc_id == row.document_id)
            if source[row.start : row.end] != row.text:
                raise ValueError("source_access_literal_changed")
            result.append(row.literal())
        return result

    def _segments(self, alias: str) -> list[dict[str, Any]]:
        canonical = self.view.alias_to_canonical[alias]
        block = next(b for b in self.packet.blocks if b.block_id == canonical)
        removed = [(r.start, r.end) for r in self.rows if r.source_ref == alias]
        result = []
        position = block.start
        for segment in self.origins[canonical]["segments"]:
            end = position + len(segment["text"])
            cursor = position
            for left, right in removed:
                if left >= end:
                    break
                if cursor < left and cursor < end:
                    stop = min(left, end)
                    result.append(
                        {
                            **segment,
                            "text": segment["text"][cursor - position : stop - position],
                            "start": cursor,
                            "end": stop,
                        }
                    )
                cursor = max(cursor, min(right, end)) if left < end and cursor < right else cursor
            if cursor < end:
                result.append({**segment, "text": segment["text"][cursor - position :], "start": cursor, "end": end})
            position = end
        return result

    def project(
        self, messages: list[dict[str, str]], group: str, requested: tuple[str, ...] = ()
    ) -> tuple[list[dict[str, str]], str]:
        output = copy.deepcopy(messages)
        payload = json.loads(output[1]["content"])
        if not isinstance(payload, dict) or payload.get("source_fingerprint") != self.packet.fingerprint:
            raise ValueError("source_access_payload_unowned")
        # Server-generated source projection is deterministic for this stage and
        # lookup prefix, so native/cold replay uses exactly the same request.
        candidates: list[str] = []
        for key in ("primary_slices", "supporting_slices"):
            candidates.extend(
                self.slice_rows[row["id"]] for row in payload.get(key, []) if row.get("id") in self.slice_rows
            )
        if not candidates and self.plan:
            candidates.extend(
                self.slice_rows[s]
                for unit in self.plan["units"]
                for s in unit["primary_slices"] + unit["supporting_slices"]
                if s in self.slice_rows
            )
        narrative = json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key not in ("source_blocks", "documents", *_SLICE_FIELDS)
            },
            ensure_ascii=False,
        )
        key_counts = Counter(row.key for row in self.rows)
        mentioned = [r.handle for r in self.rows if len(r.key) >= 3 and key_counts[r.key] == 1 and r.key in narrative]
        exposed = list(dict.fromkeys(requested))
        if any(handle not in self.by_id for handle in exposed):
            raise ValueError("source_access_lookup_unowned")
        used = sum(len(self.by_id[handle].text) for handle in exposed)
        if ":plan:" not in group:
            mentioned.extend(candidates)
        for handle in dict.fromkeys(mentioned):
            if handle in exposed:
                continue
            size = len(self.by_id[handle].text)
            if used + size <= self.budget:
                exposed.append(handle)
                used += size
        # Keep all operative/prose/visual text; replace only proven supporting
        # table rows with addressable navigation and explicitly exposed literals.
        ranges: dict[str, list[tuple[int, int]]] = {}
        stage_refs: dict[str, str] = {}
        for block in payload.get("source_blocks", []):
            supplied = block["id"]
            alias = self.view.canonical_to_alias.get(supplied, supplied)
            if alias not in self.view.alias_to_canonical:
                raise ValueError("source_access_parent_unowned")
            stage_refs[alias] = supplied
            document_id = self.origins[self.view.alias_to_canonical[alias]]["document_id"]
            segments = self._segments(alias)
            block.pop("text", None)
            block["segments"] = segments
            ranges.setdefault(document_id, []).extend((s["start"], s["end"]) for s in segments)
        for key in _SLICE_FIELDS:
            if key in payload:
                for part in payload[key]:
                    if part.get("id") not in self.slice_rows and "start" in part and "end" in part:
                        ranges.setdefault(part["document_id"], []).append((part["start"], part["end"]))
                payload[key] = [
                    (
                        {
                            "id": row["id"],
                            "source_ref": row["source_ref"],
                            "reference_row_id": self.slice_rows[row["id"]],
                            "literal_available_by_lookup": True,
                        }
                        if row.get("id") in self.slice_rows
                        else row
                    )
                    for row in payload[key]
                ]
        for handle in exposed:
            row = self.by_id[handle]
            ranges.setdefault(row.document_id, []).append((row.start, row.end))
        for doc in payload.get("documents", []):
            kept = []
            for decision in doc.get("approved_decisions", []):
                ds = self.decisions.get((doc["document_id"], decision["item_id"]))
                if ds is None or any(a < y and x < b for a, b in ds for x, y in ranges.get(doc["document_id"], [])):
                    kept.append(decision)
            doc["approved_decisions"] = kept
        payload["reference_index"] = [
            {"id": row.handle, "source_ref": stage_refs.get(row.source_ref, row.source_ref), "label": row.label}
            for row in self.rows
        ]
        payload["reference_rows"] = self.lookup(exposed, source_fingerprint=self.packet.fingerprint)
        for row in payload["reference_rows"]:
            row["source_ref"] = stage_refs.get(row["source_ref"], row["source_ref"])
        payload["source_access"] = {
            "policy": "literal-reference-access-v1",
            "store_fingerprint": self.fingerprint,
            "total_reference_rows": len(self.rows),
            "exposed_reference_rows": len(exposed),
            "navigation_is_evidence": False,
            "instructions": "Index labels are navigation only. Complete approved rows remain available. "
            "Request exact ROW handles in lookup_ids with empty results if source data needed for your task "
            "is not exposed; do not guess or silently infer missing characteristics. Otherwise return one result "
            "and empty lookup_ids. A reference catalogue is lookup material, not a lesson for every row. "
            "Choose coherent practical topics from the learning material and a few useful literal reference examples.",
        }
        context_fp = _digest([self.fingerprint, group, self.budget, payload, list(requested)])
        output[1]["content"] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return output, context_fp
