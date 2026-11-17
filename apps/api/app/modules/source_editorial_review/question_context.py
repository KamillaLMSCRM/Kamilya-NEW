"""Literal table navigation for source questions, never factual approval."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.modules.ai.v3.source_units import SourceUnit, plan_source_units, source_table_topic

# Projection changes must not invalidate a completed model request whose wire
# contract is unchanged. The model-facing row inventory stays byte compatible.
REQUEST_POLICY = "source-question-row-context-v2"
POLICY = "source-question-row-context-v3"


class QuestionContextError(ValueError):
    """A fully returned review did not identify its literal source evidence."""


@dataclass(frozen=True)
class QuestionContext:
    original: str
    offset: int
    end: int
    references: dict[str, SourceUnit]
    headers: tuple[SourceUnit, ...]

    def request(self) -> dict[str, Any]:
        return {"policy": REQUEST_POLICY,
                "references": [{"id": ref, "start": unit.start - self.offset,
                    "end": unit.end - self.offset, "kind": unit.kind,
                    **({"complete_original_context": unit.text}
                       if unit.start < self.offset or unit.end > self.end else {})}
                    for ref, unit in self.references.items()],
                "table_headers": [{"container_id": unit.container_id,
                    "text": next((row.context for row in self.references.values()
                                  if row.container_id == unit.container_id and row.context), unit.text)}
                                  for unit in self.headers]}

    def bind(self, excerpt: str, refs: list[str],
             restore: Callable[[str, str], tuple[int, int] | None] | None = None) -> tuple[int, int]:
        if not refs or len(refs) != len(set(refs)) or any(ref not in self.references for ref in refs):
            raise QuestionContextError("source_question_reference_invalid")
        units = [self.references[ref] for ref in refs]
        left, right = min(u.start for u in units), max(u.end for u in units)
        scope = self.original[left:right]
        if excerpt and scope.count(excerpt) == 1:
            start = scope.index(excerpt)
            span = (left + start, left + start + len(excerpt))
        else:
            recovered = restore(scope, excerpt) if restore is not None else None
            if recovered is None:
                raise QuestionContextError("source_question_excerpt_not_bound")
            span = (left + recovered[0], left + recovered[1])
        # A multi-row quotation cannot acquire an unlisted intervening row.
        if any(u.start < span[1] and span[0] < u.end and ref not in refs
               for ref, u in self.references.items()):
            raise QuestionContextError("source_question_reference_scope_changed")
        return span

    def same_row(self, clue: str, span: tuple[int, int]) -> bool:
        local = self.original[self.offset:self.end]
        if not clue or local.count(clue) != 1:
            return False
        start = self.offset + local.index(clue)
        end = start + len(clue)
        return any(u.kind == "table_row" and u.start <= start < u.end
                   and end <= u.end and u.start <= span[0] < span[1] <= u.end
                   for u in self.references.values())

    def confirmed_row(self, clue: str, span: tuple[int, int]) -> str | None:
        """Link repeated literal clues to an OPEN question, never dismiss them."""
        if not clue:
            return None
        return next((ref for ref, unit in self.references.items() if unit.kind == "table_row"
                     and unit.start <= span[0] < span[1] <= unit.end and unit.text.count(clue) == 1), None)

    def labels(self, refs: list[str]) -> list[str]:
        return list(dict.fromkeys(label for ref in refs if ref in self.references
                                 if (label := source_table_topic(self.references[ref]))))

    def unique_literal_row(self, excerpt: str) -> str | None:
        """Find a canonical row only from one exact original occurrence."""
        if not excerpt or self.original.count(excerpt) != 1:
            return None
        start = self.original.index(excerpt)
        end = start + len(excerpt)
        return next((ref for ref, unit in self.references.items()
                     if unit.kind == "table_row" and unit.start <= start < end <= unit.end), None)


def contexts(original: str, windows: list[tuple[int, str]]) -> list[QuestionContext | None]:
    units = plan_source_units(original)
    if not any(unit.kind == "table_row" for unit in units):
        return [None] * len(windows)
    indexed = {f"S{index + 1}": unit for index, unit in enumerate(units)
               if unit.text.strip() and unit.kind != "table_header"}
    result = []
    for offset, text in windows:
        end = offset + len(text)
        refs = {ref: unit for ref, unit in indexed.items() if unit.start < end and offset < unit.end}
        containers = {unit.container_id for unit in refs.values() if unit.kind == "table_row"}
        headers = tuple(unit for unit in units if unit.kind == "table_header"
                        and unit.container_id in containers)
        result.append(QuestionContext(original, offset, end, refs, headers) if containers else None)
    return result
