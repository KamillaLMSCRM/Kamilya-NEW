import hashlib
from dataclasses import replace

import pytest

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity
from app.modules.ai.v3.reference_source_view import build_source_reference_view
from app.modules.ai.v3.source_reference_decisions import SourceReferenceDecision


def fixture():
    source = "Порядок: см. п. 2.\n2. Подписать билет и внести отметку. Затем сохранить документ."
    ref, target = "см. п. 2", "Подписать билет и внести отметку."
    chunk = DirectSourceChunk("c", "doc", "d", "d", (), source, "rev", 0)
    doc = DirectSourceDocument("doc", "d", "d", "general", "rev", (chunk,), source_text=source)
    corpus = DirectSourceCorpus("tenant", (doc,), len(source), 1)
    a, b = source.index(ref), source.index(target)
    decision = SourceReferenceDecision("tenant", "doc", "rev", hashlib.sha256(source.encode()).hexdigest(),
                                       a, a + len(ref), ref, b, b + len(target), target, "owner_chat")
    referring = RuleEntity("r", "s", "ref", "См. п. 2 и опять п. 2", conditions=("Если готово", "см. п. 3"),
                           timing="согласно п. 2", source_quote="Порядок: см. п. 2.", doc_id="doc",
                           source_revision="rev", source_start=0, source_end=len(source))
    target_rule = replace(referring, rule_id="t", statement="Домысел", conditions=("Если готово",), timing="",
                          source_quote=source[b:])
    model = DocumentRuleModel("d", "hash", (referring, target_rule))
    return corpus, model, decision


def test_literal_quotes_quarantine_and_immutable_model():
    corpus, model, decision = fixture()
    before = model.to_dict()
    view = build_source_reference_view(corpus, model, (decision,))
    assert not view.unresolved_decision_ids
    assert view.rule_model.rules[0].statement == "Порядок: см. п. 2."
    assert view.rule_model.rules[1].statement == model.rules[1].source_quote
    assert decision.target_exact in view.rule_model.rules[1].statement
    assert view.rule_model.rules[0].conditions == ("Если готово",)
    assert view.rule_model.rules[0].timing == ""
    assert model.to_dict() == before
    assert view.changes[0].quarantined_fields == ("statement", "conditions", "timing")
    assert all(c.requires_semantic_review and len(c.original_hash) == 64 and len(c.rebuilt_hash) == 64 for c in view.changes)
    assert view == build_source_reference_view(corpus, model, (decision,))


def test_no_decision_identity():
    corpus, model, _ = fixture()
    view = build_source_reference_view(corpus, model, ())
    assert view.rule_model is model and not view.changes and not view.unresolved_decision_ids


@pytest.mark.parametrize("case", ["duplicate", "revision", "tenant", "unit", "target", "owner", "overlap", "malformed", "extra_ref"])
def test_ambiguous_or_invalid_is_held(case):
    corpus, model, d = fixture()
    decisions = (d,)
    if case == "duplicate":
        decisions = (d, d)
    elif case == "revision":
        decisions = (replace(d, source_revision="other"),)
    elif case == "tenant":
        decisions = (replace(d, tenant_id="other"),)
    elif case == "unit":
        model = replace(model, rules=(replace(model.rules[0], source_end=2), model.rules[1]))
    elif case == "target":
        model = replace(model, rules=model.rules[:1])
    elif case == "owner":
        model = replace(model, rules=(*model.rules, replace(model.rules[0], rule_id="duplicate")))
    elif case == "overlap":
        decisions = (d, replace(d, reference_start=d.reference_start + 1, reference_exact=d.reference_exact[1:]))
    elif case == "malformed":
        decisions = (replace(d, target_start="bad"),)
    elif case == "extra_ref":
        source = corpus.documents[0].source_text + " см. п. 3"
        doc = replace(corpus.documents[0], source_text=source, chunks=(replace(corpus.documents[0].chunks[0], text=source),))
        corpus = replace(corpus, documents=(doc,))
        d = replace(d, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest())
        decisions = (d,)
        model = replace(model, rules=(model.rules[0], replace(model.rules[1], source_quote=source[d.target_start:], source_end=len(source))))
    view = build_source_reference_view(corpus, model, decisions)
    assert view.rule_model is model and not view.changes and view.unresolved_decision_ids


def test_saved_case_offsets_and_target_containment():
    ref = "см. п. 2" + "x" * (33 - len("см. п. 2"))
    ref_quote = "A" * 104 + ref + "Z"
    target = "T" * 190
    target_quote = target + "Q" * (512 - len(target))
    source = "_" * 2021 + ref_quote + "_" * (3037 - 2159) + target_quote
    chunk = DirectSourceChunk("c", "doc", "d", "d", (), source, "rev", 0)
    doc = DirectSourceDocument("doc", "d", "d", "general", "rev", (chunk,), source_text=source)
    corpus = DirectSourceCorpus("tenant", (doc,), len(source), 1)
    d = SourceReferenceDecision("tenant", "doc", "rev", hashlib.sha256(source.encode()).hexdigest(),
                                2125, 2158, ref, 3037, 3227, target, "owner_chat")
    first = RuleEntity("r", "s", "r", "paraphrase", source_quote=ref_quote, doc_id="doc",
                       source_revision="rev", source_start=2021, source_end=2159)
    second = replace(first, rule_id="t", source_quote=target_quote, source_start=3037, source_end=3549)
    model = DocumentRuleModel("d", "hash", (first, second))
    view = build_source_reference_view(corpus, model, (d,))
    assert not view.unresolved_decision_ids
    assert view.rule_model.rules[1].statement == target_quote
    assert [(c.source_quote_start, c.source_quote_end) for c in view.changes] == [(2021, 2159), (3037, 3549)]


def test_reference_bearing_navigation_and_actor_hints_are_quarantined():
    corpus, model, decision = fixture()
    referring = replace(model.rules[0], title="см. п. 9", actors=("operator", "п. 99"))
    model = replace(model, rules=(referring, model.rules[1]))
    view = build_source_reference_view(corpus, model, (decision,))
    assert not view.unresolved_decision_ids
    assert view.rule_model.rules[0].title == ""
    assert view.rule_model.rules[0].actors == ("operator",)
    assert {"title", "actors"} <= set(view.changes[0].quarantined_fields)
    assert model.rules[0] == referring
