"""Controlled production journey for the first Kamilya LMS tenant.

The script exercises the real public API and Celery worker, while using the
migration connection only for assertions that a learner must never be able to
perform (reading quiz keys) and deterministic cleanup.

It never prints passwords, tokens, OTP codes, email addresses, or provider
credentials. The temporary tenant and its object-storage documents are removed
in ``finally``.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import httpx
from openpyxl import Workbook
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.getenv("SMOKE_API_BASE", "https://kamilya-lms-api.onrender.com/api/v1")
GENERAL_SOURCE = (
    ROOT
    / "docs"
    / "Документы тенантов"
    / "tenant2_acme_corp"
    / "02_client_onboarding_process.md"
)
JD_SOURCE = (
    ROOT
    / "docs"
    / "Документы тенантов"
    / "tenant2_acme_corp"
    / "jd_creative_director.md"
)


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(f".env not found at {env_path}")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    migration_url = os.getenv("MIGRATION_DATABASE_URL")
    if not migration_url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL is required for assertions and cleanup"
        )
    os.environ["DATABASE_URL"] = migration_url


def step(name: str, **evidence: object) -> None:
    suffix = " ".join(f"{key}={value}" for key, value in evidence.items())
    print(f"[PASS] {name}" + (f" {suffix}" if suffix else ""), flush=True)


def make_alias(base_email: str, label: str, suffix: str) -> str:
    local, separator, domain = base_email.strip().lower().partition("@")
    if not separator or not local or not domain:
        raise RuntimeError("TENANT_ADMIN_EMAIL must contain a valid mailbox")
    local = local.split("+", 1)[0]
    return f"{local}+synthetic-{label}-{suffix}@{domain}"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    label: str,
    expected: tuple[int, ...] = (200,),
    retries: int = 4,
    **kwargs,
) -> httpx.Response:
    url = path if path.startswith("http") else f"{API_BASE}{path}"
    for attempt in range(retries + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code in expected:
            return response
        if response.status_code in {429, 503} and attempt < retries:
            retry_after = response.headers.get("Retry-After", "5")
            try:
                delay = min(30, max(2, int(retry_after)))
            except ValueError:
                delay = 5
            await asyncio.sleep(delay)
            continue
        body = response.text[:1200].replace("\n", " ")
        raise RuntimeError(f"{label} failed: HTTP {response.status_code}: {body}")
    raise RuntimeError(f"{label} failed after retries")


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    label: str,
    expected: tuple[int, ...] = (200,),
    **kwargs,
) -> dict | list:
    response = await request(
        client,
        method,
        path,
        label=label,
        expected=expected,
        **kwargs,
    )
    return response.json()


def fetch_otp_from_vps(email: str) -> str:
    host = os.getenv("VPS_URL", "").strip()
    if not host:
        raise RuntimeError("VPS_URL is required to verify the real email OTP flow")
    target = host if "@" in host else f"root@{host}"
    key = f"auth:email:{email.lower().strip()}"
    command = (
        "value=$(valkey-cli --raw GET "
        + shlex.quote(key)
        + '); test -n "$value" && printf \'%s\' "$value"'
    )
    completed = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            target,
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise RuntimeError("Email OTP was not found in production Valkey")
    payload = json.loads(completed.stdout)
    code = str(payload.get("code", ""))
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError("Production email OTP payload is invalid")
    return code


async def poll_job(
    client: httpx.AsyncClient,
    token: str,
    job_id: str,
    *,
    label: str,
    timeout_seconds: int = 900,
) -> dict:
    started = time.monotonic()
    last_marker: tuple[str, str, int] | None = None
    while time.monotonic() - started < timeout_seconds:
        body = await request_json(
            client,
            "GET",
            f"/ai/jobs/{job_id}",
            label=f"{label} poll",
            headers=auth(token),
        )
        marker = (
            str(body.get("status")),
            str(body.get("stage")),
            int(body.get("progress") or 0),
        )
        if marker != last_marker:
            print(
                f"[WAIT] {label} status={marker[0]} stage={marker[1]} progress={marker[2]}",
                flush=True,
            )
            last_marker = marker
        if body.get("status") in {"completed", "failed", "cancelled"}:
            if body.get("status") != "completed":
                raise RuntimeError(
                    f"{label} ended with status={body.get('status')} "
                    f"message={body.get('message')}"
                )
            return body
        await asyncio.sleep(8)
    raise RuntimeError(f"{label} timed out after {timeout_seconds}s")


def staffing_workbook(suffix: str, email: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Employees"
    sheet.append(
        [
            "personnel_number",
            "first_name",
            "last_name",
            "department",
            "position",
            "email",
        ]
    )
    sheet.append(
        [
            f"XLSX-{suffix}",
            "Imported",
            "Learner",
            "Client Operations",
            "Client Onboarding Specialist",
            email,
        ]
    )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


async def correct_answers(
    tenant_id: str, course_id: str
) -> dict[str, dict[str, list[str]]]:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from app.core.db import async_session_factory

    query = text(
        """
        SELECT z.id AS quiz_id, q.id AS question_id, c.id AS choice_id
        FROM courses co
        JOIN modules m ON m.course_id = co.id
        JOIN lessons l ON l.module_id = m.id
        JOIN quizzes z ON z.lesson_id = l.id
        JOIN questions q ON q.quiz_id = z.id
        JOIN quiz_choices c ON c.question_id = q.id
        WHERE co.id = :course_id
          AND co.tenant_id = :tenant_id
          AND c.is_correct = true
        ORDER BY m.order_index, l.order_index, q.order_index, c.order_index
        """
    )
    result: dict[str, dict[str, list[str]]] = {}
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_current_tenant(:tenant_id)"),
            {"tenant_id": tenant_id},
        )
        rows = (
            await session.execute(
                query,
                {"tenant_id": tenant_id, "course_id": course_id},
            )
        ).mappings()
        for row in rows:
            quiz = result.setdefault(str(row["quiz_id"]), {})
            quiz.setdefault(str(row["question_id"]), []).append(str(row["choice_id"]))
    return result


async def cleanup_tenant(tenant_id: str) -> None:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    from app.core.db import async_session_factory
    from app.core.storage import get_storage
    from app.models.document import Document
    from app.modules.admin.superadmin.service import SuperadminService

    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_current_tenant(:tenant_id)"),
            {"tenant_id": tenant_id},
        )
        keys = list(
            (
                await session.execute(
                    select(Document.s3_key).where(
                        Document.tenant_id == UUID(tenant_id),
                        Document.s3_key != "",
                    )
                )
            ).scalars()
        )
        storage = get_storage()
        failed_keys: list[str] = []
        for key in keys:
            try:
                storage.delete_bytes(key)
            except Exception:  # noqa: BLE001 - cleanup must report every provider failure
                failed_keys.append(key)
        if failed_keys:
            raise RuntimeError(
                f"Cleanup stopped: {len(failed_keys)} object-storage files could not be removed"
            )
        await SuperadminService(session).delete_tenant(UUID(tenant_id))
    step("cleanup", objects=len(keys))


async def run_journey() -> None:
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    base_email = os.environ["TENANT_ADMIN_EMAIL"]
    admin_email = make_alias(base_email, "admin", suffix)
    methodologist_email = make_alias(base_email, "methodologist", suffix)
    manual_email = make_alias(base_email, "manual", suffix)
    imported_email = make_alias(base_email, "import", suffix)
    learner_email = make_alias(base_email, "learner", suffix)
    password = f"Synthetic-{suffix}-{uuid4().hex[:8]}!"
    tenant_id: str | None = None

    timeout = httpx.Timeout(300.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        try:
            registration = await request_json(
                client,
                "POST",
                "/tenants/register",
                label="tenant registration",
                expected=(201,),
                json={
                    "company_name": f"Synthetic Pilot {suffix}",
                    "contact_name": "Synthetic Administrator",
                    "email": admin_email,
                    "password": password,
                    "phone": "+7 700 000 00 00",
                    "employee_count_range": "1-10",
                    "preferred_language": "ru",
                    "intent": "try",
                    "message": "Automated first-tenant production acceptance journey",
                },
            )
            tenant_id = str(registration["tenant_id"])
            admin_token = str(registration["access_token"])
            assert registration["role"] == "admin"
            assert registration["limits"]["ai_course_generations_limit"] == 1
            assert registration["limits"]["jd_course_generations_limit"] == 1
            step("tenant registration", plan="trial", limits="1+1")

            initial_usage = await request_json(
                client,
                "GET",
                "/admin/trial-usage",
                label="initial trial usage",
                headers=auth(admin_token),
            )
            assert initial_usage["ai_courses"]["used"] == 0
            assert initial_usage["jd_courses"]["used"] == 0
            assert initial_usage["system_users"]["used"] == 1
            step("initial trial usage")

            await request_json(
                client,
                "POST",
                "/auth/email/request-code",
                label="email OTP request",
                json={"email": admin_email},
            )
            otp = fetch_otp_from_vps(admin_email)
            verified = await request_json(
                client,
                "POST",
                "/auth/email/verify-code",
                label="email OTP verify",
                json={"email": admin_email, "code": otp},
            )
            assert verified["verified"] is True
            step("email OTP login")

            await request_json(
                client,
                "POST",
                "/auth/logout",
                label="logout",
                json={"refresh_token": str(verified["refresh_token"])},
            )
            password_login = await request_json(
                client,
                "POST",
                "/auth/login",
                label="password login after logout",
                json={"email": admin_email, "password": password},
            )
            admin_token = str(password_login["access_token"])
            step("logout and repeat login")

            methodologist = await request_json(
                client,
                "POST",
                "/users",
                label="create methodologist",
                expected=(201,),
                headers=auth(admin_token),
                json={
                    "email": methodologist_email,
                    "first_name": "Synthetic",
                    "last_name": "Methodologist",
                    "role": "methodologist",
                    "password": password,
                    "is_active": True,
                },
            )
            assert methodologist["role"] == "methodologist"
            assert "methodologist" in methodologist["roles"]
            methodologist_login = await request_json(
                client,
                "POST",
                "/auth/login",
                label="methodologist login",
                json={"email": methodologist_email, "password": password},
            )
            methodologist_token = str(methodologist_login["access_token"])
            step("methodologist account and login")

            general_bytes = GENERAL_SOURCE.read_bytes()
            general_doc = await request_json(
                client,
                "POST",
                "/documents/upload",
                label="general document upload",
                expected=(201,),
                headers=auth(methodologist_token),
                files={
                    "file": (
                        "client-onboarding-process.txt",
                        general_bytes,
                        "text/plain",
                    )
                },
                data={
                    "title": "Client onboarding process",
                    "description": "Synthetic production smoke source",
                    "category": "general",
                },
            )
            assert general_doc["embedding_status"] == "success", general_doc.get(
                "embedding_error"
            )
            step("general document indexed")

            ordinary_job = await request_json(
                client,
                "POST",
                "/ai/generate-course",
                label="ordinary course generation",
                expected=(202,),
                headers=auth(methodologist_token),
                json={
                    "documents": [general_doc["id"]],
                    "target_audience": "New client onboarding specialists",
                    "num_modules": 1,
                    "language": "ru",
                    "tone": "professional",
                    "source_strategy": "single_topic",
                },
            )
            ordinary_final = await poll_job(
                client,
                methodologist_token,
                str(ordinary_job["id"]),
                label="ordinary generation",
            )
            ordinary_course_id = str(ordinary_final["course_id"])
            ordinary_preview = await request_json(
                client,
                "GET",
                f"/courses/{ordinary_course_id}/preview",
                label="ordinary course preview",
                headers=auth(methodologist_token),
            )
            assert ordinary_preview["modules_count"] >= 1
            assert ordinary_preview["lessons_count"] >= 1
            assert ordinary_preview["quizzes_count"] >= 1
            await request_json(
                client,
                "POST",
                f"/courses/{ordinary_course_id}/review",
                label="ordinary course review",
                headers=auth(methodologist_token),
                json={
                    "review_status": "approved",
                    "comment": "Synthetic source and structure review passed",
                },
            )
            published = await request_json(
                client,
                "POST",
                f"/courses/{ordinary_course_id}/publish",
                label="ordinary course publication",
                headers=auth(methodologist_token),
            )
            assert published["status"] == "published"
            step(
                "ordinary course generated and published",
                modules=ordinary_preview["modules_count"],
                lessons=ordinary_preview["lessons_count"],
                quizzes=ordinary_preview["quizzes_count"],
            )

            position = await request_json(
                client,
                "POST",
                "/positions",
                label="position creation",
                expected=(201,),
                headers=auth(methodologist_token),
                json={
                    "name": "Creative Director",
                    "department": "Creative",
                    "level": "lead",
                    "responsibilities": "",
                    "requirements": "",
                    "course_ids": [],
                },
            )
            position_id = str(position["id"])
            jd_position = await request_json(
                client,
                "POST",
                f"/positions/{position_id}/instruction",
                label="job instruction upload",
                headers=auth(methodologist_token),
                files={
                    "file": (
                        "creative-director-instruction.txt",
                        JD_SOURCE.read_bytes(),
                        "text/plain",
                    )
                },
            )
            assert jd_position["instruction_embedding_status"] == "success"
            position_name = str(jd_position["name"])
            jd_job = await request_json(
                client,
                "POST",
                f"/positions/{position_id}/generate-instruction-course",
                label="instruction course generation",
                expected=(202,),
                headers=auth(methodologist_token),
                json={
                    "target_audience": position_name,
                    "num_modules": 1,
                    "language": "ru",
                },
            )
            jd_final = await poll_job(
                client,
                methodologist_token,
                str(jd_job["job_id"]),
                label="instruction generation",
            )
            jd_course_id = str(jd_job["course_id"])
            assert str(jd_final["course_id"]) == jd_course_id
            jd_preview = await request_json(
                client,
                "GET",
                f"/courses/{jd_course_id}/preview",
                label="instruction course preview",
                headers=auth(methodologist_token),
            )
            assert jd_preview["lessons_count"] >= 1
            await request_json(
                client,
                "POST",
                f"/courses/{jd_course_id}/review",
                label="instruction course review",
                headers=auth(methodologist_token),
                json={
                    "review_status": "approved",
                    "comment": "Synthetic job-instruction review passed",
                },
            )
            jd_published = await request_json(
                client,
                "POST",
                f"/courses/{jd_course_id}/publish",
                label="instruction course publication",
                headers=auth(methodologist_token),
            )
            assert jd_published["status"] == "published"
            step("instruction course generated and published")

            usage = await request_json(
                client,
                "GET",
                "/admin/trial-usage",
                label="final generation usage",
                headers=auth(admin_token),
            )
            assert usage["ai_courses"]["used"] == 1, usage["ai_courses"]
            assert usage["jd_courses"]["used"] == 1, usage["jd_courses"]
            step("trial generation limits", ai="1/1", jd="1/1")

            manual = await request_json(
                client,
                "POST",
                "/admin/staff/manual",
                label="manual learner creation",
                expected=(201,),
                headers=auth(methodologist_token),
                json={
                    "personnel_number": f"MANUAL-{suffix}",
                    "first_name": "Manual",
                    "last_name": "Learner",
                    "department": "Creative",
                    "position": position_name,
                    "email": manual_email,
                },
            )
            assert manual["created"] == 1
            users = await request_json(
                client,
                "GET",
                "/users?per_page=100",
                label="user list after manual create",
                headers=auth(admin_token),
            )
            manual_user = next(
                user for user in users["users"] if user["email"] == manual_email
            )
            step("manual learner creation")

            await request_json(
                client,
                "POST",
                f"/positions/{position_id}/courses",
                label="position course attachment",
                expected=(201,),
                headers=auth(methodologist_token),
                json={"course_id": ordinary_course_id, "required": True},
            )
            await request_json(
                client,
                "POST",
                f"/positions/{position_id}/courses",
                label="idempotent position course attachment",
                expected=(201,),
                headers=auth(methodologist_token),
                json={"course_id": ordinary_course_id, "required": True},
            )
            enrollments = await request_json(
                client,
                "GET",
                f"/courses/{ordinary_course_id}/enrollments",
                label="rule enrollment verification",
                headers=auth(methodologist_token),
            )
            assert sum(row["user_id"] == manual_user["id"] for row in enrollments) == 1
            step("position rule idempotency")

            xlsx = staffing_workbook(suffix, imported_email)
            xlsx_file = {
                "file": (
                    "synthetic-staffing.xlsx",
                    xlsx,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            }
            preview = await request_json(
                client,
                "POST",
                "/admin/staff/import/preview",
                label="staff import preview",
                headers=auth(methodologist_token),
                files=xlsx_file,
            )
            assert preview["missing_required_columns"] == []
            assert preview["summary"]["create"] == 1
            committed = await request_json(
                client,
                "POST",
                "/admin/staff/import/commit",
                label="staff import commit",
                headers=auth(methodologist_token),
                files=xlsx_file,
            )
            assert committed["created"] == 1
            step("XLSX staff preview and commit")

            invitation = await request_json(
                client,
                "POST",
                "/users/invitations/bulk",
                label="learner invitation",
                headers=auth(methodologist_token),
                json={"items": [{"email": learner_email}]},
            )
            assert len(invitation["created"]) == 1
            invite_url = str(invitation["created"][0]["invite_url"])
            token = parse_qs(urlparse(invite_url).query).get("token", [""])[0]
            if not token:
                raise RuntimeError("Invitation URL did not contain a token")
            public_invite = await request_json(
                client,
                "GET",
                f"/invitations/{token}",
                label="public invitation view",
            )
            assert public_invite["valid"] is True
            accepted = await request_json(
                client,
                "POST",
                f"/invitations/{token}/accept",
                label="invitation acceptance",
                json={
                    "first_name": "Invited",
                    "last_name": "Learner",
                    "password": password,
                },
            )
            learner_token = str(accepted["access_token"])
            learner_id = str(accepted["user_id"])
            step("learner invitation and acceptance")

            await request_json(
                client,
                "POST",
                f"/courses/{ordinary_course_id}/enrollments",
                label="manual course assignment",
                expected=(201,),
                headers=auth(methodologist_token),
                json={"user_ids": [learner_id]},
            )
            await request_json(
                client,
                "POST",
                f"/courses/{ordinary_course_id}/enrollments",
                label="idempotent manual course assignment",
                expected=(201,),
                headers=auth(methodologist_token),
                json={"user_ids": [learner_id]},
            )
            enrollments = await request_json(
                client,
                "GET",
                f"/courses/{ordinary_course_id}/enrollments",
                label="manual assignment verification",
                headers=auth(methodologist_token),
            )
            assert sum(row["user_id"] == learner_id for row in enrollments) == 1
            step("manual assignment idempotency")

            answer_key = await correct_answers(tenant_id, ordinary_course_id)
            if not answer_key:
                raise RuntimeError("Generated course has no answer key")
            lessons = [
                lesson
                for module in ordinary_preview["modules"]
                for lesson in module["lessons"]
            ]
            for lesson in lessons:
                await request_json(
                    client,
                    "PUT",
                    f"/progress/lessons/{lesson['id']}",
                    label="lesson completion",
                    headers=auth(learner_token),
                    json={"completed": True, "completion_percent": 100},
                )
                quiz_id = lesson.get("quiz_id")
                if not quiz_id:
                    continue
                learner_quiz = await request_json(
                    client,
                    "GET",
                    f"/quizzes/{quiz_id}",
                    label="learner quiz view",
                    headers=auth(learner_token),
                )
                assert all(
                    choice["is_correct"] is False
                    for question in learner_quiz["questions"]
                    for choice in question["choices"]
                )
                key = answer_key.get(str(quiz_id))
                if not key:
                    raise RuntimeError(f"No answer key for quiz {quiz_id}")
                result = await request_json(
                    client,
                    "POST",
                    f"/quizzes/{quiz_id}/submit",
                    label="quiz submission",
                    headers=auth(learner_token),
                    json={
                        "answers": [
                            {
                                "question_id": question_id,
                                "selected_choice_ids": choice_ids,
                            }
                            for question_id, choice_ids in key.items()
                        ],
                        "time_spent_seconds": 30,
                    },
                )
                assert result["passed"] is True
            step(
                "learner lessons and quizzes",
                lessons=len(lessons),
                quizzes=len(answer_key),
            )

            completion = await request_json(
                client,
                "POST",
                f"/courses/{ordinary_course_id}/complete",
                label="course completion",
                headers=auth(learner_token),
            )
            assert completion["status"] == "completed"
            certificate_number = str(completion["certificate_number"])
            verification = await request_json(
                client,
                "GET",
                f"/certificates/verify/{certificate_number}",
                label="certificate verification",
            )
            assert verification["valid"] is True
            certificates = await request_json(
                client,
                "GET",
                "/certificates",
                label="learner certificate list",
                headers=auth(learner_token),
            )
            assert any(
                item["certificate_number"] == certificate_number
                for item in certificates
            )
            await request(
                client,
                "GET",
                f"/certificates/{certificates[0]['id']}/download",
                label="certificate download",
                headers=auth(learner_token),
            )
            step("course completion and certificate")

            training_log = await request_json(
                client,
                "GET",
                f"/admin/training-log?course_id={ordinary_course_id}",
                label="training log",
                headers=auth(methodologist_token),
            )
            learner_row = next(
                row for row in training_log["items"] if row["user_id"] == learner_id
            )
            assert learner_row["computed_status"] == "completed"
            assert learner_row["progress_percent"] == 100
            assert learner_row["certificate_number"] == certificate_number
            csv_response = await request(
                client,
                "GET",
                f"/admin/training-log?course_id={ordinary_course_id}&format=csv&lang=ru",
                label="training log CSV",
                headers=auth(methodologist_token),
            )
            assert csv_response.content.startswith(b"\xef\xbb\xbf")
            csv_text = csv_response.content.decode("utf-8-sig")
            rows = list(csv.DictReader(io.StringIO(csv_text), delimiter=";"))
            assert rows
            assert "ФИО" in rows[0]
            assert "Курс" in rows[0]
            assert "Статус" in rows[0]
            assert "user_id" not in rows[0]
            step("training log JSON and Excel-compatible CSV")

            final_usage = await request_json(
                client,
                "GET",
                "/admin/trial-usage",
                label="final trial usage",
                headers=auth(admin_token),
            )
            assert final_usage["learners"]["used"] == 3
            assert final_usage["system_users"]["used"] == 2
            step(
                "final trial usage",
                learners=final_usage["learners"]["used"],
                system_users=final_usage["system_users"]["used"],
            )
        finally:
            if tenant_id:
                await cleanup_tenant(tenant_id)


async def main() -> None:
    load_env()
    if os.getenv("CONFIRM_PRODUCTION_SMOKE") != "1":
        raise RuntimeError(
            "Set CONFIRM_PRODUCTION_SMOKE=1 to create and remove a temporary production tenant"
        )
    if not GENERAL_SOURCE.exists() or not JD_SOURCE.exists():
        raise RuntimeError("Synthetic source documents are missing")
    await run_journey()


if __name__ == "__main__":
    asyncio.run(main())
