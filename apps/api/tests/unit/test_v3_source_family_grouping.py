"""Related table conditions must remain visible together in curriculum planning."""

from dataclasses import replace

from app.modules.ai.v3.models import DocumentRuleModel, RuleEntity
from app.modules.ai.v3.service import _build_curriculum_groups
from app.modules.ai.v3.source_units import coalesce_table_headers, plan_source_units, source_table_topic


def rule(name: str, family: str = "") -> RuleEntity:
    return RuleEntity(rule_id=name, section="Раздел 1", title=name, statement=name, source_family=family)


def test_table_family_crossing_old_five_rule_boundary_is_not_split():
    rules = [rule(f"intro-{i}") for i in range(4)] + [
        rule("category-one-group-one", "doc/table-1"),
        rule("category-one-group-two", "doc/table-1"),
        rule("category-two", "doc/table-1"),
    ]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    table_groups = [g for g in groups if any(r.source_family == "doc/table-1" for r in g.primary_rules)]
    assert len(table_groups) == 1
    assert {r.rule_id for r in table_groups[0].primary_rules} >= {
        "category-one-group-one", "category-one-group-two", "category-two"
    }
    assert {r.rule_id for r in table_groups[0].context_neighbor_rules} == {f"intro-{i}" for i in range(4)}
    assert sum(len(g.primary_rules) for g in groups) == len(rules)


def test_large_table_family_and_duplicate_ids_are_not_split_or_lost():
    rules = [rule("duplicate", "doc/table-1") for _ in range(8)]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) == 1
    assert len(groups[0].primary_rules) == 8
    assert len({r.rule_id for r in groups[0].primary_rules}) == 8
    assert all(r.source_family == "doc/table-1" for r in groups[0].primary_rules)


def test_large_table_with_labeled_rows_splits_primary_rules_but_retains_sibling_context():
    rules = [replace(rule(f"a-{i}", "doc/table-1"), source_topic="Категория А") for i in range(7)]
    rules += [replace(rule(f"b-{i}", "doc/table-1"), source_topic="Категория Б") for i in range(7)]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) == 2
    assert [{r.source_topic for r in g.primary_rules} for g in groups] == [{"Категория А"}, {"Категория Б"}]
    for group in groups:
        assert {r.rule_id for r in group.primary_rules + group.context_neighbor_rules} == {r.rule_id for r in rules}
    assert sum(len(g.primary_rules) for g in groups) == len(rules)


def test_unlabeled_table_row_is_not_treated_as_independent_topic():
    source = "| Тема | Правило |\n| --- | --- |\n| Первый | Действие |\n| | Исключение |\n"
    units = coalesce_table_headers(plan_source_units(source), source)
    assert [source_table_topic(unit) for unit in units] == ["Первый", ""]
    rules = [replace(rule(f"a-{i}", "doc/table-1"), source_topic="Первый") for i in range(7)]
    rules += [rule(f"b-{i}", "doc/table-1") for i in range(7)]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) == 1 and len(groups[0].primary_rules) == len(rules)


def test_two_rules_from_same_exact_source_span_do_not_split_at_count_boundary():
    rules = [rule(f"intro-{i}") for i in range(4)] + [
        replace(rule("condition"), doc_id="doc", source_revision="rev", source_start=100, source_end=200),
        replace(rule("outcome"), doc_id="doc", source_revision="rev", source_start=100, source_end=200),
    ] + [rule("other")]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    owners = [g for g in groups if any(r.rule_id in {"condition", "outcome"} for r in g.primary_rules)]
    assert len(owners) == 1
    assert {r.rule_id for r in owners[0].primary_rules} >= {"condition", "outcome"}
    assert sum(len(g.primary_rules) for g in groups) == len(rules)


def test_matching_offsets_in_different_documents_are_not_treated_as_one_source_unit():
    from app.modules.ai.v3.service import _source_atomic_blocks

    rules = [
        replace(rule("first"), doc_id="doc-a", source_revision="rev", source_start=100, source_end=200),
        replace(rule("second"), doc_id="doc-b", source_revision="rev", source_start=100, source_end=200),
    ]
    assert len(_source_atomic_blocks(rules)) == 2


def test_matching_table_labels_in_different_documents_do_not_force_one_family():
    from app.modules.ai.v3.service import _source_atomic_blocks

    rules = [
        replace(rule("first", "table-1"), doc_id="doc-a", source_revision="rev"),
        replace(rule("second", "table-1"), doc_id="doc-b", source_revision="rev"),
    ]
    assert len(_source_atomic_blocks(rules)) == 2


