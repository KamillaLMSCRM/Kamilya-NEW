"""Project verified working-text spans onto a replacement source."""

from __future__ import annotations

from difflib import SequenceMatcher
from hashlib import sha256
from itertools import accumulate
from typing import Any

from app.modules.ai.direct_source import DirectSourceDocument

_SPAN_FIELDS = {"kind", "doc_id", "source_revision", "source_text_sha256", "start", "end", "span_sha256"}


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


class WorkingTextChanges:
    def __init__(self, old: DirectSourceDocument, new: DirectSourceDocument) -> None:
        self.old = old
        self.new = new
        self.before = old.source_text or ""
        self.after = new.source_text or ""
        self.before_digest = _digest(self.before)
        self.after_digest = _digest(self.after)
        old_lines = self.before.splitlines(keepends=True)
        new_lines = self.after.splitlines(keepends=True)
        self.segments: list[tuple[str, int, int, int, int]] = []
        if max(len(old_lines), len(new_lines)) > 4000:
            return
        old_offsets = list(accumulate(map(len, old_lines), initial=0))
        new_offsets = list(accumulate(map(len, new_lines), initial=0))
        for tag, i, j, k, end in SequenceMatcher(None, old_lines, new_lines).get_opcodes():
            if tag == "replace" and j == i + 1 and end == k + 1 and max(len(old_lines[i]), len(new_lines[k])) <= 4000:
                line = SequenceMatcher(None, old_lines[i], new_lines[k])
                if line.ratio() >= 0.7:
                    self.segments.extend(
                        (op, old_offsets[i] + a, old_offsets[i] + b, new_offsets[k] + c, new_offsets[k] + d)
                        for op, a, b, c, d in line.get_opcodes()
                    )
                    continue
            self.segments.append((tag if tag == "equal" else "unmapped",
                                  old_offsets[i], old_offsets[j], new_offsets[k], new_offsets[end]))

    @property
    def has_unmapped_changes(self) -> bool:
        return self.before != self.after and (not self.segments or any(row[0] == "unmapped" for row in self.segments))

    def edits_are_covered(self, references: list[dict[str, Any]]) -> bool:
        """A change outside the cited passages can still alter their scope."""
        if self.has_unmapped_changes:
            return False
        return all(
            tag == "equal" or any(ref["start"] <= start <= end <= ref["end"] for ref in references)
            for tag, start, end, _, _ in self.segments
        )

    def rebind(self, reference: dict[str, Any]) -> tuple[dict[str, Any], bool] | None:
        if (set(reference) != _SPAN_FIELDS or reference["kind"] != "working_text_span_v1"
                or reference["doc_id"] != self.old.doc_id or reference["source_revision"] != self.old.source_revision
                or reference["source_text_sha256"] != self.before_digest):
            return None
        start, end = reference["start"], reference["end"]
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(self.before)
                or reference["span_sha256"] != _digest(self.before[start:end])):
            return None

        mapped: list[tuple[int, int]] = []
        for tag, old_start, old_end, new_start, new_end in self.segments:
            if old_start == old_end:
                if not start <= old_start <= end:
                    continue
            elif old_start >= end or old_end <= start:
                continue
            if tag == "equal":
                mapped.append((new_start + max(start - old_start, 0), new_end - max(old_end - end, 0)))
            elif tag != "unmapped" and start <= old_start <= old_end <= end:
                mapped.append((new_start, new_end))
            else:
                return None
        if not mapped or any(a[1] != b[0] for a, b in zip(mapped, mapped[1:], strict=False)):
            return None
        new_start, new_end = mapped[0][0], mapped[-1][1]
        quote = self.after[new_start:new_end]
        if not quote.strip():
            return None
        return {
            **reference, "doc_id": self.new.doc_id, "source_revision": self.new.source_revision,
            "source_text_sha256": self.after_digest, "start": new_start, "end": new_end, "span_sha256": _digest(quote),
        }, quote != self.before[start:end]
