"""AI-COURSE-01 bounded acceptance wrapper for one preserved source.

Default invocation is a read-only authenticated preflight. ``--execute`` never
uploads or deletes a document and can delete only a newly returned course after
proving its job and source provenance.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

import httpx
from dotenv import dotenv_values

MAX_POLL_SECONDS = 720
POLL_SECONDS = 5
API_ROOT = "https://api.kml.kz/api/v1"
TENANT_ID = "83552ce6-8058-4561-abe3-cfbda14e030a"
TENANT_SLUG = "kamilya-production-smoke"
FULL_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
PREFERRED_SOURCE_DOCUMENT_ID = "05097f1b-8ae9-47be-ad26-0c65bdfb7a16"
PREFERRED_SOURCE_TITLE = "Smoke: безопасное обслуживание клиента"
PREFERRED_SOURCE_BYTES = 6682
PREFERRED_SOURCE_SHA256 = "ff889005b90f8e108e89831fe387b99bcc9cf0966f357a469a0ce37c6c67019a"
ACTIVE_JOB_STATES = frozenset({"queued", "pending", "running", "processing"})
TERMINAL_JOB_STATES = frozenset({"completed", "failed", "cancelled"})
ROOT = Path(__file__).resolve().parents[2]
METHOD_CREDENTIAL_KEYS = ("PRODUCTION_SMOKE_METHODOLOGIST_EMAIL", "PRODUCTION_SMOKE_METHODOLOGIST_PASSWORD")


class AcceptanceBlocked(RuntimeError):
    """A stable, response-body-free acceptance failure with safe ID evidence."""

    def __init__(self, reason: str, *, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.evidence = evidence or {}


class Api:
    """Minimal response-body-safe client required by this acceptance only."""

    def __init__(self, client: httpx.AsyncClient, base: str) -> None:
        self.client = client
        self.base = base.rstrip("/")

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        expected: tuple[int, ...] = (200,),
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"Origin": "https://app.kml.kz"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response = await self.client.request(
            method,
            f"{self.base}{path}",
            headers=headers,
            json=json_body,
        )
        if response.status_code not in expected:
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "")
                suffix = f":retry_after_seconds_{retry}" if retry.isdigit() else ""
                raise RuntimeError(f"request_failed:{method}:{path}:http_429{suffix}")
            raise RuntimeError(
                f"request_failed:{method}:{path}:http_{response.status_code}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(f"invalid_json:{method}:{path}") from exc


async def health(api: Api, expected_sha: str) -> None:
    if not FULL_SHA.fullmatch(expected_sha):
        raise RuntimeError("expected_release_sha_must_be_full_40_characters")
    payload = await api.request("GET", "/health")
    if not isinstance(payload, dict) or payload.get("release_sha") != expected_sha:
        raise RuntimeError("health_release_sha_mismatch")
    if payload.get("deployment_environment") != "kz-production":
        raise RuntimeError("health_deployment_mismatch")


async def methodologist_context(api: Api, token: str) -> dict[str, Any]:
    payload = await api.request("GET", "/users/me", token=token)
    if not isinstance(payload, dict):
        raise RuntimeError("methodologist_context_contract_invalid")
    if payload.get("tenant_id") != TENANT_ID or "methodologist" not in payload.get(
        "roles", []
    ):
        raise RuntimeError("methodologist_identity_mismatch")
    return payload


def load_methodologist_credentials() -> None:
    values = dotenv_values(ROOT / ".env")
    selected: dict[str, str] = {}
    for key in METHOD_CREDENTIAL_KEYS:
        value = values.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AcceptanceBlocked(f"{key}_missing")
        selected[key] = value.strip()
    os.environ.update(selected)


def canonical_uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise AcceptanceBlocked(f"{name}_missing_or_invalid")
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise AcceptanceBlocked(f"{name}_missing_or_invalid") from exc
    if value != parsed:
        raise AcceptanceBlocked(f"{name}_noncanonical")
    return parsed


class AcceptanceApi(Api):
    async def validate_source_download(self, token: str, document_id: str) -> None:
        """Hash the exact bounded stream without retaining or emitting its content."""
        document_id = canonical_uuid(document_id, "source_document_id")
        headers = {"Authorization": f"Bearer {token}", "Origin": "https://app.kml.kz"}
        digest = hashlib.sha256()
        byte_count = 0
        async with self.client.stream("GET", f"{self.base}/documents/{document_id}/download", headers=headers) as response:
            if response.status_code != 200:
                raise AcceptanceBlocked(f"source_download_http_{response.status_code}")
            if response.headers.get("Content-Length") != str(PREFERRED_SOURCE_BYTES):
                raise AcceptanceBlocked("source_download_size_invalid")
            async for chunk in response.aiter_bytes():
                byte_count += len(chunk)
                if byte_count > PREFERRED_SOURCE_BYTES:
                    raise AcceptanceBlocked("source_download_size_invalid")
                digest.update(chunk)
        if byte_count != PREFERRED_SOURCE_BYTES:
            raise AcceptanceBlocked("source_download_size_mismatch")
        if digest.hexdigest() != PREFERRED_SOURCE_SHA256:
            raise AcceptanceBlocked("source_download_sha256_mismatch")


async def request_dict(api: Api, method: str, path: str, *, token: str,
                       expected: tuple[int, ...] = (200,), json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = await api.request(method, path, token=token, expected=expected, json_body=json_body)
    if not isinstance(payload, dict):
        raise AcceptanceBlocked(f"{method.lower()}_{path.strip('/').replace('/', '_')}_contract_invalid")
    return payload


async def wait_for_terminal_job(api: Api, token: str, job_id: str, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                                monotonic: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    job_id = canonical_uuid(job_id, "job_id")
    started = monotonic()
    while True:
        job = await request_dict(api, "GET", f"/ai/jobs/{job_id}", token=token)
        if canonical_uuid(job.get("id"), "job_readback_id") != job_id:
            raise AcceptanceBlocked("job_identity_mismatch")
        status = job.get("status")
        if status in TERMINAL_JOB_STATES:
            return job
        if status not in ACTIVE_JOB_STATES:
            raise AcceptanceBlocked("job_status_unknown")
        if monotonic() - started >= MAX_POLL_SECONDS:
            raise AcceptanceBlocked("job_poll_timeout")
        await sleep(POLL_SECONDS)


def course_ids(payload: Any) -> set[str]:
    if not isinstance(payload, list):
        raise AcceptanceBlocked("course_inventory_contract_invalid")
    return {canonical_uuid(course.get("id") if isinstance(course, dict) else None, "course_inventory_id") for course in payload}


def structure_counts(payload: dict[str, Any]) -> tuple[set[str], int, int]:
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        raise AcceptanceBlocked("course_structure_modules_missing")
    lesson_ids: set[str] = set()
    lessons = 0
    for module in modules:
        if not isinstance(module, dict) or not isinstance(module.get("lessons"), list):
            raise AcceptanceBlocked("course_structure_contract_invalid")
        for lesson in module["lessons"]:
            if not isinstance(lesson, dict):
                raise AcceptanceBlocked("course_structure_contract_invalid")
            lesson_ids.add(canonical_uuid(lesson.get("id"), "lesson_id"))
            title = lesson.get("title")
            if not isinstance(title, str) or not any("\u0400" <= char <= "\u04ff" for char in title):
                raise AcceptanceBlocked("lesson_title_not_cyrillic")
            lessons += 1
    if not lesson_ids:
        raise AcceptanceBlocked("course_structure_lessons_missing")
    return lesson_ids, len(modules), lessons


def quiz_counts(payload: Any, lesson_ids: set[str]) -> tuple[int, int, int]:
    if not isinstance(payload, list):
        raise AcceptanceBlocked("quizzes_contract_invalid")
    quizzes = questions = choices = 0
    for quiz in payload:
        if not isinstance(quiz, dict) or quiz.get("lesson_id") not in lesson_ids:
            continue
        canonical_uuid(quiz.get("id"), "quiz_id")
        if not isinstance(quiz.get("title"), str) or not isinstance(quiz.get("pass_score"), int) or not isinstance(quiz.get("attempt_limit"), int):
            raise AcceptanceBlocked("quiz_contract_invalid")
        quiz_questions = quiz.get("questions")
        if not isinstance(quiz_questions, list):
            raise AcceptanceBlocked("quiz_questions_contract_invalid")
        quizzes += 1
        for question in quiz_questions:
            if (not isinstance(question, dict) or not isinstance(question.get("text"), str)
                    or not isinstance(question.get("type"), str) or not isinstance(question.get("points"), int)
                    or not isinstance(question.get("order_index"), int) or not isinstance(question.get("choices"), list)):
                raise AcceptanceBlocked("quiz_question_contract_invalid")
            canonical_uuid(question.get("id"), "quiz_question_id")
            questions += 1
            for choice in question["choices"]:
                if (not isinstance(choice, dict) or not isinstance(choice.get("text"), str)
                        or not isinstance(choice.get("order_index"), int) or not isinstance(choice.get("is_correct"), bool)):
                    raise AcceptanceBlocked("quiz_choice_contract_invalid")
                canonical_uuid(choice.get("id"), "quiz_choice_id")
                choices += 1
    if not quizzes or not questions or not choices:
        raise AcceptanceBlocked("generated_quiz_structure_missing")
    return quizzes, questions, choices


async def source_readback(api: AcceptanceApi, token: str, source_id: str) -> None:
    document = await request_dict(api, "GET", f"/documents/{source_id}", token=token)
    if canonical_uuid(document.get("id"), "source_document_readback_id") != source_id or document.get("title") != PREFERRED_SOURCE_TITLE:
        raise AcceptanceBlocked("existing_document_readback_mismatch")
    await api.validate_source_download(token, source_id)


def ru_contract(course: dict[str, Any]) -> None:
    """CourseResponse has no language field; enforce it only if later exposed."""
    if course.get("language") is not None and course.get("language") != "ru":
        raise AcceptanceBlocked("course_language_not_ru")


async def login(api: Api, email_name: str, password_name: str) -> str:
    # TenantSummary is in auth TokenResponse.user, not GET /users/me.
    if (email_name, password_name) != METHOD_CREDENTIAL_KEYS:
        raise AcceptanceBlocked('credential_names_mismatch')
    result = await request_dict(api, 'POST', '/auth/login', token='', json_body={
        'email': os.environ[email_name], 'password': os.environ[password_name],
    })
    user = result.get('user')
    tenant = user.get('tenant') if isinstance(user, dict) else None
    if (not isinstance(tenant, dict) or tenant.get('id') != TENANT_ID
            or tenant.get('slug') != TENANT_SLUG or tenant.get('is_demo') is not True
            or user.get('tenant_id') != TENANT_ID or user.get('role') != 'methodologist'):
        raise AcceptanceBlocked('synthetic_tenant_contract_mismatch')
    token = result.get('access_token')
    if not isinstance(token, str) or not token:
        raise AcceptanceBlocked('login_token_missing')
    return token


async def preflight(
    api: AcceptanceApi,
    *,
    source_document_id: str | None,
    expected_release_sha: str,
) -> tuple[str, dict[str, Any]]:
    source_id = canonical_uuid(source_document_id, "source_document_id")
    if source_id != PREFERRED_SOURCE_DOCUMENT_ID:
        raise AcceptanceBlocked("source_document_id_not_root_approved")
    await health(api, expected_release_sha)
    token = await login(api, *METHOD_CREDENTIAL_KEYS)
    me = await methodologist_context(api, token)
    if me.get('role') != 'methodologist':
        raise AcceptanceBlocked('active_methodologist_role_mismatch')
    catalog = await request_dict(api, "GET", "/documents/catalog?limit=100", token=token)
    documents = catalog.get("items")
    if not isinstance(documents, list) or catalog.get("page", {}).get("has_more") is True:
        raise AcceptanceBlocked("document_capacity_contract_invalid")
    matches = [item for item in documents if isinstance(item, dict) and item.get("id") == source_id]
    if len(matches) != 1:
        raise AcceptanceBlocked("existing_document_not_exactly_one")
    marker = matches[0].get("index")
    if not isinstance(marker, dict) or marker.get("status") != "ready" or matches[0].get("title") != PREFERRED_SOURCE_TITLE:
        raise AcceptanceBlocked("existing_document_source_marker_mismatch")
    await source_readback(api, token, source_id)
    inventory = course_ids(await api.request("GET", "/courses?per_page=100", token=token))
    if len(inventory) >= 5:
        raise AcceptanceBlocked("course_capacity")
    return token, {"document_id": source_id, "course_ids": sorted(inventory)}


async def cleanup_course(api: Api, token: str, course_id: str, *, prior_course_ids: set[str]) -> None:
    if course_id in prior_course_ids:
        raise AcceptanceBlocked("generated_course_preexisting")
    await api.request("DELETE", f"/courses/{course_id}", token=token, expected=(204,))
    await api.request("GET", f"/courses/{course_id}", token=token, expected=(404,))


async def cancel_owned_job_on_timeout(api: Api, token: str, job_id: str) -> str | None:
    """Cancel only a captured, identity- and type-verified generation job."""
    current = await request_dict(api, "GET", f"/ai/jobs/{job_id}", token=token)
    if canonical_uuid(current.get("id"), "job_cancel_readback_id") != job_id:
        return None
    course_id = canonical_uuid(current.get("course_id"), "job_timeout_course_id") if current.get("course_id") is not None else None
    if current.get("job_type") != "course_generation" or current.get("status") not in ACTIVE_JOB_STATES:
        return course_id
    cancelled = await request_dict(api, "POST", f"/ai/jobs/{job_id}/cancel", token=token)
    # The cancel route returns only status; identity comes from the addressed
    # route and the independent full job readback, not an invented response id.
    if cancelled.get("status") != "cancelled":
        return course_id
    readback = await request_dict(api, "GET", f"/ai/jobs/{job_id}", token=token)
    if canonical_uuid(readback.get("id"), "job_cancel_final_id") != job_id or readback.get("status") != "cancelled":
        return course_id
    return course_id


async def execute(
    api: AcceptanceApi,
    *,
    expected_release_sha: str,
    source_document_id: str | None = PREFERRED_SOURCE_DOCUMENT_ID,
) -> dict[str, Any]:
    """Run one preserved-source journey; do not retry uncertain cleanup."""
    token = ""
    generation_job_id: str | None = None
    course_id: str | None = None
    cleanup_started = False
    provenance_verified = False
    capacity: dict[str, Any] | None = None
    try:
        token, capacity = await preflight(
            api,
            source_document_id=source_document_id,
            expected_release_sha=expected_release_sha,
        )
        source_id = capacity["document_id"]
        generated = await request_dict(api, "POST", "/ai/generate-course", token=token, expected=(202,), json_body={
            "documents": [source_id], "course_format": "brief", "num_modules": 1,
            "language": "ru", "target_audience": "synthetic acceptance only",
            "reuse_reason": "other",
        })
        generation_job_id = canonical_uuid(generated.get("id"), "generation_job_id")
        if generated.get("job_type") != "course_generation" or generated.get("course_id") is not None:
            raise AcceptanceBlocked("generation_job_contract_invalid")
        terminal = await wait_for_terminal_job(api, token, generation_job_id)
        if terminal.get("job_type") != "course_generation":
            raise AcceptanceBlocked("generation_job_type_mismatch")
        if terminal.get("course_id") is not None:
            course_id = canonical_uuid(terminal.get("course_id"), "generated_course_id")
        if terminal.get("status") != "completed":
            raise AcceptanceBlocked("generation_not_completed")
        if course_id is None:
            raise AcceptanceBlocked("generated_course_id_missing_or_invalid")
        if course_id in capacity["course_ids"]:
            raise AcceptanceBlocked("generated_course_preexisting")
        course = await request_dict(api, "GET", f"/courses/{course_id}", token=token)
        if canonical_uuid(course.get("id"), "generated_course_readback_id") != course_id:
            raise AcceptanceBlocked("generated_course_identity_mismatch")
        if course.get("tenant_id") != TENANT_ID or course.get("ai_generated") is not True:
            raise AcceptanceBlocked("generated_course_disposable_contract_invalid")
        if course.get("source_document_ids") != [source_id]:
            raise AcceptanceBlocked("generated_course_source_linkage_mismatch")
        ru_contract(course)
        provenance_verified = True
        structure = await request_dict(api, "GET", f"/courses/{course_id}/structure", token=token)
        lesson_ids, modules, lessons = structure_counts(structure)
        quizzes, questions, choices = quiz_counts(await api.request("GET", "/quizzes", token=token), lesson_ids)
        cleanup_started = True
        await cleanup_course(api, token, course_id, prior_course_ids=set(capacity["course_ids"]))
        inventory_after = course_ids(await api.request("GET", "/courses?per_page=100", token=token))
        if inventory_after != set(capacity["course_ids"]):
            raise AcceptanceBlocked("course_inventory_not_restored")
        await source_readback(api, token, source_id)
        return {"status": "PASS", "tenant_id": TENANT_ID, "document_id": source_id, "course_id": course_id,
                "modules": modules, "lessons": lessons, "quizzes": quizzes, "questions": questions, "choices": choices,
                "preserved_document": True, "course_deleted": True, "document_deleted": False}
    except Exception as exc:
        reason = str(exc) if isinstance(exc, AcceptanceBlocked) else type(exc).__name__
        if isinstance(exc, RuntimeError):
            matched = re.fullmatch(r'request_failed:(GET|POST|DELETE):/[A-Za-z0-9_/?=.-]+:http_(\d{3})(?::retry_after_seconds_\d+)?', str(exc))
            if matched:
                reason = 'api_http_' + matched.group(2)
        cleanup_confirmed = False
        # A timeout has one narrowly scoped recovery: cancel the verified owned job.
        if reason == "job_poll_timeout" and token and generation_job_id:
            try:
                timeout_course_id = await cancel_owned_job_on_timeout(api, token, generation_job_id)
                if course_id is None:
                    course_id = timeout_course_id
            except Exception:
                pass
        # Once course provenance is proven, structural assertion failure may safely clean it once.
        if provenance_verified and course_id and not cleanup_started and capacity:
            cleanup_started = True
            try:
                await cleanup_course(api, token, course_id, prior_course_ids=set(capacity["course_ids"]))
                cleanup_confirmed = True
            except Exception:
                pass
        evidence: dict[str, Any] = {"generation_job_id": generation_job_id, "course_id": course_id,
                                    "cleanup_started": cleanup_started, "cleanup_confirmed": cleanup_confirmed}
        if capacity:
            evidence.update(source_document_id=capacity["document_id"], original_course_ids=capacity["course_ids"])
        raise AcceptanceBlocked(reason, evidence=evidence) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform one root-reviewed preserved-source API journey")
    parser.add_argument("--source-document-id", help="required approved preserved source UUID")
    parser.add_argument(
        "--expected-release-sha",
        required=True,
        help="required exact 40-character production release SHA",
    )
    args = parser.parse_args()
    try:
        load_methodologist_credentials()
        async def run() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
                api = AcceptanceApi(client, API_ROOT)
                if not args.execute:
                    _, result = await preflight(
                        api,
                        source_document_id=args.source_document_id,
                        expected_release_sha=args.expected_release_sha,
                    )
                    return {"status": "READY", "read_only": True, "tenant_id": TENANT_ID, **result}
                return await execute(
                    api,
                    source_document_id=args.source_document_id,
                    expected_release_sha=args.expected_release_sha,
                )
        print(json.dumps(asyncio.run(run()), sort_keys=True))
        return 0
    except (AcceptanceBlocked, RuntimeError, OSError, KeyError, httpx.HTTPError) as error:
        reason = str(error) if isinstance(error, AcceptanceBlocked) else type(error).__name__
        evidence = error.evidence if isinstance(error, AcceptanceBlocked) else {}
        print(json.dumps({"status": "BLOCKED", "reason": reason, **evidence}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
