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


@pytest.mark.parametrize("question", [
    "Compare only the deadline for approving the complete checked atlas set. Give the deadline in each source and the exact event that starts it. Do the two sources agree? Do not confuse this with either record-retention period.",
    "Who approves? Do not discuss the retention period.",
    "Кто утверждает? Не обсуждай сроки хранения записей.",
    "Кто утверждает, а не сроки хранения записей?",
    "Кім бекітеді? Жазбалардың сақтау мерзімін талқыламаңыз.",
    "Who approves, not the retention period?",
])
def test_excluded_retention_is_not_a_mandatory_answer_part(question):
    assert "record_retention" not in answers.required_dimensions(question)


@pytest.mark.parametrize("question", [
    "Do not discuss approval deadlines, but state the record retention period.",
    "Who must not approve, and how long are records retained?",
    "Do not forget to state the retention period. Who approves?",
    "Не обсуждай срок утверждения, но укажи сроки хранения записей.",
    "Какие сроки хранения записей не установлены?",
    "Кім бекітеді? Бірақ жазбалардың сақтау мерзімін көрсетіңіз.",
    "Who approves? Ignore approval timing, but state the retention period.",
    "State the retention period; do not discuss who appoints the deputy.",
    "Who may ignore the record-retention period?",
    "Which records should we exclude from the retention period?",
    "Кто не обсуждает сроки хранения записей?",
    "Ignore approval timing and state the record retention period.",
    "Не обсуждай срок утверждения и укажи сроки хранения записей.",
])
def test_exclusions_do_not_erase_positive_or_negative_fact_questions(question):
    assert "record_retention" in answers.required_dimensions(question)


def test_deadline_conflict_not_rejected_for_explicitly_excluded_retention():
    question = "Compare approval deadlines. Do not confuse this with either record-retention period."
    windows = [{**EXCERPTS[0], "text": "Approval takes two working days after receipt registration."},
               {**EXCERPTS[1], "text": "Approval takes five working days after receipt registration."}]
    item = part("duration", "RU says two working days, KK five; no precedence is established.", (1, 2), "conflict")
    item["conflict_evidence"] = {"question_quote": "approval deadlines", "left": {"handle": 1, "quote": windows[0]["text"]},
                                "right": {"handle": 2, "quote": windows[1]["text"]}}
    result = answers.parse_answer(json.dumps({"requested_dimensions": ["duration"], "parts": [item]}), windows, question=question)
    assert result.status == "conflict"


def test_excluded_actor_is_not_forced_into_a_retention_answer():
    question = "How long are records retained? Do not discuss who appoints a deputy."
    assert answers.required_dimensions(question) == ["record_retention"]


def test_actual_conflict_stays_one_cross_source_dimension():
    windows = [{**EXCERPTS[0], "text": "Approval takes three working days after complete receipt."},
               {**EXCERPTS[1], "text": "Approval takes five working days after complete receipt."}]
    conflict = part("duration", "RU says three working days, KK five. No dates or precedence resolve the disagreement.", (1, 2), "conflict")
    conflict["conflict_evidence"] = {"question_quote": "approval deadline", "left": {"handle": 1, "quote": windows[0]["text"]},
                                     "right": {"handle": 2, "quote": windows[1]["text"]}}
    value = json.dumps({"requested_dimensions": ["duration"], "parts": [
        conflict]})
    result = answers.parse_answer(value, windows, question="What is the approval deadline?")
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


def test_conflict_without_question_bound_opposing_positions_is_rejected():
    # Captured DEV58 pattern: accurate coordinator/deputy/retention prose was
    # marked conflict for a conditional appointing difference not requested.
    # This protocol gate rejects an unsubstantiated conflict, not its semantics.
    value = complete(parts=[part("actor", "Coordinator approves in both sources; deputy appointers differ.", (1, 2), "conflict"),
                            part("record_retention", "Raw 30; signed 60.", (1, 2))])
    with pytest.raises(ValueError):
        answers.parse_answer(value, EXCERPTS, question=QUESTION)


@pytest.mark.parametrize("change", ["unasked", "invented_quote", "uncited", "identical", "wrong_status"])
def test_conflict_binding_rejects_invalid_private_proof(change):
    item = part("actor", "Opposing rules.", (1, 2), "conflict")
    item["conflict_evidence"] = {"question_quote": "кто утверждает возврат", "left": {"handle": 1, "quote": EXCERPTS[0]["text"]},
                                 "right": {"handle": 2, "quote": EXCERPTS[1]["text"]}}
    if change == "unasked":
        item["conflict_evidence"]["question_quote"] = "who appoints the deputy"
    elif change == "invented_quote":
        item["conflict_evidence"]["right"]["quote"] = "Invented opposing authority."
    elif change == "uncited":
        item["citations"] = [{"handle": 1}]
    elif change == "identical":
        item["conflict_evidence"]["right"] = item["conflict_evidence"]["left"]
    else:
        item["status"] = "supported"
    value = complete(parts=[item, part("record_retention", "Raw 30; signed 60.", (1, 2))])
    with pytest.raises(ValueError):
        answers.parse_answer(value, EXCERPTS, question=QUESTION)


def test_private_proof_does_not_pretend_to_prove_semantic_incompatibility():
    # Exact grounding alone cannot decide whether role names are incompatible.
    # This remains an explicit real-model acceptance responsibility.
    item = part("actor", "Different appointers.", (1, 2), "conflict")
    item["conflict_evidence"] = {"question_quote": "кто утверждает возврат", "left": {"handle": 1, "quote": EXCERPTS[0]["text"]},
                                 "right": {"handle": 2, "quote": EXCERPTS[1]["text"]}}
    response = answers.parse_answer(complete(parts=[item, part("record_retention", "Raw 30; signed 60.", (1, 2))]), EXCERPTS, question=QUESTION)
    assert response.status == "conflict"  # Never relabel unreviewed semantics.
    assert "conflict_evidence" not in response.model_dump()
