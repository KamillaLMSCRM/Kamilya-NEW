"""Opt-in decision instructions preserve legacy prompt identity and source boundaries."""
import hashlib

from app.modules.ai.v3.prompts import (
    LESSON_COGEN_DECISION_SUFFIX,
    LESSON_COGEN_SYSTEM_PROMPT,
    RULE_EXTRACTION_DECISION_SUFFIX,
    RULE_EXTRACTION_SYSTEM_PROMPT,
    SOURCE_QUOTATION_VIEW_SUFFIX,
)


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_legacy_request_prompts_remain_byte_identical():
    assert sha(RULE_EXTRACTION_SYSTEM_PROMPT) == "789c012965af419ae977ffe3983d4e95f6d33e4b1972f61a82230182132a7127"
    assert sha(LESSON_COGEN_SYSTEM_PROMPT) == "7816c9c945a2045a8663ee6194bb595b78220a18aa01cff197d5f54051e317fe"


def test_fresh_opt_in_appends_decision_boundaries_to_actual_prompts():
    extraction = RULE_EXTRACTION_SYSTEM_PROMPT + RULE_EXTRACTION_DECISION_SUFFIX
    author = LESSON_COGEN_SYSTEM_PROMPT + SOURCE_QUOTATION_VIEW_SUFFIX + LESSON_COGEN_DECISION_SUFFIX
    assert extraction.startswith(RULE_EXTRACTION_SYSTEM_PROMPT) and extraction.endswith(RULE_EXTRACTION_DECISION_SUFFIX)
    assert author.startswith(LESSON_COGEN_SYSTEM_PROMPT) and author.endswith(LESSON_COGEN_DECISION_SUFFIX)
    assert SOURCE_QUOTATION_VIEW_SUFFIX in author
    # The source map and owner interpretation retain their established authority boundaries.
    assert "не самостоятельное подтверждение нормы" in extraction
    assert "не делает остальные пересказы источником" in extraction
    assert "Исходная цитата должна оставаться точной" in extraction


def test_extraction_contract_distinguishes_alternatives_and_unknown_references():
    text = RULE_EXTRACTION_DECISION_SUFFIX
    # A list of individually plausible grounds must not become an accidental AND.
    assert "совместно необходимые обстоятельства, альтернативы, отрицания" in text
    assert "передай их как альтернативы в одном условии либо явно обозначь связь «или»" in text
    assert "не выбирая трактовку" in text
    # An outside cross-reference does not independently supply new actors or deadlines.
    assert "Не подставляй по предположению" in text
    assert "сроки, исполнителей, действия или последствия" in text


def test_author_contract_targets_cueing_unsupported_deadline_and_option_comparability():
    text = LESSON_COGEN_DECISION_SUFFIX
    # Category may be context for a subsequent action, not the classification being tested.
    assert "не сообщай заранее классификацию или решение" in text
    assert "когда вопрос проверяет другое последующее решение" in text
    # A same-day grouping condition alone does not prove a next-day timing violation.
    assert "срок указывай только при наличии самостоятельного основания в источнике" in text
    assert "не объявляй неверным вариант только потому, что источник о нём молчит" in text
    assert "Все четыре варианта должны отвечать на один и тот же вопрос" in text
    assert "выбор категории сравнивай с выбором категории" in text
    assert "без искусственного заполнения" in text
