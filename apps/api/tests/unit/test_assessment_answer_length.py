from dataclasses import replace

from app.modules.ai.evidence_engine.models import QuestionDraft
from app.modules.ai.evidence_engine.quality import answer_length_repair_targets


def question(identity: str, *, lesson: str = "l1", correct: str = "one two three four") -> QuestionDraft:
    return QuestionDraft(
        identity, lesson, "single_choice", identity, (correct, "wrong one", "wrong two"),
        correct, "Source-owned explanation", identity,
    )


def test_two_longest_correct_answers_need_one_deterministic_repair() -> None:
    questions = [question("q2"), question("q1")]
    assert answer_length_repair_targets(questions) == ("q1",)
    assert answer_length_repair_targets(list(reversed(questions))) == ("q1",)


def test_exact_eighty_percent_signal_uses_quiz_denominator() -> None:
    questions = [question(str(index)) for index in range(5)]
    questions[-1] = replace(questions[-1], options=(questions[-1].correct_answer, "a b c d e", "wrong"))
    assert len(answer_length_repair_targets(questions)) == 1
    questions[-2] = replace(questions[-2], options=(questions[-2].correct_answer, "a b c d e", "wrong"))
    assert answer_length_repair_targets(questions) == ()


def test_tied_longest_and_natural_numeric_options_are_not_repair_targets() -> None:
    tied = [replace(question(str(index)), options=("one two three four", "a b c d", "wrong"))
            for index in range(2)]
    assert answer_length_repair_targets(tied) == ()
    numeric = [replace(question(str(index), correct="30"), options=("30", "10", "60"))
               for index in range(2)]
    assert answer_length_repair_targets(numeric) == ()


def test_separate_lessons_and_single_question_do_not_form_a_quiz() -> None:
    assert answer_length_repair_targets([question("q1"), question("q2", lesson="l2")]) == ()
    assert answer_length_repair_targets([question("q1")]) == ()


def test_current_batch_targets_do_not_reject_previously_accepted_question() -> None:
    questions = [question("q1"), question("q2")]
    assert answer_length_repair_targets(questions, repairable_ids={"q2"}) == ("q2",)


def test_invalid_answer_key_is_not_a_length_signal() -> None:
    invalid = replace(question("bad"), correct_answer="absent")
    assert answer_length_repair_targets([question("q1"), invalid]) == ()
