"""Citation expansion proposes only exact source spans and is not semantic approval."""

from dataclasses import replace

from app.modules.ai.direct_source import DirectSourceCorpus, DirectSourceDocument
from app.modules.ai.v3.citation_expansion import (
    citation_question_fingerprint,
    propose_rule_quote_expansion,
    stage_citation_candidate,
)
from app.modules.ai.v3.citation_review import build_citation_review_items
from app.modules.ai.v3.models import RuleEntity, V3Lesson, V3Option, V3QuestionVariant, V3ScenarioCase


def test_contiguous_source_quote_candidate_rejects_identity_and_content_drift():
    text = "Выполнить первое. Выполнить второе."
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="r", chunks=(), source_text=text)
    corpus = DirectSourceCorpus(tenant_id="t", documents=(doc,), total_chars=len(text), total_chunks=0)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", doc_id="d",
                      source_revision="r", source_start=0, source_end=len(text), source_quote=text)
    short = "Выполнить первое."
    assert propose_rule_quote_expansion(corpus, rule, short) == text
    assert propose_rule_quote_expansion(corpus, rule, text) is None
    assert propose_rule_quote_expansion(corpus, replace(rule, source_revision="old"), short) is None
    assert propose_rule_quote_expansion(corpus, replace(rule, source_quote="Выполнить второе."), short) is None
    assert propose_rule_quote_expansion(replace(corpus, documents=(replace(doc, source_text=text + short),)),
                                       rule, short) is None


def test_apply_replaces_only_matching_citation_and_rejects_identity_collision():
    variant = V3QuestionVariant(variant_id="v1", branch_context="", scenario_premise="Ситуация",
        prompt="Что сделать?", correct_option=V3Option(text="Первое и второе", is_correct=True),
        distractor_pool=(V3Option(text="Первое", is_correct=False), V3Option(text="Второе", is_correct=False),
                         V3Option(text="Ничего", is_correct=False)), explanation="Нужны оба действия.",
        source_quote="Выполнить первое.")
    case = V3ScenarioCase(case_id="c", rule_id="r", learning_objective="Правило", variants=(variant,))
    question = variant.assemble_question(seed=42)
    unrelated = replace(question, question_id="other")
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="Текст", covered_rule_ids=("r",),
                      cases=(case,), questions=(question, unrelated))
    source = "Выполнить первое. Выполнить второе."
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="r", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="t", documents=(doc,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", doc_id="d",
                      source_revision="r", source_start=0, source_end=len(source), source_quote=source)
    items, issues = build_citation_review_items(lesson, [rule], corpus)
    assert not issues and len(items) == 1
    fingerprint = citation_question_fingerprint(lesson, question.question_id)
    assert fingerprint is not None
    updated = stage_citation_candidate(lesson, rule, corpus, items[0], source, fingerprint)
    assert updated is not None
    assert replace(updated.cases[0].variants[0], source_quote=variant.source_quote) == variant
    assert updated.questions[1] == unrelated and updated.questions[0].options == question.options
    collision = replace(lesson, questions=(replace(question, prompt="Другой вопрос"),))
    assert stage_citation_candidate(collision, rule, corpus, items[0], source, fingerprint) is None
    assert stage_citation_candidate(lesson, rule, corpus, items[0], "Чужая цитата", fingerprint) is None
    assert stage_citation_candidate(lesson, rule, corpus, {**items[0], "answer": "Другой"}, source, fingerprint) is None
    repeated = replace(question, options=(question.options[0], question.options[1], question.options[1], question.options[3]))
    assert stage_citation_candidate(replace(lesson, questions=(repeated,)), rule, corpus, items[0], source, fingerprint) is None
    changed_distractors = replace(variant, distractor_pool=(replace(variant.distractor_pool[0], text="Другая ошибка"),
                                                           *variant.distractor_pool[1:]))
    changed_lesson = replace(lesson, cases=(replace(case, variants=(changed_distractors,)),))
    assert stage_citation_candidate(changed_lesson, rule, corpus, items[0], source, fingerprint) is None


def test_expanding_two_questions_does_not_revert_first_citation():
    source = "Выполнить первое. Выполнить второе."
    doc = DirectSourceDocument(doc_id="d", title="d", filename="d", category="general",
                               source_revision="r", chunks=(), source_text=source)
    corpus = DirectSourceCorpus(tenant_id="t", documents=(doc,), total_chars=len(source), total_chunks=0)
    rule = RuleEntity(rule_id="r", section="s", title="t", statement="x", doc_id="d",
                      source_revision="r", source_start=0, source_end=len(source), source_quote=source)
    first = V3QuestionVariant(variant_id="v1", branch_context="", scenario_premise="Ситуация", prompt="Что делать?",
        correct_option=V3Option(text="Первое и второе", is_correct=True),
        distractor_pool=(V3Option(text="Первое", is_correct=False), V3Option(text="Второе", is_correct=False),
                         V3Option(text="Ничего", is_correct=False)), explanation="Нужны оба действия.",
        source_quote="Выполнить первое.")
    second = replace(first, variant_id="v2", source_quote="Выполнить второе.")
    case = V3ScenarioCase(case_id="c", rule_id="r", learning_objective="Правило", variants=(first, second))
    lesson = V3Lesson(lesson_id="l", title="t", module_title="m", content="", covered_rule_ids=("r",),
                      cases=(case,), questions=(first.assemble_question(seed=42),))
    items, issues = build_citation_review_items(lesson, [rule], corpus)
    assert not issues and len(items) == 2
    fingerprints = [citation_question_fingerprint(lesson, item["id"]) for item in items]
    assert all(fingerprints)
    staged = stage_citation_candidate(lesson, rule, corpus, items[0], source, fingerprints[0])
    assert staged is not None
    staged_twice = stage_citation_candidate(staged, rule, corpus, items[1], source, fingerprints[1])
    assert staged_twice is not None
    assert [v.source_quote for v in staged_twice.cases[0].variants] == [source, source]
    assert staged_twice.questions[0].source_quote == source
