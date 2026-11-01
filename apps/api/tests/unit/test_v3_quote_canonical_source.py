"""A stale chunk cannot certify a quote missing from the canonical working text."""

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.models import RuleEntity
from app.modules.ai.v3.service import _verify_rule_quote_grounding, find_quote_occurrences_in_corpus


def corpus(canonical: str | None, chunk_text: str) -> DirectSourceCorpus:
    chunk = DirectSourceChunk(chunk_id="old-chunk", doc_id="doc", doc_name="source", title="source", headings=(),
                              text=chunk_text, source_revision="rev", chunk_index=0)
    doc = DirectSourceDocument(doc_id="doc", title="source", filename="source", category="general",
                               source_revision="rev", chunks=(chunk,), source_text=canonical)
    return DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=len(canonical or chunk_text), total_chunks=1)


def test_old_chunk_quote_absent_from_canonical_text_is_not_verified():
    data = corpus("Только исправленное обязательство.", "Только устаревшая ошибка.")
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote="устаревшая ошибка",
                      doc_id="doc", source_revision="rev")
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert not verified


def test_canonical_document_coordinates_take_precedence_over_old_chunk():
    data = corpus("Пролог. Согласование обязательно. Эпилог.", "Согласование обязательно.")
    matches = find_quote_occurrences_in_corpus("Согласование обязательно.", data)
    assert len(matches) == 1 and matches[0].scope == "document" and matches[0].char_start == 8


def test_legacy_document_without_full_text_keeps_chunk_provenance():
    data = corpus(None, "Проверенное старое содержимое.")
    matches = find_quote_occurrences_in_corpus("старое содержимое", data)
    assert len(matches) == 1 and matches[0].scope == "chunk" and matches[0].chunk_id == "old-chunk"


def test_canonical_text_with_conflicting_chunk_revision_is_not_certified():
    chunk = DirectSourceChunk(chunk_id="old", doc_id="doc", doc_name="source", title="source", headings=(),
                              text="Точная цитата", source_revision="old", chunk_index=0)
    doc = DirectSourceDocument(doc_id="doc", title="source", filename="source", category="general",
                               source_revision="new", chunks=(chunk,), source_text="Точная цитата")
    data = DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=13, total_chunks=1)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote="Точная цитата",
                      doc_id="doc", source_revision="new")
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert not verified


def test_canonical_text_with_foreign_chunk_owner_is_not_certified():
    chunk = DirectSourceChunk(chunk_id="foreign", doc_id="other", doc_name="source", title="source", headings=(),
                              text="Точная цитата", source_revision="rev", chunk_index=0)
    doc = DirectSourceDocument(doc_id="doc", title="source", filename="source", category="general",
                               source_revision="rev", chunks=(chunk,), source_text="Точная цитата")
    data = DirectSourceCorpus(tenant_id="tenant", documents=(doc,), total_chars=13, total_chunks=1)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote="Точная цитата",
                      doc_id="doc", source_revision="rev")
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert not verified


def test_quote_from_neighboring_source_unit_is_not_certified_for_target_rule():
    source = "Первое правило. Второе правило."
    data = corpus(source, source)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote="Второе правило.",
                      doc_id="doc", source_revision="rev", source_start=0, source_end=len("Первое правило."))
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert not verified


def test_quote_inside_target_source_unit_remains_verifiable():
    source = "Первое правило. Второе правило."
    data = corpus(source, source)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote="Первое правило.",
                      doc_id="doc", source_revision="rev", source_start=0, source_end=len("Первое правило."))
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert verified


def test_rule_source_unit_cannot_extend_beyond_canonical_document():
    source = "Первое правило."
    data = corpus(source, source)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", source_quote=source,
                      doc_id="doc", source_revision="rev", source_start=0, source_end=len(source) + 100)
    verified, _, _ = _verify_rule_quote_grounding(rule, data)
    assert not verified
