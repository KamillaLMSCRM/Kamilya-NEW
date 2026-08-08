from pathlib import Path


def test_single_answer_question_migration_is_linear_and_semantic() -> None:
    migration = Path(__file__).parents[1] / "alembic" / "versions" / "0092_canonicalize_single_answer_questions.py"
    source = migration.read_text(encoding="utf-8")

    assert 'revision = "0092"' in source
    assert 'down_revision = "0091"' in source
    assert "question.type = 'multiple_choice'" in source
    assert "choice.is_correct IS TRUE" in source
    assert "SET type = 'MCQ'" in source
