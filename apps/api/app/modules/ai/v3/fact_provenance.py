"""Strict V3-to-correction fact references for owned narrative sources."""
from __future__ import annotations

import re
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus, direct_source_chunks
from app.modules.ai.evidence_engine.application import _fact_reference, _locator_values, build_evidence_source
from app.modules.ai.v3.citation_review import bind_displayed_citation
from app.modules.ai.v3.models import RuleEntity


def exact_narrative_fact_references(
    corpus: DirectSourceCorpus, rules: tuple[RuleEntity, ...],
) -> list[dict[str, Any]] | None:
    """Return refs for exact or uniquely enclosing, source-bound narrative facts.

    Caller must independently establish current tenant, selection and revision
    ownership. This does not certify lesson-wide semantic coverage. Reconstructed
    table row or column indexes are intentionally not used as source locations.
    """
    if (not corpus.tenant_id or not rules or len({r.rule_id for r in rules}) != len(rules)
            or len(corpus.documents) > 5 or len({d.doc_id for d in corpus.documents}) != len(corpus.documents)):
        return None
    for doc in corpus.documents:
        if doc.source_text is None or not re.fullmatch(r"document:[0-9a-f]{64}", doc.source_revision):
            return None
        try:
            rebuilt = direct_source_chunks(doc.source_text, document_id=doc.doc_id, filename=doc.filename,
                                           title=doc.title, source_revision=doc.source_revision)
        except Exception:
            return None
        if doc.chunks != rebuilt:
            return None
    try:
        facts = build_evidence_source(corpus).generation_facts
    except Exception:
        return None
    if len({fact.fact_id for fact in facts}) != len(facts):
        return None
    selected = []
    for rule in rules:
        if not bind_displayed_citation(corpus, rule, rule.source_quote):
            return None
        docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id]
        if len(docs) != 1 or docs[0].source_text is None:
            return None
        source = docs[0].source_text
        exact = []
        enclosing = []
        for fact in facts:
            locator = _locator_values(fact.source_locator)
            if (locator.get("doc_id") != rule.doc_id or locator.get("source_revision") != rule.source_revision
                    or not isinstance(fact.value, str) or not fact.value
                    or any(k in locator for k in ("row", "column", "table"))
                    or not locator.get("section") or not locator.get("part")
                    or fact.uncertainty or fact.confidence != 1.0):
                continue
            if fact.value == rule.source_quote:
                exact.append(fact)
                continue
            if rule.source_quote not in fact.value or fact.value.count(rule.source_quote) != 1:
                continue
            start = source.find(fact.value)
            if (start < 0 or source.find(fact.value, start + 1) >= 0
                    or type(rule.source_start) is not int or type(rule.source_end) is not int
                    or not rule.source_start <= start < start + len(fact.value) <= rule.source_end):
                continue
            enclosing.append(fact)
        candidates = exact if exact else enclosing
        if len(candidates) != 1:
            return None
        selected.append(candidates[0])
    if len(selected) > 64 or len({fact.fact_id for fact in selected}) != len(selected):
        return None
    return [_fact_reference(fact, corpus) for fact in selected]
