"""Production AI smoke test.

Reads secrets from local .env, creates an isolated smoke tenant/admin in the
production DB, then exercises public production API endpoints:

- login
- JD generation from position name
- manual course/module/lesson creation
- quiz draft generation from a lesson
- document upload with ingestion
- AI course generation job + polling

The script prints only IDs/statuses and never prints credentials or API keys.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from argon2 import PasswordHasher


ROOT = Path(__file__).resolve().parents[1]
API_BASE = os.getenv("SMOKE_API_BASE", "https://kamilya-lms-api.onrender.com/api/v1")


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(f".env not found at {env_path}")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value)


async def seed_smoke_user() -> tuple[str, str, str]:
    migration_url = os.getenv("MIGRATION_DATABASE_URL")
    if migration_url:
        os.environ["DATABASE_URL"] = migration_url

    sys.path.insert(0, str(ROOT / "apps" / "api"))

    from app.core.db import async_session_factory
    from app.models.tenants import Tenant, TenantUsage
    from app.models.user_roles import UserRole
    from app.models.users import User

    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    tenant_id = uuid4()
    user_id = uuid4()
    tenant_slug = f"ai-smoke-{suffix}.kml.kz"
    email = f"admin@{tenant_slug}"
    password = f"Smoke-{suffix}-{uuid4().hex[:8]}!"

    async with async_session_factory() as session:
        tenant = Tenant(
            id=tenant_id,
            name=f"AI Smoke {suffix}",
            slug=tenant_slug,
            status="trial",
            plan="free",
            billing_contact_email=email,
            notes="Temporary prod AI smoke tenant created by scripts/smoke_ai_prod.py",
            settings={},
            is_demo=False,
        )
        session.add(tenant)
        session.add(TenantUsage(tenant_id=tenant_id))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                password_hash=PasswordHasher().hash(password),
                first_name="AI",
                last_name="Smoke",
                role="teacher",
                is_active=True,
                status="active",
            )
        )
        await session.flush()
        session.add(
            UserRole(
                id=uuid4(),
                user_id=user_id,
                tenant_id=tenant_id,
                role="teacher",
            )
        )
        await session.commit()

    print(f"seed tenant_id={tenant_id} user_id={user_id} email={email}")
    return str(tenant_id), email, password


def require_ok(resp: httpx.Response, label: str) -> dict:
    if resp.status_code >= 400:
        body = resp.text[:1000].replace("\n", " ")
        raise RuntimeError(f"{label} failed: HTTP {resp.status_code}: {body}")
    if not resp.content:
        return {}
    return resp.json()


async def run_api_smoke(email: str, password: str) -> None:
    timeout = httpx.Timeout(180.0, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        health = require_ok(await client.get(f"{API_BASE}/health"), "health")
        print(f"health status={health.get('status')}")

        login = require_ok(
            await client.post(
                f"{API_BASE}/auth/login",
                json={"email": email, "password": password},
            ),
            "login",
        )
        token = login["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("login ok")

        jd = require_ok(
            await client.post(
                f"{API_BASE}/positions/generate-jd-from-name",
                headers=headers,
                json={
                    "name": "Специалист по охране труда",
                    "department": "Производство",
                    "level": "middle",
                },
            ),
            "jd generation",
        )
        print(
            "jd ok "
            f"name_len={len(jd.get('name', ''))} "
            f"responsibilities_len={len(jd.get('responsibilities', ''))}"
        )

        course = require_ok(
            await client.post(
                f"{API_BASE}/courses",
                headers=headers,
                json={
                    "title": "AI Smoke Manual Course",
                    "description": "Manual fixture course for AI smoke quiz generation.",
                    "status": "draft",
                },
            ),
            "create course",
        )
        course_id = course["id"]

        module = require_ok(
            await client.post(
                f"{API_BASE}/courses/{course_id}/modules",
                headers=headers,
                json={"title": "Основы", "description": "Базовый модуль", "order_index": 0},
            ),
            "create module",
        )
        module_id = module["id"]

        lesson = require_ok(
            await client.post(
                f"{API_BASE}/modules/{module_id}/lessons",
                headers=headers,
                json={
                    "title": "Инструктаж перед началом смены",
                    "content_type": "text",
                    "content": (
                        "Перед началом смены сотрудник проверяет состояние рабочего места, "
                        "средства индивидуальной защиты, исправность оборудования и сообщает "
                        "руководителю о любых рисках. Нельзя приступать к работе при выявленных "
                        "неисправностях, отсутствии СИЗ или признаках опасной ситуации."
                    ),
                    "duration_seconds": 600,
                    "order_index": 0,
                },
            ),
            "create lesson",
        )
        lesson_id = lesson["id"]

        quiz = require_ok(
            await client.post(
                f"{API_BASE}/quizzes/generate",
                headers=headers,
                json={
                    "lesson_id": lesson_id,
                    "num_questions": 3,
                    "difficulty": "medium",
                    "language": "ru",
                    "guidance": "Проверить понимание запретов и порядка сообщения о рисках.",
                },
            ),
            "quiz generation",
        )
        print(f"quiz ok questions={len(quiz.get('questions', []))}")

        doc_text = (
            "Курс: безопасный вводный инструктаж для производственного персонала.\n"
            "Цель: сотрудник понимает порядок допуска к смене, проверку СИЗ, "
            "действия при обнаружении неисправностей и правила сообщения руководителю.\n"
            "Темы: осмотр рабочего места, средства индивидуальной защиты, "
            "опасные ситуации, остановка работ, регистрация инцидентов.\n"
            "Практика: разобрать три ситуации и выбрать безопасное действие."
        ).encode("utf-8")
        uploaded = require_ok(
            await client.post(
                f"{API_BASE}/documents/upload",
                headers=headers,
                files={"file": ("ai-smoke-safety.txt", doc_text, "text/plain")},
            ),
            "document upload",
        )
        doc_id = uploaded["id"]
        print(
            "document ok "
            f"doc_id={doc_id} "
            f"embedding_status={uploaded.get('embedding_status')}"
        )

        job = require_ok(
            await client.post(
                f"{API_BASE}/ai/generate-course",
                headers=headers,
                json={
                    "documents": [doc_id],
                    "target_audience": "Новые сотрудники производственного участка",
                    "num_modules": 1,
                    "language": "ru",
                    "tone": "professional",
                },
            ),
            "course generation start",
        )
        job_id = job["id"]
        print(f"ai job queued job_id={job_id}")

        final = None
        started = time.monotonic()
        while time.monotonic() - started < 720:
            await asyncio.sleep(8)
            current = require_ok(
                await client.get(f"{API_BASE}/ai/jobs/{job_id}", headers=headers),
                "course generation poll",
            )
            print(
                "ai job "
                f"status={current.get('status')} "
                f"stage={current.get('stage')} "
                f"progress={current.get('progress')}"
            )
            if current.get("status") in {"completed", "failed", "cancelled"}:
                final = current
                break

        if final is None:
            raise RuntimeError(f"AI job timed out after 720s: {job_id}")
        if final.get("status") != "completed":
            raise RuntimeError(
                f"AI job ended with status={final.get('status')} message={final.get('message')}"
            )

        generated_course_id = final.get("course_id")
        preview = require_ok(
            await client.get(
                f"{API_BASE}/courses/{generated_course_id}/preview",
                headers=headers,
            ),
            "generated course preview",
        )
        print(
            "generated course ok "
            f"course_id={generated_course_id} "
            f"modules={preview.get('modules_count')} "
            f"lessons={preview.get('lessons_count')} "
            f"quizzes={preview.get('quizzes_count')}"
        )


async def main() -> None:
    load_env()
    _, email, password = await seed_smoke_user()
    await run_api_smoke(email, password)


if __name__ == "__main__":
    asyncio.run(main())
