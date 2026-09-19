from scripts.dev.run_semantic_block_smoke import SOURCES, corpus_for

from app.modules.ai.evidence_engine.application import build_evidence_source


def test_synthetic_collections_preserves_xlsx_matrix_cells_for_evidence_course() -> None:
    """The synthetic harness must retain the production chunker worksheet contract."""

    corpus = corpus_for(SOURCES["synthetic-collections"], "synthetic-collections")

    assert corpus.documents[0].filename == "synthetic-collections.xlsx"
    assert all(chunk.headings == ("[Worksheet] Коллекции",) for chunk in corpus.documents[0].chunks)

    bundle = build_evidence_source(corpus)
    facts = [fact for section in bundle.document.sections for fact in section.facts]

    assert {(fact.subject, fact.attribute, fact.value) for fact in facts} == {
        ("Север", "Назначение", "Для спальни"),
        ("Берег", "Назначение", "Для прихожей"),
        ("Линия", "Назначение", "Для гостиной"),
        ("Север", "Материал фасада", "МДФ"),
        ("Берег", "Материал фасада", "ЛДСП"),
        ("Линия", "Материал фасада", "Массив дерева"),
        ("Север", "Уход", "Протирать мягкой сухой тканью; абразивные средства запрещены"),
        ("Берег", "Уход", "Удалять загрязнения слегка влажной тканью и сразу вытирать насухо"),
        ("Линия", "Уход", "Протирать сухой мягкой тканью; беречь от длительного воздействия воды"),
    }
    assert {fact.subject for fact in facts} == {"Север", "Берег", "Линия"}
    assert len(facts) == 9
