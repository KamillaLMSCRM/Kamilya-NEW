"""A confirmed target may be a literal subspan of one grounded rule quote."""
import hashlib
from dataclasses import replace

from app.modules.ai.direct_source import DirectSourceChunk, DirectSourceCorpus
from app.modules.ai.v3.models import DocumentRuleModel
from app.modules.ai.v3.reference_source_view import build_source_reference_view
from app.modules.ai.v3.service import _build_curriculum_groups, _verify_rule_quote_grounding
from tests.unit.test_v3_reference_decisions import setup_decision


def test_unique_target_quote_may_include_following_source_context():
    doc, decision, referring = setup_decision()
    source = doc.source_text + " Соседнее подтверждённое последствие."
    chunk = DirectSourceChunk("c", doc.doc_id, "d", "d", (), source, doc.source_revision, 0)
    doc = replace(doc, source_text=source, chunks=(chunk,))
    corpus = DirectSourceCorpus("tenant-1", (doc,), len(source), 1)
    decision = replace(decision, converted_text_sha256=hashlib.sha256(source.encode()).hexdigest())
    referring = replace(referring, section="ref", source_quote="Порядок: см. п. 2.", source_end=len(source))
    target = replace(referring, rule_id="target", section="target", statement="Подписать билет",
                     source_quote=source[decision.target_start:])
    assert _verify_rule_quote_grounding(referring, corpus)[0]
    assert _verify_rule_quote_grounding(target, corpus)[0]
    model = DocumentRuleModel("d", "a" * 64, (referring, target))
    legacy = next(g for g in _build_curriculum_groups(model, corpus=corpus, reference_decisions=(decision,))
                  if referring in g.primary_rules)
    assert legacy.unresolved_dependencies
    view = build_source_reference_view(corpus, model, (decision,))
    group = next(g for g in _build_curriculum_groups(view.rule_model, corpus=corpus,
                 reference_decisions=(decision,), source_view=view) if any(r.rule_id == referring.rule_id for r in g.primary_rules))
    assert target.rule_id in {rule.rule_id for rule in group.context_prerequisite_rules}
    assert not group.unresolved_dependencies
