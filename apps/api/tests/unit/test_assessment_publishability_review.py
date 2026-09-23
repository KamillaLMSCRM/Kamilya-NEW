from app.modules.ai.evidence_engine.application import _finalize_assessment_publishability
from app.modules.ai.evidence_engine.provider_models import PublishabilityReport


def _base_report() -> PublishabilityReport:
    return PublishabilityReport(
        publishable=True, reasons=(), fact_coverage_ratio=1.0,
        generic_question_count=0, duplicate_question_count=0,
        ocr_artifact_count=0, invalid_title_count=0, overlong_lesson_count=0,
    )


def test_assessable_block_without_accepted_question_requires_review() -> None:
    report = _finalize_assessment_publishability(
        _base_report(), question_count=3,
        audit={"coverage": {"requires_review": False}, "block_outcomes": [
            {"candidates": 3, "accepted": 3},
            {"candidates": 3, "accepted": 0, "outcome": "quality_omitted"},
        ]},
    )
    assert not report.publishable
    assert report.reasons == ("assessment_assessable_block_unassessed",)


def test_source_without_question_candidates_does_not_force_question_quota() -> None:
    report = _finalize_assessment_publishability(
        _base_report(), question_count=1,
        audit={"coverage": {"requires_review": False}, "block_outcomes": [
            {"candidates": 1, "accepted": 1},
            {"candidates": 0, "accepted": 0, "outcome": "unassessable"},
        ]},
    )
    assert report.publishable
    assert report.reasons == ()


def test_missing_assessment_audit_is_review_required_not_a_crash() -> None:
    report = _finalize_assessment_publishability(
        _base_report(), question_count=2,
        audit={"coverage": None, "block_outcomes": None},
    )
    assert not report.publishable
    assert report.reasons == ("assessment_audit_incomplete",)
