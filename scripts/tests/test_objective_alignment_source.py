from app.modules.ai.evidence_engine.application import build_evidence_source
from scripts.dev.objective_alignment.source import build_complete_source
from scripts.dev.run_semantic_block_smoke import corpus_for


def test_table_adjacent_rule_survives_without_promoting_or_repeating_cells():
    note = "Перед выбором режима проверьте маркировку устройства."
    text = "# [Worksheet] Коллекции\n\n" + note + "\n\n| Серия | Режим |\n|---|---|\n| Альфа | Медленно |\n| Бета | Быстро |\n"
    corpus = corpus_for(text, "synthetic-collections")
    baseline = build_evidence_source(corpus)
    assert not any(note in fact.value for fact in baseline.all_facts)
    fixed = build_complete_source(corpus)
    assert sum(fact.value == note for fact in fixed.all_facts) == 1
    assert sum(fact.value == "Медленно" for fact in fixed.all_facts) == 1
    assert [(s.section_id, s.role) for s in fixed.document.sections] == [
        (s.section_id, s.role) for s in baseline.document.sections]


def test_narrative_only_document_is_unchanged():
    corpus = corpus_for("Сначала проверьте номер заявки. Затем зарегистрируйте результат проверки.", "synthetic-policy")
    assert build_complete_source(corpus) == build_evidence_source(corpus)


def test_plain_table_does_not_create_empty_or_header_notes():
    text = "# [Worksheet] Коллекции\n\n| Серия | Режим |\n|---|---|\n| Альфа | Медленно |\n"
    corpus = corpus_for(text, "synthetic-collections")
    assert build_complete_source(corpus) == build_evidence_source(corpus)
