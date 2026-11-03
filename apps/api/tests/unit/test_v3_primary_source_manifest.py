"""Selected primary rules must all bind before joint assessment review."""
from dataclasses import replace

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.models import RuleEntity
from app.modules.ai.v3.primary_source_manifest import build_primary_source_manifest


def sample():
    source = "Вводный текст. Сотрудник сверяет документ. Далее выполняется запись."
    quote = "Сотрудник сверяет документ."
    start = source.index(quote)
    document = DirectSourceDocument(doc_id="d1", title="Документ", filename="a.txt",
        category="general", source_revision="rev1", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="tenant", documents=(document,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="r1", section="Раздел", title="Сверка", statement=quote,
        source_quote=quote, doc_id="d1", source_revision="rev1", source_start=start,
        source_end=start + len(quote))
    return corpus, rule


def build(corpus, rules, tenant="tenant", docs=("d1",)):
    return build_primary_source_manifest(corpus, rules, expected_tenant_id=tenant, expected_document_ids=docs)


def test_selected_source_is_bound_and_changed_fragment_invalidates_fingerprint():
    corpus, rule = sample()
    first = build(corpus, (rule,))
    assert first is not None and first.fragments == (rule.source_quote,)
    changed = replace(rule, source_end=rule.source_end + len(" Далее выполняется запись."))
    second = build(corpus, (changed,))
    assert second is not None and first.fingerprint != second.fingerprint


def test_wrong_tenant_document_set_duplicates_and_unresolved_rule_hold():
    corpus, rule = sample()
    assert build(corpus, (rule,), tenant="other") is None
    assert build(corpus, (rule,), docs=("d1", "d2")) is None
    assert build(corpus, (rule,), docs=("d1", "d1")) is None
    assert build(corpus, (rule, rule)) is None
    assert build(corpus, (rule, replace(rule, rule_id="r2", source_revision="old"))) is None
    assert build(corpus, ()) is None


def test_repeated_quote_is_not_guessed_even_when_rule_span_contains_one_occurrence():
    corpus, rule = sample()
    doc = corpus.documents[0]
    corpus = replace(corpus, documents=(replace(doc, source_text=doc.source_text + " " + rule.source_quote),))
    assert build(corpus, (rule,)) is None


def test_rule_semantics_change_fingerprint_even_if_quote_is_unchanged():
    corpus, rule = sample()
    first = build(corpus, (rule,))
    second = build(corpus, (replace(rule, conditions=("При наличии документа",)),))
    assert first is not None and second is not None
    assert first.fingerprint != second.fingerprint


def test_malformed_identity_values_hold():
    corpus, rule = sample()
    assert build(corpus, (replace(rule, rule_id=[]),)) is None
    assert build(corpus, (rule,), docs=(["d1"],)) is None
