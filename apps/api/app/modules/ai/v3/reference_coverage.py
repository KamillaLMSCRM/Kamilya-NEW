"""Inventory confirmed source references without assigning an unproven rule."""

from __future__ import annotations

import hashlib
import json

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.models import RuleEntity
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, reference_context_for_rules


def unmatched_confirmed_references(
    corpus: DirectSourceCorpus, rules: list[RuleEntity], decisions: tuple[SourceReferenceDecision, ...],
) -> list[str]:
    """Return opaque IDs when a confirmed occurrence has no unique grounded rule.

    A document-level quote must identify exactly one location and contain the
    verified occurrence. A missing or multiply owned source occurrence is not
    assigned to an arbitrary rule. Values never include the source text.
    """
    from app.modules.ai.v3.service import CLAUSE_REF_RE, _verify_rule_quote_grounding

    reference_context_for_rules(corpus.tenant_id, corpus.documents, decisions, ())
    unmatched: list[str] = []
    for decision in decisions:
        owner_count = 0
        clauses = [value.strip().rstrip(".") for value in CLAUSE_REF_RE.findall(decision.reference_exact)]
        for rule in rules:
            if rule.doc_id != decision.document_id or rule.source_revision != decision.source_revision:
                continue
            grounded, _, occurrences = _verify_rule_quote_grounding(rule, corpus)
            owned = [occ for occ in occurrences if occ.doc_id == decision.document_id
                     and occ.source_revision == decision.source_revision and occ.scope == "document"]
            if (grounded and len(owned) == 1
                    and owned[0].char_start <= decision.reference_start < decision.reference_end <= owned[0].char_end
                    and len(clauses) == 1
                    and [value.strip().rstrip(".") for value in CLAUSE_REF_RE.findall(rule.source_quote)].count(clauses[0]) == 1):
                owner_count += 1
        if owner_count != 1:
            identity = [decision.tenant_id, decision.document_id, decision.source_revision,
                        decision.converted_text_sha256, decision.reference_start, decision.reference_end,
                        decision.target_start, decision.target_end]
            digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
            unmatched.append(digest)
    return unmatched
