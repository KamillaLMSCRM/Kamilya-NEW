"""Build a non-authoritative planning view from uniquely owned source quotations."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from typing import Any

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.cooperative_budget import PreclaimYieldError
from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision, reference_context_for_rules

POLICY = "source-quotation-view-v1"


class SourceReferenceReviewRequiredError(PreclaimYieldError):
    """Known pre-author source hold; preserve completed work and its reservation."""

    def __init__(self, decision_ids: tuple[str, ...]):
        self.decision_ids = decision_ids
        super().__init__("source_reference_review_required")


def _hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decision_id(decision: object) -> str:
    return _hash(asdict(decision) if isinstance(decision, SourceReferenceDecision) else {"invalid_decision_type": type(decision).__name__})


@dataclass(frozen=True, slots=True)
class SourceReferenceChange:
    decision_id: str
    rule_id: str
    role: str
    original_hash: str
    rebuilt_hash: str
    source_quote_start: int
    source_quote_end: int
    source_quote_hash: str
    quarantined_fields: tuple[str, ...]
    requires_semantic_review: bool = True


@dataclass(frozen=True, slots=True)
class SourceReferenceView:
    rule_model: DocumentRuleModel
    policy: str
    fingerprint: str
    changes: tuple[SourceReferenceChange, ...]
    unresolved_decision_ids: tuple[str, ...]


def build_source_reference_view(
    corpus: DirectSourceCorpus, model: DocumentRuleModel, decisions: tuple[SourceReferenceDecision, ...],
) -> SourceReferenceView:
    """Return literal quotations only when the entire batch binds unambiguously.

    Original extracted fields are hints, not semantic approvals. Invalid inputs leave
    the model untouched and are reported as opaque decision hashes.
    """
    from app.modules.ai.v3.service import CLAUSE_REF_RE, QuoteOccurrence, _verify_rule_quote_grounding

    ids = tuple(_decision_id(d) for d in decisions)
    original_hash = _hash(model.to_dict())

    def result(rule_model: DocumentRuleModel, changes: tuple[SourceReferenceChange, ...],
               unresolved: tuple[str, ...]) -> SourceReferenceView:
        fingerprint = _hash([POLICY, original_hash, _hash(rule_model.to_dict()), ids,
                             [asdict(c) for c in changes], unresolved])
        return SourceReferenceView(rule_model, POLICY, fingerprint, changes, unresolved)

    if not decisions:
        return result(model, (), ())
    try:
        reference_context_for_rules(corpus.tenant_id, corpus.documents, decisions, ())
    except (ValueError, TypeError, AttributeError):
        return result(model, (), ids)

    # Source spans and rule identities may not be shared across decisions, even
    # when the individual authorizations are valid in isolation.
    spans: list[tuple[str, str, int, int]] = []
    for d in decisions:
        for start, end in ((d.reference_start, d.reference_end), (d.target_start, d.target_end)):
            if any(doc == d.document_id and rev == d.source_revision and start < other_end and other_start < end
                   for doc, rev, other_start, other_end in spans):
                return result(model, (), ids)
            spans.append((d.document_id, d.source_revision, start, end))
    if len({r.rule_id for r in model.rules}) != len(model.rules) or any(not r.rule_id for r in model.rules):
        return result(model, (), ids)

    bindings = []
    used: set[str] = set()
    for decision, decision_id in zip(decisions, ids, strict=True):
        clause = CLAUSE_REF_RE.findall(decision.reference_exact)
        if len(clause) != 1:
            return result(model, (), ids)
        owners: list[tuple[RuleEntity, QuoteOccurrence]] = []
        targets: list[tuple[RuleEntity, QuoteOccurrence]] = []
        reference_claims = target_claims = 0
        for rule in model.rules:
            if rule.doc_id != decision.document_id or rule.source_revision != decision.source_revision:
                continue
            # Source-unit bounds are required; an unscoped match is not ownership.
            if type(rule.source_start) is not int or type(rule.source_end) is not int:
                continue
            grounded, _, occurrences = _verify_rule_quote_grounding(rule, corpus)
            owned = [o for o in occurrences if o.doc_id == decision.document_id
                     and o.source_revision == decision.source_revision and o.scope == "document"]
            if not grounded or len(owned) != 1:
                continue
            occ = owned[0]
            if not rule.source_start <= occ.char_start < occ.char_end <= rule.source_end:
                continue
            refs = CLAUSE_REF_RE.findall(occ.matched_text)
            if occ.char_start <= decision.reference_start < decision.reference_end <= occ.char_end:
                reference_claims += 1
            if occ.char_start <= decision.target_start < decision.target_end <= occ.char_end:
                target_claims += 1
            if (occ.char_start <= decision.reference_start < decision.reference_end <= occ.char_end
                    and len(refs) == 1 and refs[0].strip().rstrip(".") == clause[0].strip().rstrip(".")):
                owners.append((rule, occ))
            if (occ.char_start <= decision.target_start < decision.target_end <= occ.char_end and not refs):
                targets.append((rule, occ))
        if reference_claims != 1 or target_claims != 1 or len(owners) != 1 or len(targets) != 1:
            return result(model, (), ids)
        if owners[0][0].rule_id == targets[0][0].rule_id or any(
            item[0].rule_id in used for item in (owners[0], targets[0])
        ):
            return result(model, (), ids)
        for role, (rule, occ) in (("referring", owners[0]), ("target", targets[0])):
            used.add(rule.rule_id)
            bindings.append((decision_id, role, rule, occ))

    replacements: dict[str, RuleEntity] = {}
    changes = []
    for decision_id, role, rule, occ in bindings:
        updates: dict[str, Any] = {"statement": occ.matched_text, "source_quote": occ.matched_text}
        quarantined = [field for field in ("statement", "source_quote") if getattr(rule, field) != occ.matched_text]
        if CLAUSE_REF_RE.search(rule.title):
            updates["title"] = ""
            quarantined.append("title")
        actors = tuple(value for value in rule.actors if not CLAUSE_REF_RE.search(value))
        if actors != rule.actors:
            updates["actors"] = actors
            quarantined.append("actors")
        for field in ("conditions", "exceptions"):
            values = getattr(rule, field)
            filtered = tuple(v for v in values if not CLAUSE_REF_RE.search(v))
            if filtered != values:
                updates[field] = filtered
                quarantined.append(field)
        for field in ("timing", "consequences"):
            if CLAUSE_REF_RE.search(getattr(rule, field)):
                updates[field] = ""
                quarantined.append(field)
        rebuilt = replace(rule, **updates)
        replacements[rule.rule_id] = rebuilt
        changes.append(SourceReferenceChange(
            decision_id, rule.rule_id, role, _hash(rule.to_dict()), _hash(rebuilt.to_dict()),
            occ.char_start, occ.char_end, hashlib.sha256(occ.matched_text.encode("utf-8")).hexdigest(),
            tuple(quarantined),
        ))
    view = replace(model, rules=tuple(replacements.get(rule.rule_id, rule) for rule in model.rules))
    return result(view, tuple(changes), ())
