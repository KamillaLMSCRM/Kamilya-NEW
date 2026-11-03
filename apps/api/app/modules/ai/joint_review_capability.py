"""Opt-in in-process joint review capability; not wired into generation.

Authority is the particular issuer instance and its trusted review callback. The
callback must actually review its supplied full request; the receipt cannot prove
model quality, authenticated source ownership, or survive a process restart.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

MAX_SOURCE_CHARS = 100_000
MAX_SOURCES = 256
MAX_QUESTION_CHARS = 12_000


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _request(tenant: str, lesson: str, policy: str, question: dict[str, Any],
             sources: list[dict[str, str]], *, job: str, attempt: str, source_revision: str) -> dict[str, Any]:
    if any(not isinstance(v, str) or not v or len(v) > 256
           for v in (tenant, lesson, policy, job, attempt, source_revision)):
        raise ValueError("joint_review_identity_invalid")
    if not isinstance(question, dict) or set(question) != {"text", "options", "answer"}:
        raise ValueError("joint_review_question_invalid")
    options = question["options"]
    if (not isinstance(question["text"], str) or not question["text"] or
        not isinstance(question["answer"], str) or not question["answer"] or
        not isinstance(options, list) or not 2 <= len(options) <= 16 or
        any(not isinstance(option, str) or not option for option in options) or
        question["answer"] not in options or
        sum(len(value) for value in (question["text"], question["answer"], *options)) > MAX_QUESTION_CHARS or
        len(_canonical(question)) > MAX_QUESTION_CHARS):
        raise ValueError("joint_review_question_invalid")
    if (not isinstance(sources, list) or not 1 <= len(sources) <= MAX_SOURCES or
        any(not isinstance(row, dict) or set(row) != {"id", "text"} or
            any(not isinstance(row[k], str) or not row[k] for k in ("id", "text")) or
            len(row["id"]) > 256 for row in sources) or
        len({row["id"] for row in sources}) != len(sources) or
        sum(len(row["text"]) for row in sources) > MAX_SOURCE_CHARS):
        raise ValueError("joint_review_sources_invalid")
    return {"tenant": tenant, "lesson": lesson, "policy": policy, "job": job, "attempt": attempt,
            "source_revision": source_revision, "question": question, "sources": sources}


@dataclass(frozen=True, slots=True)
class JointReviewReceipt:
    request_digest: str
    verdict: str
    mac: str


class JointReviewCapability:
    """Trusted callback and unpredictable process-local key are issuer authority."""

    def __init__(self, reviewer: Callable[[bytes], Awaitable[dict[str, str]]]):
        if not callable(reviewer):
            raise ValueError("joint_reviewer_invalid")
        self._reviewer = reviewer
        self._key = secrets.token_bytes(32)

    def _mac(self, digest: str, verdict: str) -> str:
        return hmac.new(self._key, _canonical(["joint-review-v1", digest, verdict]), hashlib.sha256).hexdigest()

    async def review(self, tenant: str, lesson: str, policy: str, question: dict[str, Any],
                     sources: list[dict[str, str]], *, job: str, attempt: str, source_revision: str) -> JointReviewReceipt:
        payload = _canonical(_request(tenant, lesson, policy, question, sources, job=job, attempt=attempt, source_revision=source_revision))
        digest = hashlib.sha256(payload).hexdigest()
        output = await self._reviewer(payload)
        if (not isinstance(output, dict) or set(output) != {"request_digest", "verdict"} or
            output["request_digest"] != digest or not isinstance(output["verdict"], str) or
            output["verdict"] not in {"pass", "hold"}):
            raise ValueError("joint_reviewer_output_invalid")
        verdict = output["verdict"]
        return JointReviewReceipt(digest, verdict, self._mac(digest, verdict))

    def verify(self, receipt: JointReviewReceipt, tenant: str, lesson: str, policy: str,
               question: dict[str, Any], sources: list[dict[str, str]], *, job: str, attempt: str, source_revision: str) -> bool:
        if (type(receipt) is not JointReviewReceipt or not isinstance(receipt.verdict, str) or
            receipt.verdict not in {"pass", "hold"} or not isinstance(receipt.request_digest, str) or
            not isinstance(receipt.mac, str) or
            re.fullmatch(r"[0-9a-f]{64}", receipt.request_digest) is None or
            re.fullmatch(r"[0-9a-f]{64}", receipt.mac) is None):
            return False
        digest = hashlib.sha256(_canonical(_request(tenant, lesson, policy, question, sources, job=job, attempt=attempt, source_revision=source_revision))).hexdigest()
        return (hmac.compare_digest(receipt.request_digest, digest) and
                hmac.compare_digest(receipt.mac, self._mac(digest, receipt.verdict)))

    async def review_batch(self, tenant: str, lesson: str, policy: str,
                           questions: list[dict[str, Any]], sources: list[dict[str, str]], *,
                           job: str, attempt: str, source_revision: str) -> dict[str, bool]:
        """One diagnostic request; each exact question receives an independent verdict."""
        if not isinstance(questions, list) or not 1 <= len(questions) <= 128:
            raise ValueError("joint_review_batch_invalid")
        checked = []
        for row in questions:
            if (not isinstance(row, dict) or set(row) != {"id", "question"} or
                not isinstance(row["id"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["id"])):
                raise ValueError("joint_review_batch_invalid")
            _request(tenant, lesson, policy, row["question"], sources, job=job,
                     attempt=attempt, source_revision=source_revision)
            checked.append(row["id"])
        if len(set(checked)) != len(checked):
            raise ValueError("joint_review_batch_invalid")
        payload = _canonical({"tenant": tenant, "lesson": lesson, "policy": policy, "job": job,
                              "attempt": attempt, "source_revision": source_revision,
                              "sources": sources, "questions": questions})
        digest = hashlib.sha256(payload).hexdigest()
        output = await self._reviewer(payload)
        if (not isinstance(output, dict) or set(output) != {"request_digest", "verdicts"} or
            output["request_digest"] != digest or not isinstance(output["verdicts"], list) or
            len(output["verdicts"]) > 256):
            raise ValueError("joint_reviewer_batch_output_invalid")
        result = {key: False for key in checked}
        seen: set[str] = set()
        duplicates: set[str] = set()
        for row in output["verdicts"]:
            if (not isinstance(row, dict) or set(row) != {"id", "verdict"} or
                not isinstance(row["id"], str) or row["id"] not in result or
                not isinstance(row["verdict"], str) or row["verdict"] not in {"pass", "hold"}):
                raise ValueError("joint_reviewer_batch_output_invalid")
            key = row["id"]
            if key in seen:
                duplicates.add(key)
            seen.add(key)
            result[key] = row["verdict"] == "pass" and key not in duplicates
        for key in duplicates:
            result[key] = False
        return result

    def admits(self, receipt: JointReviewReceipt, tenant: str, lesson: str, policy: str,
               question: dict[str, Any], sources: list[dict[str, str]], *, job: str, attempt: str,
               source_revision: str) -> bool:
        """Only an authentic pass admits; a valid hold is never admission."""
        return (type(receipt) is JointReviewReceipt and receipt.verdict == "pass" and
                self.verify(receipt, tenant, lesson, policy, question, sources,
                            job=job, attempt=attempt, source_revision=source_revision))