def test_same_offsets_in_different_source_revisions_are_not_one_source_unit():
    from app.modules.ai.v3.service import _source_atomic_blocks

    rules = [replace(rule("first", "table-1"), doc_id="doc", source_revision="rev-a", source_start=10, source_end=20),
             replace(rule("second", "table-1"), doc_id="doc", source_revision="rev-b", source_start=10, source_end=20)]
    assert len(_source_atomic_blocks(rules)) == 2


def test_overlapping_family_and_span_relationships_form_one_atomic_block():
    def typed(name, family, start, end):
        return replace(rule(name, family), doc_id="doc", source_revision="rev", source_start=start, source_end=end)

    rules = [rule(f"intro-{i}") for i in range(3)] + [
        typed("a1", "A", 0, 10), typed("a2", "A", 10, 20),
        typed("b1", "B", 10, 20), typed("b2", "B", 20, 30),
    ]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    owners = [g for g in groups if any(r.rule_id in {"a1", "a2", "b1", "b2"} for r in g.primary_rules)]
    assert len(owners) == 1
    assert {r.rule_id for r in owners[0].primary_rules} >= {"a1", "a2", "b1", "b2"}


def test_topic_split_cannot_separate_rules_from_same_exact_source_span():
    rules = [replace(rule(f"r-{i}", "table"), doc_id="doc", source_revision="rev",
                     source_start=100, source_end=200, source_topic="A" if i < 4 else "B") for i in range(8)]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) == 1 and len(groups[0].primary_rules) == 8


def test_cases_linked_only_to_context_are_exposed_for_review_without_dropping_content():
    from app.modules.ai.v3.models import V3Course
    from app.modules.ai.v3.service import _cases_outside_primary_rule_scope

    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
        "lessons": [{"lesson_id": "l", "title": "t", "content": "content", "cases": [
            {"case_id": "primary-case", "rule_id": "primary", "variants": []},
            {"case_id": "context-case", "rule_id": "context", "variants": []},
            {"case_id": "missing-case", "rule_id": "", "variants": []},
        ]}]}).lessons[0]
    result = _cases_outside_primary_rule_scope(lesson, [rule("primary")])
    assert result == [("context-case", "context"), ("missing-case", "")]
    assert len(lesson.cases) == 3


def test_legacy_question_linked_only_to_context_is_not_silently_accepted():
    from app.modules.ai.v3.models import V3Course
    from app.modules.ai.v3.service import _cases_outside_primary_rule_scope

    lesson = V3Course.from_dict({"course_id": "c", "title": "t", "document_sha256": "a" * 64,
        "lessons": [{"lesson_id": "l", "title": "t", "content": "content", "questions": [
            {"question_id": "q-primary", "rule_id": "primary"},
            {"question_id": "q-context", "rule_id": "context"},
        ]}]}).lessons[0]
    assert _cases_outside_primary_rule_scope(lesson, [rule("primary")]) == [("q-context", "context")]


def test_long_source_section_is_segmented_without_losing_source_units():
    rules = [replace(rule(f"r-{i}"), doc_id="doc", source_revision="rev", source_start=i * 9000,
                     source_end=i * 9000 + 8000) for i in range(30)]
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) > 1
    assert {r.rule_id for g in groups for r in g.primary_rules} == {r.rule_id for r in rules}
    assert sum(len(g.primary_rules) for g in groups) == len(rules)


def test_large_table_with_shared_note_does_not_collapse_into_one_unbounded_lesson():
    rules = [replace(rule(f"row-{i}", "table"), doc_id="doc", source_revision="rev",
                     source_start=i * 1000, source_end=i * 1000 + 900, source_topic=f"Topic {i}")
             for i in range(100)]
    rules.append(replace(rule("shared-note", "table"), doc_id="doc", source_revision="rev",
                         source_start=100000, source_end=100100))
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) > 1
    assert {r.rule_id for g in groups for r in g.primary_rules} == {r.rule_id for r in rules}
    assert all(any(r.rule_id == "shared-note" for r in g.primary_rules + g.context_neighbor_rules
                   + g.context_prerequisite_rules) for g in groups)
    assert all(len(g.context_neighbor_rules) <= 13 for g in groups)
    assert all(g.unresolved_dependencies for g in groups)


def test_large_family_with_conflicting_topics_on_one_span_is_not_automatically_split():
    rules = [replace(rule(f"r-{i}", "table"), doc_id="doc", source_revision="rev", source_start=10,
                     source_end=500, source_topic=f"Topic {i}") for i in range(15)]
    rules.append(replace(rule("shared", "table"), doc_id="doc", source_revision="rev",
                         source_start=500, source_end=600))
    groups = _build_curriculum_groups(DocumentRuleModel(document_title="d", document_sha256="a" * 64,
                                                        rules=tuple(rules)))
    assert len(groups) == 1
    assert groups[0].unresolved_dependencies
    assert len(groups[0].primary_rules) == len(rules)
