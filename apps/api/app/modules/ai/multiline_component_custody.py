"""Lossless proposal custody for plain multiline fields, not semantic approval.

Exact answer-to-qualification movement still requires the full source-plan audit.
Governed/marked lists stay on their separate decomposition path.
"""

from __future__ import annotations

import re
from typing import Any

from app.modules.ai.assessment_governing_bindings import compile_assessment_governing_bindings
from app.modules.ai.source_layout import parse_source_marker


def lossless_multiline_component_reprojection(
    *, before: dict[str, Any], after: dict[str, Any], source_ref: str,
    source_id: str, source_text: str, old_quote: str, quote: str,
) -> bool:
    """Conserve every non-whitespace character once in one exact held span.

    Roles/effects come from the proposal, never from layout. This proof alone
    cannot grant admission, correct semantic attachment, or assessment coverage.
    """
    if (not 0 < len(old_quote) <= 512 or not 0 < len(quote) <= 240
            or len(source_text) > 65536 or old_quote == quote
            or not re.search(r"[\r\n]", old_quote) or re.search(r"[\r\n]", quote)
            or source_text.count(old_quote) != 1 or old_quote.count(quote) != 1
            or source_text.count(quote) != 1
            or before.get("source_refs") != [source_ref]
            or before.get("answer_components") != [{"ref": source_ref, "terms": [old_quote]}]
            or after.get("answer_components") != [{"ref": source_ref, "terms": [quote]}]):
        return False
    start = source_text.index(old_quote)
    end = start + len(old_quote)
    preceding_lines = re.split(r"\r\n|\r|\n", source_text[:start])
    following_line = re.split(r"\r\n|\r|\n", source_text[end:], maxsplit=1)[0]
    if preceding_lines[-1].strip() or following_line.strip():
        return False  # A partial physical row cannot establish plain-field layout.
    if any(line.rstrip().endswith(":") for line in preceding_lines[:-1]):
        return False  # A preceding sibling does not end a colon governor's scope.
    # The canonical parser distinguishes explicit а) from address abbreviation г.
    for line in re.split(r"\r\n|\r|\n", old_quote):
        if not line.strip() or line.rstrip().endswith(":"):
            return False
        if parse_source_marker(line) is not None:
            return False
    old_bindings = before.get("governing_bindings", [])
    new_bindings = after.get("governing_bindings", [])
    if (not isinstance(old_bindings, list) or not isinstance(new_bindings, list)
            or new_bindings[:len(old_bindings)] != old_bindings
            or len(new_bindings) <= len(old_bindings)):
        return False
    try:
        compiled = compile_assessment_governing_bindings(
            [after], sources={source_ref: (source_id, source_text)},
        )
    except (ValueError, TypeError):
        return False
    if compiled.invalid_target_issues:
        return False
    covered = [False] * len(old_quote)
    spans = [quote]
    for binding in new_bindings[len(old_bindings):]:
        if not isinstance(binding, dict) or binding.get("ref") != source_ref:
            return False
        residual = binding.get("quote")
        if (not isinstance(residual, str) or not residual or old_quote.count(residual) != 1
                or source_text.count(residual) != 1):
            return False
        spans.append(residual)
    for span in spans:
        start = old_quote.index(span)
        end = start + len(span)
        if any(covered[start:end]):
            return False
        covered[start:end] = [True] * len(span)
    return all(owned or char.isspace() for char, owned in zip(old_quote, covered, strict=True))
