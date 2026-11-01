"""Decision-level inventory does not hide unmatched source references."""

import hashlib
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus
from app.modules.ai.v3.reference_coverage import unmatched_confirmed_references
from tests.unit.test_v3_reference_decisions import setup_decision


@pytest.mark.parametrize("owners", [0, 1, 2])
def test_reference_coverage_counts_rule_records_not_ids(owners):
    doc, decision, rule = setup_decision()
    source = doc.source_text or ""
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,))
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    grounded = replace(rule, source_quote="Порядок: см. п. 2.")
    entries = [grounded] * owners
    unmatched = unmatched_confirmed_references(corpus, entries, (decision,))
    assert len(unmatched) == (0 if owners == 1 else 1)
    assert all(len(identity) == 64 and decision.reference_exact not in identity for identity in unmatched)


def test_repeated_source_quote_is_not_a_unique_owner():
    doc, decision, rule = setup_decision()
    source = (doc.source_text or "") + "\nПорядок: см. п. 2."
    chunk = DirectSourceChunk(chunk_id="c", doc_id=doc.doc_id, doc_name="d", title="d", headings=(),
                              text=source, source_revision=doc.source_revision, chunk_index=0)
    doc = replace(doc, chunks=(chunk,), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant-1", documents=(doc,), total_chars=len(source), total_chunks=1)
    decision = replace(decision, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest())
    rule = replace(rule, source_quote="Порядок: см. п. 2.", source_end=len(source))
    assert len(unmatched_confirmed_references(corpus, [rule], (decision,))) == 1
