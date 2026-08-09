from __future__ import annotations

import csv
import hashlib
import io
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_scoped_token, decode_token
from app.modules.candidate_assessments.models import (
    AssessmentCandidate,
    CandidateAccessCredential,
    CandidateAssessmentAttempt,
    CandidateAssessmentCampaign,
)
from app.modules.courses.release_models import ContentRelease
from app.modules.courses.release_service import canonical_json_sha256

PIN_HASHER = PasswordHasher()
LINK_TTL = timedelta(days=7)
LOCKOUT = timedelta(minutes=15)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def assessment_from_release(snapshot: dict[str, Any]) -> dict[str, Any]:
    quizzes = []
    for module in snapshot.get("modules", []):
        for lesson in module.get("lessons", []):
            for quiz in lesson.get("quizzes", []):
                if quiz.get("review_status") != "approved":
                    continue
                quizzes.append(
                    {
                        "id": quiz["id"],
                        "title": quiz["title"],
                        "pass_score": quiz.get("pass_score", 80),
                        "questions": [
                            {
                                "id": question["id"],
                                "text": question["text"],
                                "type": question.get("type", "single_choice"),
                                "points": question.get("points", 1),
                                "choices": [
                                    {
                                        "id": choice["id"],
                                        "text": choice["text"],
                                        "is_correct": bool(choice.get("is_correct")),
                                    }
                                    for choice in question.get("choices", [])
                                ],
                            }
                            for question in quiz.get("questions", [])
                        ],
                    }
                )
    if not quizzes or not any(quiz["questions"] for quiz in quizzes):
        raise ValueError("Release has no approved assessment questions")
    return {
        "schema_version": 1,
        "course_title": snapshot.get("course", {}).get("title", "Assessment"),
        "pass_score": max(int(quiz["pass_score"]) for quiz in quizzes),
        "quizzes": quizzes,
    }


def public_assessment(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in snapshot.items() if key != "quizzes"},
        "quizzes": [
            {
                **{key: value for key, value in quiz.items() if key != "questions"},
                "questions": [
                    {
                        **{key: value for key, value in question.items() if key != "choices"},
                        "choices": [
                            {key: value for key, value in choice.items() if key != "is_correct"}
                            for choice in question["choices"]
                        ],
                    }
                    for question in quiz["questions"]
                ],
            }
            for quiz in snapshot["quizzes"]
        ],
    }


def grade(snapshot: dict[str, Any], answers: list[dict[str, Any]]) -> dict[str, Any]:
    expected: dict[str, tuple[set[str], int]] = {}
    for quiz in snapshot["quizzes"]:
        for question in quiz["questions"]:
            expected[question["id"]] = (
                {choice["id"] for choice in question["choices"] if choice["is_correct"]},
                int(question.get("points", 1)),
            )
    submitted = {
        str(answer["question_id"]): {str(value) for value in answer["selected_choice_ids"]} for answer in answers
    }
    if set(submitted) != set(expected):
        raise ValueError("Submit every assessment question exactly once")
    earned = sum(points for qid, (correct, points) in expected.items() if submitted[qid] == correct)
    total = sum(points for _, points in expected.values())
    score = round(100 * earned / total) if total else 0
    normalized = sorted(
        ({"question_id": qid, "selected_choice_ids": sorted(values)} for qid, values in submitted.items()),
        key=lambda item: item["question_id"],
    )
    return {
        "answers": normalized,
        "answers_sha256": canonical_json_sha256({"answers": normalized}),
        "earned_points": earned,
        "total_points": total,
        "score_percent": score,
        "passed": score >= int(snapshot["pass_score"]),
    }


def status_after_submission(*, passed: bool, submitted_attempts: int, attempt_limit: int) -> str:
    return "completed" if passed or submitted_attempts >= attempt_limit else "active"


