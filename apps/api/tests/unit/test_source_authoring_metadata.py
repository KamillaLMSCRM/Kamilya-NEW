from app.modules.ai.evidence_engine.application import (
    _narrative_fact_metadata,
    _split_narrative_chunk,
)


def test_equipment_cover_and_tail_are_not_assessment_facts() -> None:
    values = _split_narrative_chunk(
        "Синтетический материал для видеоинструкции Камили. "
        "Все правила и названия вымышлены. "
        "Персональных данных и сведений клиентов нет. "
        "Конец учебного материала."
    )

    assert values == [
        "Синтетический материал для видеоинструкции Камили. Все правила и названия вымышлены. Персональных данных и сведений клиентов нет. Конец учебного материала.",
    ]
    assert all(
        _narrative_fact_metadata(value) == {
            "confidence": 0.0,
            "uncertainty": "source_authoring_metadata",
        }
        for value in values
    )


def test_explicit_authoring_boilerplate_is_recognized_in_ru_kk_and_en() -> None:
    cases = (
        "Урок должен учить правилам, а не пересказу заголовков.",
        "Сабақ ережелерді үйретуі керек, тақырыптарды қайталау емес.",
        "The lesson must teach the rules rather than retelling headings.",
    )

    for value in cases:
        assert _narrative_fact_metadata(value) == {
            "confidence": 0.0,
            "uncertainty": "source_authoring_metadata",
        }


def test_explicit_multilingual_synthetic_covers_are_not_assessment_facts() -> None:
    cases = (
        "Синтетический материал для видеоинструкции Камили. Все правила и названия вымышлены. Персональных данных и сведений клиентов нет. Конец учебного материала.",
        "Бейненұсқаулыққа арналған синтетикалық материал. Барлық ережелер мен атаулар ойдан шығарылған. Жеке деректер және клиенттер туралы мәліметтер жоқ. Материалдың соңы.",
        "Synthetic material for a video instruction. All rules and names are fictional. There is no personal data or client information. End of the training material.",
    )

    for value in cases:
        parts = _split_narrative_chunk(value)
        assert len(parts) == 1
        assert _narrative_fact_metadata(parts[0]) == {
            "confidence": 0.0,
            "uncertainty": "source_authoring_metadata",
        }


def test_mixed_cover_keeps_following_operational_clause() -> None:
    values = _split_narrative_chunk(
        "Синтетический материал для видеоинструкции Камили. "
        "Персональных данных и сведений клиентов нет. "
        "Перед выдачей проверьте комплектность оборудования."
    )

    assert values == [
        "Синтетический материал для видеоинструкции Камили. Персональных данных и сведений клиентов нет.",
        "Перед выдачей проверьте комплектность оборудования.",
    ]
    assert _narrative_fact_metadata(values[0])["uncertainty"] == "source_authoring_metadata"
    assert _narrative_fact_metadata(values[1]) == {"confidence": 1.0, "uncertainty": ""}


def test_kazakh_uppercase_action_after_cover_remains_operational() -> None:
    values = _split_narrative_chunk(
        "Бейненұсқаулыққа арналған синтетикалық материал. "
        "Қауіп байқалса, жұмысты тоқтатыңыз."
    )

    assert values == [
        "Бейненұсқаулыққа арналған синтетикалық материал.",
        "Қауіп байқалса, жұмысты тоқтатыңыз.",
    ]
    assert _narrative_fact_metadata(values[0])["uncertainty"] == "source_authoring_metadata"
    assert _narrative_fact_metadata(values[1]) == {"confidence": 1.0, "uncertainty": ""}


def test_operational_privacy_or_synthetic_wording_is_not_blanket_filtered() -> None:
    values = (
        "Если материал синтетический, не фотографируйте документы и не передавайте персональные данные.",
        "В синтетическом журнале не указывайте персональные данные клиентов.",
        "If the training material is synthetic, do not record personal data in the log.",
    )

    for value in values:
        assert _narrative_fact_metadata(value) == {"confidence": 1.0, "uncertainty": ""}
