"""Independent multipart completeness oracles; not semantic-entailment proof."""
import hashlib
import json
from uuid import UUID

import pytest

from app.modules.methodologist_workbench import document_answers as answers
from app.modules.methodologist_workbench.document_schemas import DocumentSource

RU = DocumentSource(document_id=UUID(int=31), title="RU calibration", version=1,
                    content_sha256="a" * 64, index_revision=1)
KK = DocumentSource(document_id=UUID(int=32), title="KK calibration", version=1,
                    content_sha256="b" * 64, index_revision=1)
EXCERPTS = [
    {"handle": 1, "source": RU, "chunk_id": hashlib.sha256(b"ru").hexdigest(),
     "text": "Raw journals: 30 calendar days after calibration. Quality coordinator approves return; workshop head appoints a written deputy."},
    {"handle": 2, "source": KK, "chunk_id": hashlib.sha256(b"kk").hexdigest(),
     "text": "Signed protocol: 60 days after final approval. Quality coordinator approves return; laboratory head appoints a written deputy."},
]
QUESTION = "Сопоставь правила RU и KK: кто утверждает возврат, и какие сроки хранения относятся к каким записям?"


def part(dimension, answer, handles=(1,), status="supported"):
    return {"dimension": dimension, "answer": answer,
            "citations": [{"handle": handle} for handle in handles], "status": status}


def complete(**updates):
    return json.dumps({"requested_dimensions": ["actor", "record_retention"], "parts": [
        part("actor", "Quality coordinator approves; RU workshop head and KK laboratory head appoint their respective written deputies.", (1, 2)),
        part("record_retention", "RU raw journals: 30 calendar days after calibration. KK signed protocol: 60 days after final approval.", (1, 2)),
    ], **updates})


def test_legacy_flat_answer_cannot_silently_omit_a_declared_requirement():
    # Reconstructed legacy envelope from the captured incomplete answer pattern:
    # record_retention is declared and its evidence is cited, but the answer only
    # gives actors. Citation membership must not be counted as answer coverage.
    captured_pattern = json.dumps({"requested_dimensions": ["actor", "permission", "record_retention"],
        "answer": "Quality coordinator approves. A written deputy is appointed by the workshop head in RU and laboratory head in KK.",
        "citations": [{"handle": 1}, {"handle": 2}], "status": "supported"})
    with pytest.raises(ValueError):
        answers.parse_answer(captured_pattern, EXCERPTS)


def test_all_parts_are_assembled_without_a_model_authored_summary():
    result = answers.parse_answer(complete(), EXCERPTS, question=QUESTION)
    assert "30 calendar days after calibration" in result.answer
    assert "60 days after final approval" in result.answer
    assert "workshop head" in result.answer and "laboratory head" in result.answer
    assert result.status == "supported"
    assert [c.number for c in result.citations] == [1, 2]
    assert [c.quote for c in result.citations] == [e["text"] for e in EXCERPTS]
    assert set(result.model_dump()) == {"state", "status", "answer", "citations"}


@pytest.mark.parametrize("parts", [[], [part("actor", "Coordinator approves.")],
    [part("actor", "Coordinator approves."), part("actor", "Coordinator approves again.")],
    [part("actor", "Coordinator approves."), part("duration", "Three days.")]])
def test_missing_duplicate_or_wrong_part_is_rejected(parts):
    with pytest.raises(ValueError):
        answers.parse_answer(complete(parts=parts), EXCERPTS, question=QUESTION)


@pytest.mark.parametrize("question", [QUESTION,
    "Кто утверждает возврат и сколько хранятся записи?",
    "Қайтаруды кім бекітеді және жазбалардың сақтау мерзімі қандай?",
    "Who approves return and how long are records retained?"])
def test_explicit_actor_and_retention_cannot_be_omitted_from_declaration(question):
    only_actor = json.dumps({"requested_dimensions": ["actor"], "parts": [part("actor", "Coordinator approves.")]})
    with pytest.raises(ValueError):
        answers.parse_answer(only_actor, EXCERPTS, question=question)


def test_retention_question_does_not_request_approval_duration():
    data = json.loads(answers.messages(QUESTION, "ru", [], EXCERPTS, sources=(RU, KK))[1]["content"])
    assert set(data["required_dimensions"]) == {"actor", "record_retention"}


@pytest.mark.parametrize("question", [
    "How long should I keep the atlas room closed after indexing?",
    "Как долго хранить оборудование в закрытой комнате?",
    "Бөлмені қанша уақыт жабық сақтауға болады?",
    "Keep records as context: how long does approval take?",
])
def test_action_or_physical_storage_is_not_record_retention(question):
    assert "record_retention" not in answers.required_dimensions(question)


def test_record_category_before_elliptical_storage_quantity():
    question = "Какие записи хранятся, сколько и с какого события?"
    assert answers.required_dimensions(question) == ["record_retention"]


def test_actual_conflict_stays_one_cross_source_dimension():
    value = json.dumps({"requested_dimensions": ["duration"], "parts": [
        part("duration", "RU says three working days, KK five. No dates or precedence resolve the disagreement.", (1, 2), "conflict")]})
    result = answers.parse_answer(value, EXCERPTS)
    assert result.status == "conflict" and "three" in result.answer and "five" in result.answer


def test_one_missing_part_is_explicit_not_found_not_silent_success():
    result = answers.parse_answer(complete(parts=[part("actor", "Coordinator approves."),
        part("record_retention", "No retention period was located in the supplied excerpts.", (), "not_found")]), EXCERPTS)
    assert result.status == "not_found" and "No retention period" in result.answer


def test_supported_part_without_own_evidence_cannot_borrow_another_parts_citations():
    value = complete(parts=[part("actor", "Coordinator approves."), part("record_retention", "Thirty days.", ())])
    with pytest.raises(ValueError):
        answers.parse_answer(value, EXCERPTS)


def test_merged_answer_limit_applies_to_all_parts_not_individually():
    value = complete(parts=[part("actor", "a" * 4100), part("record_retention", "b" * 4100)])
    with pytest.raises(ValueError):
        answers.parse_answer(value, EXCERPTS)