async def create_campaign(db: AsyncSession, tenant_id: UUID, actor_id: UUID, data) -> CandidateAssessmentCampaign:
    release = await db.scalar(
        select(ContentRelease).where(
            ContentRelease.id == data.content_release_id, ContentRelease.tenant_id == tenant_id
        )
    )
    if release is None:
        raise ValueError("Content release not found")
    snapshot = assessment_from_release(release.snapshot)
    campaign = CandidateAssessmentCampaign(
        tenant_id=tenant_id,
        content_release_id=release.id,
        created_by=actor_id,
        title=data.title,
        instructions=data.instructions,
        expires_at=data.expires_at,
        attempt_limit=data.attempt_limit,
        retention_days=data.retention_days,
        assessment_snapshot=snapshot,
        snapshot_sha256=canonical_json_sha256(snapshot),
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def add_candidate(db: AsyncSession, campaign_id: UUID, tenant_id: UUID, data, base_url: str) -> dict[str, Any]:
    campaign = await db.scalar(
        select(CandidateAssessmentCampaign)
        .where(CandidateAssessmentCampaign.id == campaign_id, CandidateAssessmentCampaign.tenant_id == tenant_id)
        .with_for_update()
    )
    if campaign is None or campaign.status != "active" or campaign.expires_at <= datetime.now(UTC):
        raise ValueError("Active campaign not found")
    candidate = AssessmentCandidate(
        tenant_id=tenant_id,
        campaign_id=campaign.id,
        first_name=data.first_name,
        last_name=data.last_name,
        email=data.email,
        phone=data.phone,
        retention_until=campaign.expires_at + timedelta(days=campaign.retention_days),
    )
    db.add(candidate)
    await db.flush()
    token, pin = secrets.token_urlsafe(32), f"{secrets.randbelow(1_000_000):06d}"
    expires_at = min(campaign.expires_at, datetime.now(UTC) + LINK_TTL)
    db.add(
        CandidateAccessCredential(
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            candidate_id=candidate.id,
            token_hash=token_hash(token),
            pin_hash=PIN_HASHER.hash(pin),
            expires_at=expires_at,
        )
    )
    await db.flush()
    return {
        "candidate_id": candidate.id,
        "access_url": f"{base_url.rstrip('/')}/candidate-assessment/{token}",
        "temporary_pin": pin,
        "expires_at": expires_at,
    }


async def establish_context(db: AsyncSession, token: str) -> UUID | None:
    return await db.scalar(text("SELECT lookup_candidate_assessment_tenant(:hash)"), {"hash": token_hash(token)})


async def exchange(db: AsyncSession, token: str, pin: str, consent: bool) -> dict[str, Any] | None:
    credential = await db.scalar(
        select(CandidateAccessCredential)
        .where(CandidateAccessCredential.token_hash == token_hash(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        credential is None
        or credential.revoked_at
        or credential.expires_at <= now
        or (credential.locked_until and credential.locked_until > now)
    ):
        return None
    try:
        PIN_HASHER.verify(credential.pin_hash, pin)
    except VerifyMismatchError:
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            credential.locked_until = now + LOCKOUT
        await db.flush()
        return None
    if not consent:
        raise ValueError("Consent is required")
    campaign = await db.scalar(
        select(CandidateAssessmentCampaign).where(
            CandidateAssessmentCampaign.id == credential.campaign_id,
            CandidateAssessmentCampaign.status == "active",
            CandidateAssessmentCampaign.expires_at > now,
        )
    )
    candidate = await db.scalar(
        select(AssessmentCandidate).where(
            AssessmentCandidate.id == credential.candidate_id, AssessmentCandidate.status.in_(("invited", "active"))
        )
    )
    if campaign is None or candidate is None:
        return None
    if canonical_json_sha256(campaign.assessment_snapshot) != campaign.snapshot_sha256:
        raise ValueError("Assessment snapshot integrity check failed")
    started_attempt = await db.scalar(
        select(CandidateAssessmentAttempt).where(
            CandidateAssessmentAttempt.candidate_id == candidate.id,
            CandidateAssessmentAttempt.campaign_id == campaign.id,
            CandidateAssessmentAttempt.status == "started",
        )
    )
    count = await db.scalar(
        select(func.count(CandidateAssessmentAttempt.id)).where(
            CandidateAssessmentAttempt.candidate_id == candidate.id,
            CandidateAssessmentAttempt.campaign_id == campaign.id,
        )
    )
    if started_attempt is not None:
        attempt = started_attempt
    elif int(count or 0) >= campaign.attempt_limit:
        return None
    else:
        attempt = CandidateAssessmentAttempt(
            tenant_id=credential.tenant_id,
            campaign_id=campaign.id,
            candidate_id=candidate.id,
            attempt_number=int(count or 0) + 1,
            assessment_snapshot=campaign.assessment_snapshot,
        )
        db.add(attempt)
    candidate.consented_at = candidate.consented_at or now
    candidate.status = "active"
    credential.failed_attempts = 0
    credential.locked_until = None
    await db.flush()
    capability = create_scoped_token(
        {
            "sub": str(candidate.id),
            "tenant_id": str(candidate.tenant_id),
            "campaign_id": str(campaign.id),
            "attempt_id": str(attempt.id),
            "credential_id": str(credential.id),
        },
        token_type="candidate_assessment",
        expires_delta=min(timedelta(hours=4), campaign.expires_at - now),
    )
    return {
        "access_token": capability,
        "attempt_id": attempt.id,
        "title": campaign.title,
        "instructions": campaign.instructions,
        "assessment": public_assessment(campaign.assessment_snapshot),
    }


def candidate_claims(token: str) -> dict[str, Any]:
    payload = decode_token(token)
    if payload.get("type") != "candidate_assessment":
        raise ValueError("Invalid candidate capability")
    return payload


async def submit(
    db: AsyncSession, claims: dict[str, Any], attempt_id: UUID, answers: list[dict[str, Any]]
) -> dict[str, Any]:
    now = datetime.now(UTC)
    credential = await db.scalar(
        select(CandidateAccessCredential).where(
            CandidateAccessCredential.id == UUID(claims["credential_id"]),
            CandidateAccessCredential.candidate_id == UUID(claims["sub"]),
            CandidateAccessCredential.campaign_id == UUID(claims["campaign_id"]),
            CandidateAccessCredential.tenant_id == UUID(claims["tenant_id"]),
            CandidateAccessCredential.revoked_at.is_(None),
            CandidateAccessCredential.expires_at > now,
        )
    )
    campaign = await db.scalar(
        select(CandidateAssessmentCampaign).where(
            CandidateAssessmentCampaign.id == UUID(claims["campaign_id"]),
            CandidateAssessmentCampaign.tenant_id == UUID(claims["tenant_id"]),
            CandidateAssessmentCampaign.status == "active",
            CandidateAssessmentCampaign.expires_at > now,
        )
    )
    candidate = await db.scalar(
        select(AssessmentCandidate).where(
            AssessmentCandidate.id == UUID(claims["sub"]),
            AssessmentCandidate.tenant_id == UUID(claims["tenant_id"]),
            AssessmentCandidate.status == "active",
        )
    )
    if credential is None or campaign is None or candidate is None:
        raise ValueError("Candidate capability has been revoked")
    attempt = await db.scalar(
        select(CandidateAssessmentAttempt)
        .where(
            CandidateAssessmentAttempt.id == attempt_id,
            CandidateAssessmentAttempt.id == UUID(claims["attempt_id"]),
            CandidateAssessmentAttempt.candidate_id == UUID(claims["sub"]),
            CandidateAssessmentAttempt.tenant_id == UUID(claims["tenant_id"]),
        )
        .with_for_update()
    )
    if attempt is None or attempt.status != "started":
        raise ValueError("Active attempt not found")
    if (
        attempt.campaign_id != campaign.id
        or canonical_json_sha256(campaign.assessment_snapshot) != campaign.snapshot_sha256
        or canonical_json_sha256(attempt.assessment_snapshot) != campaign.snapshot_sha256
    ):
        raise ValueError("Assessment snapshot integrity check failed")
    result = grade(attempt.assessment_snapshot, answers)
    for key, value in result.items():
        setattr(attempt, key, value)
    attempt.status = "submitted"
    attempt.submitted_at = now
    # The current row is already marked submitted and is included after flush;
    # flush explicitly before the aggregate so retry eligibility is deterministic.
    await db.flush()
    submitted_attempts = await db.scalar(
        select(func.count(CandidateAssessmentAttempt.id)).where(
            CandidateAssessmentAttempt.candidate_id == candidate.id,
            CandidateAssessmentAttempt.campaign_id == campaign.id,
            CandidateAssessmentAttempt.status == "submitted",
        )
    )
    candidate.status = status_after_submission(
        passed=bool(attempt.passed),
        submitted_attempts=int(submitted_attempts or 0),
        attempt_limit=campaign.attempt_limit,
    )
    await db.flush()
    return {"attempt_id": attempt.id, "score_percent": attempt.score_percent, "passed": attempt.passed}


def results_csv(rows: list[tuple[CandidateAssessmentCampaign, AssessmentCandidate, CandidateAssessmentAttempt]]) -> str:
    def safe_cell(value: object) -> object:
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return f"'{value}"
        return value

    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["campaign", "candidate", "status", "attempt", "score_percent", "passed", "submitted_at"])
    for campaign, candidate, attempt in rows:
        writer.writerow(
            [
                safe_cell(value)
                for value in [
                    campaign.title,
                    f"{candidate.first_name} {candidate.last_name}".strip(),
                    candidate.status,
                    attempt.attempt_number,
                    attempt.score_percent,
                    attempt.passed,
                    attempt.submitted_at.isoformat() if attempt.submitted_at else "",
                ]
            ]
        )
    return stream.getvalue()
