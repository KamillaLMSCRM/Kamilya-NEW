from app.modules.ai.evidence_engine.assessment_coverage import assess_topic_coverage
from app.modules.ai.evidence_engine.models import QuestionDraft, SourceFact


def fact(fid, subject="Collection A", doc="d", section="collections"):
    return SourceFact(fid, subject, "material", "Oak",
                      f"doc_id={doc};source_revision=r1;section={section};part={fid}")


def question(fid, lesson="lesson-other"):
    return QuestionDraft("q-" + fid, lesson, "single_choice", "Which material?",
                         ("Oak", "Pine", "Beech"), "Oak", "Oak", fid,
                         evidence_fact_ids=(fid,), semantic_reviewed=True)


def block(fid, outcome="rejected", candidates=1):
    return {"block_id": fid, "lesson_id": "l-" + fid, "fact_ids": [fid],
            "outcome": outcome, "candidates": candidates, "accepted": 0}


def test_primary_topic_cannot_disappear_after_filtering():
    facts = {"a": fact("a"), "b": fact("b", "Collection B")}
    result = assess_topic_coverage(facts, [question("a")], [block("a"), block("b")])
    assert result["requires_review"] is True
    assert result["missing_fact_ids"] == ["b"]


def test_same_topic_tested_in_another_lesson_is_not_a_gap():
    facts = {"a": fact("a"), "b": fact("b")}
    result = assess_topic_coverage(facts, [question("a")], [block("a"), block("b")])
    assert result["requires_review"] is False


def test_successfully_empty_introduction_does_not_force_a_question():
    facts = {"intro": fact("intro", "Introduction")}
    result = assess_topic_coverage(facts, [], [block("intro", "no_assessable_questions", 0)])
    assert result["requires_review"] is False
    assert result["required_topic_count"] == 0


def test_failed_author_is_not_a_successfully_empty_introduction():
    facts = {"a": fact("a")}
    result = assess_topic_coverage(facts, [], [block("a", "unavailable", 0)])
    assert result["requires_review"] is True


def test_bounded_quality_rejection_is_an_audited_omission_not_a_coverage_gap():
    facts = {"a": fact("a")}

    result = assess_topic_coverage(
        facts,
        [],
        [block("a", "quality_omitted", 1)],
    )

    assert result["requires_review"] is False
    assert result["audit_incomplete"] is False
    assert result["required_topic_count"] == 0


def test_another_document_cannot_supply_coverage_for_same_named_topic():
    facts = {"a": fact("a"), "b": fact("b", doc="another")}
    result = assess_topic_coverage(facts, [question("a")], [block("a"), block("b")])
    assert result["requires_review"] is True


def test_incidental_supporting_citation_does_not_cover_another_topic():
    from dataclasses import replace
    facts = {"a": fact("a"), "b": fact("b", "Collection B")}
    q = replace(question("a"), evidence_fact_ids=("a", "b"))
    result = assess_topic_coverage(facts, [q], [block("a"), block("b")])
    assert result["missing_fact_ids"] == ["b"]


def test_unknown_fact_or_missing_block_audit_is_not_verified_coverage():
    assert assess_topic_coverage({}, [], [block("unknown")])["requires_review"] is True
    assert assess_topic_coverage({"a": fact("a")}, [question("a")], [])["requires_review"] is True


def test_repeated_long_source_answer_covers_each_occurrence_in_same_document():
    answer = "В момент погашения Клиентом задолженности"
    facts = {
        "a": SourceFact(
            "a", "Начисление", "момент",
            f"Начисление вознаграждения осуществляется {answer.lower()}.",
            "doc_id=d;source_revision=r1;section=payments;part=1",
        ),
        "b": SourceFact(
            "b", "Обязанности", "момент",
            f"По залоговому билету начисление производится {answer.lower()}.",
            "doc_id=d;source_revision=r1;section=rights;part=1",
        ),
    }
    q = QuestionDraft(
        "q-a", "lesson-a", "single_choice", "Когда производится начисление?",
        (answer, "При выдаче", "Ежемесячно"), answer, answer, "a",
        evidence_fact_ids=("a",), semantic_reviewed=True,
    )

    result = assess_topic_coverage(facts, [q], [block("a"), block("b")])

    assert result["requires_review"] is False
    assert result["required_topic_count"] == 2
    assert result["covered_topic_count"] == 2
    assert result["missing_fact_ids"] == []


def test_short_repeated_answer_does_not_supply_cross_topic_coverage():
    facts = {
        "a": SourceFact(
            "a", "Обращения", "срок", "Ответ предоставляется в течение 15 дней.",
            "doc_id=d;source_revision=r1;section=appeals;part=1",
        ),
        "b": SourceFact(
            "b", "Хранение", "срок", "Документ хранится 15 дней.",
            "doc_id=d;source_revision=r1;section=storage;part=1",
        ),
    }
    q = QuestionDraft(
        "q-a", "lesson-a", "single_choice", "Каков срок ответа?",
        ("15 дней", "10 дней", "30 дней"), "15 дней", "15 дней", "a",
        evidence_fact_ids=("a",), semantic_reviewed=True,
    )

    result = assess_topic_coverage(facts, [q], [block("a"), block("b")])

    assert result["requires_review"] is True
    assert result["covered_topic_count"] == 1
    assert result["missing_fact_ids"] == ["b"]


def test_repeated_long_answer_in_another_document_does_not_supply_coverage():
    answer = "В момент погашения Клиентом задолженности"
    facts = {
        "a": SourceFact(
            "a", "Начисление", "момент", answer,
            "doc_id=d1;source_revision=r1;section=payments;part=1",
        ),
        "b": SourceFact(
            "b", "Начисление", "момент", answer,
            "doc_id=d2;source_revision=r1;section=payments;part=1",
        ),
    }
    q = QuestionDraft(
        "q-a", "lesson-a", "single_choice", "Когда производится начисление?",
        (answer, "При выдаче", "Ежемесячно"), answer, answer, "a",
        evidence_fact_ids=("a",), semantic_reviewed=True,
    )

    result = assess_topic_coverage(facts, [q], [block("a"), block("b")])

    assert result["requires_review"] is True
    assert result["covered_topic_count"] == 1
    assert result["missing_fact_ids"] == ["b"]
