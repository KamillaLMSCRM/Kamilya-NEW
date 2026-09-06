from app.modules.courses.blueprint_service import get_catalog


def test_russian_general_blueprint_keeps_localized_limitations_in_public_contract():
    item = next(
        item for item in get_catalog("ru", include_financial=False) if item.id == "kz-information-security-awareness"
    )
    text = " ".join(item.limitations)
    assert "LMS completion" not in text
    for phrase in (
        "требований законодательства",
        "инструктаж на рабочем месте",
        "практические занятия",
        "официальные записи",
        "аттестованного провайдера",
        "своими правилами и каналом инцидентов",
    ):
        assert phrase in text
