"""V1 multi-document generation contract: request validation invariants.

These tests pin the request-level rules added for the multi-document
vertical slice. They are pure schema tests (no DB) and complement the
integration coverage in tests/integration/test_multi_document_generation_api.py.
"""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ai.schemas import AIGenerateRequest


def test_duplicates_are_deduplicated_preserving_first_occurrence_order() -> None:
    first, second = uuid4(), uuid4()
    request = AIGenerateRequest(documents=[first, second, first, second])
    assert request.documents == [first, second]


def test_single_document_still_accepted_for_backward_compatibility() -> None:
    document_id = uuid4()
    request = AIGenerateRequest(documents=[document_id])
    assert request.documents == [document_id]


def test_two_to_five_unique_documents_accepted() -> None:
    documents = [uuid4() for _ in range(5)]
    request = AIGenerateRequest(documents=documents)
    assert request.documents == documents


def test_schema_tolerates_more_than_five_for_endpoint_cap() -> None:
    """The 5-source cap is endpoint-owned with a stable error code; the
    schema only deduplicates so the endpoint sees unique ordered IDs."""
    documents = [uuid4() for _ in range(7)]
    request = AIGenerateRequest(documents=documents)
    assert len(request.documents) == 7


def test_duplicates_count_after_dedup_for_limit() -> None:
    unique_pair = [uuid4(), uuid4()]
    duplicated = unique_pair * 3  # 6 entries, only 2 unique
    request = AIGenerateRequest(documents=duplicated)
    assert request.documents == unique_pair


def test_reuse_reason_and_course_id_exclusivity_preserved() -> None:
    with pytest.raises(ValidationError):
        AIGenerateRequest(
            documents=[uuid4()],
            course_id=uuid4(),
            reuse_reason="updated_revision",
        )


def test_intentional_combination_goal_rule_preserved() -> None:
    with pytest.raises(ValidationError):
        AIGenerateRequest(
            documents=[uuid4(), uuid4()],
            source_strategy="intentional_combination",
            combination_goal="кратко",
        )


def test_aggregate_budget_setting_default_is_positive() -> None:
    from app.core.config import get_settings

    assert get_settings().AI_MULTI_DOC_MAX_TOTAL_CHUNKS > 0


def test_document_chunk_totals_filters_and_casts() -> None:
    import asyncio

    from app.modules.ai.source_analysis import document_chunk_totals

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class _DB:
        def __init__(self, rows):
            self._rows = rows

        async def execute(self, statement):
            return _Result(self._rows)

    doc_a, doc_b, doc_c = uuid4(), uuid4(), uuid4()
    rows = [(doc_a, 10), (doc_b, None), (doc_c, "7")]
    db = _DB(rows)

    totals = asyncio.run(document_chunk_totals(db, uuid4(), [doc_a, doc_b, doc_c]))
    # None totals count as zero chunks; non-active/missing docs are omitted.
    assert totals == {doc_a: 10, doc_b: 0, doc_c: 7}


def test_dominant_language_detection_is_deterministic() -> None:
    from app.modules.ai.source_analysis import dominant_language

    assert dominant_language("Правила безопасности") == "ru"
    assert dominant_language("Safety rules") == "latin"
    assert dominant_language("Ережелер қауіпсіздігі") == "kk"
    assert dominant_language(",,, --- 123") is None
    # Short ambiguous sample without Kazakh markers: conservative but
    # deterministic — Cyrillic-dominant maps to "ru".
    assert dominant_language("Ереже 2026 жыл") == "ru"
