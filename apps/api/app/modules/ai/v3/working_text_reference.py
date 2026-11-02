"""Exact converted-working-text locations; not original PDF or workbook coordinates."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.citation_review import bind_displayed_citation
from app.modules.ai.v3.models import RuleEntity
from app.modules.methodologist_workbench.correction_proposal import MAX_SOURCE_CHARS

KIND = "working_text_span_v1"


def working_text_references(corpus: DirectSourceCorpus, rules: tuple[RuleEntity, ...]) -> list[dict[str, Any]] | None:
    """Caller must independently establish owned current source and job identity."""
    if not rules or len({r.rule_id for r in rules}) != len(rules):
        return None
    bound: list[tuple[str, str, str, str, int, int]] = []
    for rule in rules:
        docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id and doc.source_revision == rule.source_revision]
        if (len(docs) != 1 or not isinstance(docs[0].source_text, str)
                or not re.fullmatch(r"document:[0-9a-f]{64}", rule.source_revision)
                or type(rule.source_start) is not int or type(rule.source_end) is not int
                or not bind_displayed_citation(corpus, rule, rule.source_quote)):
            return None
        text, start, end = docs[0].source_text, rule.source_start, rule.source_end
        if not 0 <= start < end <= len(text):
            return None
        bound.append((rule.doc_id, rule.source_revision, hashlib.sha256(text.encode("utf-8")).hexdigest(), text, start, end))
    merged: list[tuple[str, str, str, str, int, int]] = []
    for doc_id, revision, digest, text, start, end in sorted(bound, key=lambda item: (item[0], item[1], item[2], item[4], item[5])):
        if merged and (doc_id, revision, digest) == merged[-1][:3] and start <= merged[-1][5]:
            previous = merged[-1]
            merged[-1] = (*previous[:5], max(previous[5], end))
        else:
            merged.append((doc_id, revision, digest, text, start, end))
    if (len({item[0] for item in merged}) > 5 or len(merged) > 64
            or sum(item[5] - item[4] for item in merged) > MAX_SOURCE_CHARS):
        return None
    if any(not any((doc, rev, sha) == part[:3] and part[4] <= start and end <= part[5]
                   for part in merged) for doc, rev, sha, _text, start, end in bound):
        return None
    result: list[dict[str, Any]] = []
    for doc_id, revision, digest, text, start, end in merged:
        result.append({"kind": KIND, "doc_id": doc_id, "source_revision": revision,
            "source_text_sha256": digest, "start": start, "end": end,
            "span_sha256": hashlib.sha256(text[start:end].encode("utf-8")).hexdigest()})
    return result
