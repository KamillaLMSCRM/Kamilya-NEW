from app.modules.ai.lesson_quality import evaluate_lesson_quality


def test_sparse_source_accepts_a_short_but_grounded_lesson() -> None:
    result = evaluate_lesson_quality(
        title="Коллекция Чикаго",
        content="## Коллекция Чикаго\n\nШкаф Чикаго имеет модульную конструкцию.",
        source_chunks=["Коллекция Чикаго. Шкаф имеет модульную конструкцию."],
    )

    assert result.accepted is True
    assert result.reason_codes == ()


def test_generic_lesson_without_source_facts_is_rejected() -> None:
    result = evaluate_lesson_quality(
        title="Коллекция Чикаго",
        content=(
            "## Введение\n\nВ этом уроке мы разберём важную тему. "
            "Материал поможет лучше понять ассортимент. "
            "Подведём итоги: теперь вы знаете основные моменты."
        ),
        source_chunks=[
            "Коллекция Чикаго включает шкаф 3DG2S и зеркало LUS/7/10. "
            "Фасады выполнены в цвете дуб вотан."
        ],
    )

    assert result.accepted is False
    assert "insufficient_source_anchors" in result.reason_codes
    assert "generic_filler_dominates" in result.reason_codes


def test_substantive_product_lesson_is_accepted() -> None:
    source = (
        "Коллекция Чикаго включает шкаф 3DG2S и зеркало LUS/7/10. "
        "Фасады выполнены в цвете дуб вотан. Шкаф подходит для хранения одежды."
    )
    result = evaluate_lesson_quality(
        title="Как подобрать элементы Чикаго",
        content=(
            "## Как подобрать элементы Чикаго\n\n"
            "Для хранения одежды предложите шкаф 3DG2S. "
            "Зеркало LUS/7/10 дополняет комплект. "
            "Оба элемента представлены с фасадами в цвете дуб вотан."
        ),
        source_chunks=[source],
    )

    assert result.accepted is True
    assert result.source_anchor_matches >= 4


def test_exact_sentence_repetition_inside_lesson_is_rejected() -> None:
    repeated = "Шкаф Чикаго имеет модульную конструкцию и подходит для хранения одежды."
    result = evaluate_lesson_quality(
        title="Коллекция Чикаго",
        content=f"## Коллекция Чикаго\n\n{repeated} {repeated}",
        source_chunks=[repeated],
    )

    assert result.accepted is False
    assert "repeated_lesson_sentence" in result.reason_codes


def test_title_alone_cannot_supply_source_grounding() -> None:
    result = evaluate_lesson_quality(
        title="Emergency response",
        content="This lesson provides an important general overview.",
        source_chunks=["Emergency response must be escalated within fifteen minutes."],
    )

    assert result.accepted is False
    assert "insufficient_source_anchors" in result.reason_codes


def test_tabular_association_cannot_be_strengthened_into_causation() -> None:
    source = (
        "Коллекция Альфа; материал ЛДСП; преимущество модульная компоновка. "
        "Коллекция Бета; материал МДФ; преимущество светлые фасады."
    )

    result = evaluate_lesson_quality(
        title="Материалы коллекций",
        content=(
            "## Материалы коллекций\n\n"
            "Альфа изготовлена из ЛДСП, Бета — из МДФ. "
            "Материал прямо связан с преимуществом коллекции, поэтому при "
            "консультации важно называть их вместе."
        ),
        source_chunks=[source],
    )

    assert result.accepted is False
    assert "unsupported_relationship_claim" in result.reason_codes


def test_tabular_association_remains_valid_when_described_neutrally() -> None:
    source = (
        "Коллекция Альфа; материал ЛДСП; преимущество модульная компоновка. "
        "Коллекция Бета; материал МДФ; преимущество светлые фасады."
    )

    result = evaluate_lesson_quality(
        title="Материалы коллекций",
        content=(
            "## Материалы коллекций\n\n"
            "Для Альфы в источнике указаны ЛДСП и модульная компоновка. "
            "Для Беты указаны МДФ и светлые фасады."
        ),
        source_chunks=[source],
    )

    assert result.accepted is True
    assert "unsupported_relationship_claim" not in result.reason_codes


def test_supporting_catalog_cannot_be_used_to_justify_primary_scenario() -> None:
    source = (
        "Коллекция Альфа; сценарий консультации: уточнить размеры помещения. "
        "Каталог: SKU-0006, размер 900x400; SKU-0012, размер 1000x400."
    )

    result = evaluate_lesson_quality(
        title="Коллекция Альфа",
        content=(
            "Для Альфы указан сценарий: уточнить размеры помещения. "
            "В каталоге встречаются разные размеры, значит уточнение размеров "
            "является рабочим шагом для подбора."
        ),
        source_chunks=[source],
    )

    assert result.accepted is False
    assert "unsupported_relationship_claim" in result.reason_codes


def test_primary_attributes_cannot_be_given_an_invented_causal_heading() -> None:
    source = (
        "Коллекция Альфа; преимущество: модульная компоновка; "
        "сценарий консультации: уточнить размеры помещения."
    )

    result = evaluate_lesson_quality(
        title="Коллекция Альфа",
        content=(
            "## Как преимущество определяет шаг консультации\n\n"
            "Для Альфы указаны модульная компоновка и уточнение размеров помещения."
        ),
        source_chunks=[source],
    )

    assert result.accepted is False
    assert "unsupported_relationship_claim" in result.reason_codes
