"""Bind every selected primary rule to its owned source before a joint review.

This checks the selected rules, not the completeness of their inventory or the
meaning of the generated questions. A valid manifest is not a quality verdict.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.modules.ai.direct_source import DirectSourceCorpus
from app.modules.ai.v3.citation_review import bind_displayed_citation
from app.modules.ai.v3.models import RuleEntity


@dataclass(frozen=True)
class PrimarySourceManifest:
    fingerprint: str
    fragments: tuple[str, ...]


def build_primary_source_manifest(
    corpus: DirectSourceCorpus,
    rules: tuple[RuleEntity, ...],
    *,
    expected_tenant_id: str,
    expected_document_ids: tuple[str, ...],
) -> PrimarySourceManifest | None:
    """Return None if any selected rule or admitted document is ambiguous.

    The caller must obtain expected IDs from its already authenticated job;
    this function does not itself authenticate a caller or query storage.
    """
    if (not isinstance(expected_tenant_id, str) or not expected_tenant_id
            or not all(isinstance(value, str) and value for value in expected_document_ids)
            or not all(isinstance(doc.doc_id, str) and doc.doc_id for doc in corpus.documents)
            or not all(isinstance(rule, RuleEntity) and isinstance(rule.rule_id, str) and rule.rule_id
                       for rule in rules)):
        return None
    doc_ids = tuple(doc.doc_id for doc in corpus.documents)
    if (corpus.tenant_id != expected_tenant_id
            or not expected_document_ids or len(set(expected_document_ids)) != len(expected_document_ids)
            or len(set(doc_ids)) != len(doc_ids) or set(doc_ids) != set(expected_document_ids)
            or not rules or any(not rule.rule_id for rule in rules)
            or len({rule.rule_id for rule in rules}) != len(rules)):
        return None
    fragments: list[str] = []
    bindings: list[dict[str, object]] = []
    for rule in rules:
        identity = bind_displayed_citation(corpus, rule, rule.source_quote)
        docs = [doc for doc in corpus.documents if doc.doc_id == rule.doc_id]
        if identity is None or len(docs) != 1 or docs[0].source_text is None:
            return None
        start, end = rule.source_start, rule.source_end
        if type(start) is not int or type(end) is not int:
            return None
        fragment = docs[0].source_text[start:end]
        if not fragment.strip():
            return None
        fragments.append(fragment)
        try:
            rule_bytes = json.dumps(rule.to_dict(), sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            return None
        bindings.append({"rule_id": rule.rule_id, "source_identity": identity,
                         "rule_sha256": hashlib.sha256(rule_bytes).hexdigest(),
                         "fragment_sha256": hashlib.sha256(fragment.encode("utf-8")).hexdigest()})
    payload = {"policy": "v3-primary-source-manifest-v1", "tenant": expected_tenant_id,
               "document_ids": sorted(expected_document_ids), "bindings": bindings}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    return PrimarySourceManifest(fingerprint=digest, fragments=tuple(fragments))
