from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.modules.candidate_assessments.models import (
    AssessmentCandidate,
    CandidateAssessmentAttempt,
    CandidateAssessmentCampaign,
)
from app.modules.candidate_assessments.schemas import CampaignCreate, CandidateCreate
from app.modules.candidate_assessments.service import (
    assessment_from_release,
    create_campaign,
    grade,
    public_assessment,
    results_csv,
    status_after_submission,
    submit,
)


def _release() -> dict:
    return {
        "course": {"title": "Finance"},
        "modules": [
            {
                "lessons": [
                    {
                        "quizzes": [
                            {
                                "id": "quiz-1",
                                "title": "Test",
                                "pass_score": 80,
                                "review_status": "approved",
                                "questions": [
                                    {
                                        "id": "q1",
                                        "text": "2+2?",
                                        "points": 2,
                                        "choices": [
                                            {"id": "c1", "text": "4", "is_correct": True},
                                            {"id": "c2", "text": "5", "is_correct": False},
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }


def test_public_snapshot_never_discloses_correctness_and_grades_server_side() -> None:
    snapshot = assessment_from_release(_release())
    public = public_assessment(snapshot)
    assert "is_correct" not in str(public)
    result = grade(snapshot, [{"question_id": "q1", "selected_choice_ids": ["c1"]}])
    assert result["score_percent"] == 100
    assert result["passed"] is True
    assert len(result["answers_sha256"]) == 64


def test_grading_requires_exactly_one_complete_question_set() -> None:
    snapshot = assessment_from_release(_release())
    with pytest.raises(ValueError, match="every assessment question"):
        grade(snapshot, [])


def test_candidate_contact_is_optional_for_manual_link_delivery() -> None:
    candidate = CandidateCreate(first_name="Имя", last_name="Фамилия")
    assert candidate.email is None
    assert candidate.phone is None


def test_single_and_multiple_choice_are_frozen_and_graded_without_key_leakage() -> None:
    release = _release()
    questions = release["modules"][0]["lessons"][0]["quizzes"][0]["questions"]
    questions[0]["type"] = "single_choice"
    questions.append(
        {
            "id": "q2",
            "text": "Select both",
            "type": "multiple_choice",
            "points": 2,
            "choices": [
                {"id": "c3", "text": "A", "is_correct": True},
                {"id": "c4", "text": "B", "is_correct": True},
                {"id": "c5", "text": "C", "is_correct": False},
            ],
        }
    )
    snapshot = assessment_from_release(release)
    frozen = snapshot["quizzes"][0]["questions"]
    assert [question["type"] for question in frozen] == ["single_choice", "multiple_choice"]
    assert "is_correct" not in str(public_assessment(snapshot))
    result = grade(
        snapshot,
        [
            {"question_id": "q1", "selected_choice_ids": ["c1"]},
            {"question_id": "q2", "selected_choice_ids": ["c3", "c4"]},
        ],
    )
    assert result["score_percent"] == 100


def test_0099_isolated_rls_and_runtime_grants_contract() -> None:
    source = Path("alembic/versions/0099_candidate_assessments.py").read_text(encoding="utf-8")
    assert 'down_revision = "0098"' in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "NULLIF(current_setting('app.tenant_id', true), '')::uuid" in source
    assert "FROM PUBLIC, lms_app" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in source
    assert "SECURITY DEFINER" in source
    assert "0099 downgrade refused" in source
    assert "candidate PII or attempt evidence exists" in source
    assert "validate_candidate_campaign_ownership" in source
    assert "validate_assessment_candidate_ownership" in source
    assert "validate_candidate_credential_ownership" in source
    assert "validate_candidate_attempt_ownership" in source
    assert "candidate campaign tenant/release/creator mismatch" in source
    assert "candidate credential tenant/candidate/campaign mismatch" in source
    assert "ur.role = 'methodologist'" in source
    assert (
        "users.id"
        not in source[
            source.index('op.create_table(\n        "assessment_candidates"') : source.index(
                'op.create_table(\n        "candidate_access_credentials"'
            )
        ]
    )


def test_0100_repairs_already_migrated_polymorphic_trigger() -> None:
    source = Path("alembic/versions/0100_candidate_ownership_trigger_hotfix.py").read_text(encoding="utf-8")
    assert 'down_revision = "0099"' in source
    assert "DROP FUNCTION IF EXISTS validate_candidate_assessment_ownership()" in source
    assert "validate_candidate_campaign_ownership" in source
    assert "validate_candidate_attempt_ownership" in source


def test_0101_repairs_already_migrated_evidence_trigger() -> None:
    source = Path("alembic/versions/0101_candidate_evidence_trigger_hotfix.py").read_text(encoding="utf-8")
    assert 'down_revision = "0100"' in source
    assert "DROP FUNCTION IF EXISTS protect_candidate_assessment_evidence()" in source
    assert "protect_candidate_campaign_snapshot" in source
    assert "protect_candidate_attempt_evidence" in source


@pytest.mark.asyncio
async def test_revoked_credential_rejects_old_candidate_bearer_before_attempt_read() -> None:
    candidate_id, tenant_id, campaign_id, attempt_id, credential_id = (uuid4() for _ in range(5))
    db = AsyncMock()
    db.scalar.return_value = None
    claims = {
        "sub": str(candidate_id),
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "attempt_id": str(attempt_id),
        "credential_id": str(credential_id),
    }
    with pytest.raises(ValueError, match="revoked"):
        await submit(db, claims, attempt_id, [])
    assert db.scalar.await_count == 3


@pytest.mark.asyncio
async def test_cross_tenant_release_is_not_disclosed_when_creating_campaign() -> None:
    db = AsyncMock()
    db.scalar.return_value = None
    tenant_id = uuid4()
    payload = CampaignCreate(
        content_release_id=uuid4(),
        title="Private assessment",
        expires_at="2030-01-01T00:00:00Z",
    )
    with pytest.raises(ValueError, match="Content release not found"):
        await create_campaign(db, tenant_id, uuid4(), payload)
    statement = str(db.scalar.await_args.args[0])
    assert "content_releases.id" in statement
    assert "content_releases.tenant_id" in statement


def test_results_csv_neutralizes_spreadsheet_formulas() -> None:
    campaign = CandidateAssessmentCampaign(title="=WEBSERVICE(1)")
    candidate = AssessmentCandidate(first_name="+cmd", last_name="")
    attempt = CandidateAssessmentAttempt(attempt_number=1, score_percent=50, passed=False, status="submitted")
    exported = results_csv([(campaign, candidate, attempt)])
    assert "'=WEBSERVICE(1)" in exported
    assert "'+cmd" in exported


def test_failed_attempt_can_retry_then_pass_and_exhaustion_completes() -> None:
    assert status_after_submission(passed=False, submitted_attempts=1, attempt_limit=2) == "active"
    assert status_after_submission(passed=True, submitted_attempts=2, attempt_limit=2) == "completed"
    assert status_after_submission(passed=False, submitted_attempts=2, attempt_limit=2) == "completed"
