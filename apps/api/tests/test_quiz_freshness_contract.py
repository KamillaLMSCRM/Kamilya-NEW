from pathlib import Path

from app.modules.quizzes.schemas import QuizResponse

ROOT = Path(__file__).resolve().parents[1]


def test_quiz_response_exposes_review_state_to_methodologist_ui():
    assert QuizResponse.model_fields["review_status"].default == "approved"


def test_manual_lesson_edits_mark_quizzes_for_review_without_deleting_evidence():
    source = (ROOT / "app/modules/lessons/service.py").read_text(encoding="utf-8")
    assert '.values(review_status="needs_review", reviewed_by=None, reviewed_at=None)' in source
    assert "await db.delete(quiz)" not in source


def test_learner_visible_content_block_mutations_mark_related_quizzes_for_review():
    source = (ROOT / "app/modules/lessons/service.py").read_text(encoding="utf-8")
    assert source.count("await _mark_lesson_quizzes_needs_review") >= 5


def test_stale_quizzes_are_blocked_from_publication_and_learner_delivery():
    course_router = (ROOT / "app/modules/courses/router.py").read_text(encoding="utf-8")
    quiz_router = (ROOT / "app/modules/quizzes/router.py").read_text(encoding="utf-8")
    assert '"code": "quiz_review_required"' in course_router
    assert 'Quiz.review_status == "approved"' in quiz_router
    assert "Quiz is awaiting methodologist review" in quiz_router


def test_full_ai_pipeline_persists_every_generated_quiz_for_explicit_review():
    pipeline = (ROOT / "app/modules/ai/pipeline.py").read_text(encoding="utf-8")
    assert 'review_status="needs_review"' in pipeline
    assert "reviewed_by=None" in pipeline
    assert "reviewed_at=None" in pipeline


def test_quiz_review_migration_is_additive_and_reserved_after_0094():
    migration = (ROOT / "alembic/versions/0095_quiz_review_state.py").read_text(encoding="utf-8")
    assert 'revision = "0095"' in migration
    assert 'down_revision = "0094"' in migration
    assert "ADD COLUMN review_status" in migration
