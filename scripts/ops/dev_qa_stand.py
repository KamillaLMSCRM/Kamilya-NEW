"""One-time DEV QA bootstrap and repeatable, business-data-read-only verification.

Never repairs, deletes, recreates or replenishes a stand automatically.
Credentials remain process-local in the canonical env; evidence contains IDs only.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://kamilya-lms-api.onrender.com/api/v1"
ORIGIN = "https://kamilya-lms-dev.vercel.app"
SLUG = "kamilya-dev-qa"
MARKER = "KAMILYA_PERSISTENT_DEV_QA_V1"
APPROVAL_ID = "QA-STAND-20260930"
EMAILS = {"methodologist": "methodologist@kamilya-dev-qa.example.com", "student": "learner@kamilya-dev-qa.example.com"}
DEFAULT_MANIFEST = ROOT / "docs/testing/fixtures/kamilya-dev-qa.json"
ENV = Path(r"C:\Kamilya New\Kamilya-NEW\.env")
sys.path.insert(0, str(ROOT))


class StandError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise StandError(code)


class Client:
    def __init__(self, http: httpx.Client, *, bootstrap: bool = False):
        self.http = http
        self.bootstrap = bootstrap

    def request(self, method: str, path: str, token: str | None = None, *, status: int = 200,
                raw: bool = False, **kwargs: Any) -> Any:
        # Auth creates normal login/session audit records, never business fixtures.
        require(method == "GET" or (method == "POST" and path == "/auth/login") or self.bootstrap, "verify_mutation_forbidden")
        require(not path.startswith(("http", "//")), "absolute_path_forbidden")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.http.request(method, BASE + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise StandError(f"network_{type(exc).__name__}:{method}:{path.split('?')[0]}") from None
        if response.status_code != status:
            code = ""
            try:
                detail = response.json().get("detail")
                if isinstance(detail, dict) and isinstance(detail.get("code"), str):
                    code = ":" + detail["code"][:80]
            except (ValueError, AttributeError):
                pass
            raise StandError(f"http_{response.status_code}:{method}:{path.split('?')[0]}{code}")
        return response.text if raw else response.json()

    def login(self, email: str, password: str) -> str:
        return str(self.request("POST", "/auth/login", json={"email": email, "password": password})["access_token"])


def persist(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def tenant_identity(tenant: dict[str, Any], state: dict[str, Any]) -> None:
    require(tenant["id"] == state["tenant_id"] and tenant["slug"] == SLUG, "tenant_identity_drift")
    require(tenant["is_demo"] is False and not tenant["is_financial_organization"], "tenant_classification_drift")
    require(tenant["notes"] == MARKER and tenant["status"] == "active", "tenant_marker_or_status_drift")


def user_identity(client: Client, token: str, state: dict[str, Any], role: str) -> dict[str, Any]:
    user = client.request("GET", "/users/me", token)
    require(user["id"] == state["users"][role] and user["tenant_id"] == state["tenant_id"], "user_identity_drift")
    require(user["role"] == role and user["email"] == EMAILS[role] and user["is_active"], "user_role_drift")
    return user


def validate_manifest(state: dict[str, Any]) -> None:
    require(state.get("schema") == MARKER and state.get("slug") == SLUG, "manifest_identity_drift")
    require(state.get("status") == "READY" and bool(state.get("tenant_id")), "stand_missing_or_partial")
    require(set(state.get("users", {})) == {"methodologist", "student"}, "manifest_user_drift")
    require(len(state.get("courses", [])) == 2, "manifest_course_count_drift")
    require(len({c["course_id"] for c in state["courses"]}) == 2, "manifest_duplicate_courses")
    for n, course in enumerate(state["courses"]):
        require(len(course.get("attempt_ids", [])) == n + 1, "manifest_attempt_count_drift")


async def database_readback(values: dict[str, Any], state: dict[str, Any] | None = None,
                            *, expected_revision: str = "0168") -> None:
    """Canonical Supabase runtime role, one connection, READ ONLY transaction."""
    require(expected_revision in {"0168", "0169", "0172", "0173", "0174"}, "unsupported_qa_schema_revision")
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from scripts.ops.kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

    url = normalize_database_url(values.get("DATABASE_URL") or "")
    require(same_supabase_project(url, values.get("SUPABASE_URL") or ""), "canonical_supabase_identity_mismatch")
    require((make_url(url).username or "").split(".")[0] == "lms_app", "runtime_role_required")
    engine = create_async_engine(url, poolclass=NullPool, echo=False, hide_parameters=True,
                                 connect_args={"timeout": 12, "command_timeout": 15})
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            role = (await conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
            require(not role.rolsuper and not role.rolbypassrls, "unsafe_runtime_role")
            revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
            require(revision == [expected_revision], "dev_schema_revision_mismatch")
            if state is None:
                return
            tenant_id = UUID(state["tenant_id"])
            await conn.execute(text("SELECT set_current_tenant(:tid)"), {"tid": str(tenant_id)})
            tenant = (await conn.execute(text(
                "SELECT id,slug,is_demo,is_financial_organization,notes,status FROM tenants WHERE id=:tid"
            ), {"tid": tenant_id})).mappings().one()
            tenant_identity({**dict(tenant), "id": str(tenant["id"])}, state)
            for table, expected in [("users", 2), ("courses", 2), ("enrollments", 2)]:
                # Fixed, code-owned table names; include archived/history rows.
                count = await conn.scalar(text(f"SELECT count(*) FROM {table} WHERE tenant_id=:tid"), {"tid": tenant_id})
                require(count == expected, f"stand_total_{table}_drift")
            policies = (await conn.execute(text(
                "SELECT enrollment_id,user_id,delivery_mode,due_at FROM enrollment_access_policies WHERE tenant_id=:tid"
            ), {"tid": tenant_id})).mappings().all()
            require(len(policies) == 2, "access_policy_count_drift")
            by_id = {str(p["enrollment_id"]): p for p in policies}
            for entry in state["courses"]:
                require(entry["enrollment_id"] in by_id, "access_policy_identity_drift")
                policy = by_id[entry["enrollment_id"]]
                require(str(policy["user_id"]) == state["users"]["student"] and policy["delivery_mode"] == "personal_link", "delivery_mode_drift")
                require(policy["due_at"] == datetime.fromisoformat(entry["due_at"]), "policy_deadline_drift")
    finally:
        await engine.dispose()


def bootstrap(client: Client, values: dict[str, Any], manifest: Path, sha: str) -> dict[str, Any]:
    require(not manifest.exists(), "manifest_exists_bootstrap_forbidden")
    super_token = client.login(values["SUPERADMIN_EMAIL"], values["SUPERADMIN_PASSWORD"])
    listing = client.request("GET", "/admin/super/tenants", super_token, params={"search": SLUG, "limit": 100})
    require(not [t for t in listing["tenants"] if t["slug"] == SLUG], "tenant_exists_without_manifest_stop")
    tenant = client.request("POST", "/admin/super/tenants", super_token, status=201, json={
        "name": "Kamilya DEV QA — синтетические данные", "slug": SLUG, "plan": "free", "status": "active",
        "is_demo": False, "is_financial_organization": False, "max_users": 2,
        "max_courses_per_month": 2, "notes": MARKER})["tenant"]
    state: dict[str, Any] = {"schema": MARKER, "slug": SLUG, "tenant_id": tenant["id"],
                            "bootstrap_sha": sha, "status": "PARTIAL", "users": {}, "courses": []}
    persist(manifest, state)  # Retain exact ownership even if a later step fails.
    tenant_identity(client.request("GET", f"/admin/super/tenants/{tenant['id']}", super_token), state)
    method = client.request("POST", f"/admin/super/tenants/{tenant['id']}/admins", super_token, status=201,
                            json={"email": EMAILS["methodologist"], "first_name": "QA", "last_name": "Методолог",
                                  "role": "methodologist", "send_invite": False})
    state["users"]["methodologist"] = method["id"]
    persist(manifest, state)
    admin_token = client.request("POST", f"/admin/super/tenants/{tenant['id']}/impersonate", super_token,
                                 json={"role": "admin"})["access_token"]
    password = values["DEV_QA_METHODOLOGIST_PASSWORD"]
    client.request("POST", f"/users/{method['id']}/reset-password", admin_token, json={"new_password": password})
    method_token = client.login(EMAILS["methodologist"], password)
    user_identity(client, method_token, state, "methodologist")
    require(client.request("GET", "/positions", method_token) == [], "bootstrap_existing_positions")
    require(client.request("GET", "/courses", method_token) == [], "bootstrap_existing_courses")
    staff = client.request("POST", "/admin/staff/manual", method_token, status=201, json={
        "personnel_number": "QA-DAILY-001", "first_name": "QA", "last_name": "Ученик",
        "position": "QA без автоназначений", "email": EMAILS["student"]})
    require(staff["created"] == 1 and staff["updated"] == 0 and staff["affected_user_count"] == 1, "staff_creation_drift")
    users = client.request("GET", "/users", method_token, params={"include_students": "true", "per_page": 500})
    require(users["total"] == 2, "bootstrap_user_count_drift")
    learner = [u for u in users["users"] if u["email"] == EMAILS["student"]]
    require(len(learner) == 1 and learner[0]["role"] == "student", "learner_identity_drift")
    state["users"]["student"] = learner[0]["id"]
    state["position_id"] = learner[0]["position_id"]
    persist(manifest, state)
    positions = client.request("GET", "/positions", method_token)
    require(len(positions) == 1 and positions[0]["course_ids"] == [], "position_rules_not_empty")
    client.request("POST", f"/users/{learner[0]['id']}/reset-password", admin_token, json={"new_password": password})
    learner_token = client.login(EMAILS["student"], password)
    user_identity(client, learner_token, state, "student")
    for n, title in enumerate(["QA: можно повторить", "QA: попытки закончились"]):
        course = client.request("POST", "/courses", method_token, status=201, json={
            "title": title, "description": "Постоянный синтетический QA-сценарий. Не отправлять ответы при обычном smoke.", "status": "draft"})
        entry: dict[str, Any] = {"course_id": course["id"], "title": title, "attempt_ids": []}
        state["courses"].append(entry)
        persist(manifest, state)
        module = client.request("POST", f"/courses/{course['id']}/modules", method_token, status=201, json={"title": "Учебный шаг"})
        lesson = client.request("POST", f"/modules/{module['id']}/lessons", method_token, status=201, json={
            "title": "QA урок", "content_type": "text", "content": "Проверка нужна, чтобы подтвердить результат обучения."})
        quiz = client.request("POST", "/quizzes", method_token, status=201, json={
            "lesson_id": lesson["id"], "title": "QA проверка", "pass_score": 80, "attempt_limit": 2})
        quiz = client.request("POST", f"/quizzes/{quiz['id']}/questions", method_token, status=201, json={
            "text": "Что нужно сделать?", "type": "single_choice", "choices": [
                {"text": "Проверить результат", "is_correct": True, "order_index": 0},
                {"text": "Пропустить проверку", "is_correct": False, "order_index": 1}]})
        entry.update(lesson_id=lesson["id"], quiz_id=quiz["id"])
        persist(manifest, state)
        client.request("POST", f"/courses/{course['id']}/publish", method_token)
        entry["due_at"] = (datetime.now(UTC) + timedelta(days=7 * (n + 1))).isoformat()
        access = client.request("POST", f"/courses/{course['id']}/personal-link-enrollment", method_token, status=201,
                                json={"user_id": learner[0]["id"], "due_at": entry["due_at"]})
        require(access["delivery_mode"] == "personal_link", "bootstrap_delivery_mode_drift")
        entry["enrollment_id"] = access["enrollment_id"]
        persist(manifest, state)  # Do not preserve access URL or PIN.
        question = quiz["questions"][0]
        wrong = next(c["id"] for c in question["choices"] if not c["is_correct"])
        for _ in range(n + 1):
            attempt = client.request("POST", f"/quizzes/{quiz['id']}/submit", learner_token, json={
                "answers": [{"question_id": question["id"], "selected_choice_ids": [wrong]}], "time_spent_seconds": 3})
            require(not attempt["passed"] and attempt["attempt"]["enrollment_id"] == entry["enrollment_id"], "seed_attempt_drift")
            entry["attempt_ids"].append(attempt["attempt"]["id"])
            persist(manifest, state)
    state["status"] = "READY"
    persist(manifest, state)
    return state


def verify(client: Client, values: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    validate_manifest(state)
    password = values["DEV_QA_METHODOLOGIST_PASSWORD"]
    method = client.login(EMAILS["methodologist"], password)
    learner = client.login(EMAILS["student"], password)
    user_identity(client, method, state, "methodologist")
    user_identity(client, learner, state, "student")
    users = client.request("GET", "/users", method, params={"include_students": "true", "per_page": 500})
    require(users["total"] == 2 and {u["id"] for u in users["users"]} == set(state["users"].values()), "stand_user_count_drift")
    positions = client.request("GET", "/positions", method)
    require(len(positions) == 1 and positions[0]["id"] == state["position_id"] and positions[0]["course_ids"] == [], "stand_position_rules_drift")
    courses = client.request("GET", "/courses", method, params={"per_page": 100})
    require({c["id"] for c in courses} == {c["course_id"] for c in state["courses"]}, "stand_course_count_drift")
    dashboard = client.request("GET", "/student/dashboard", learner)
    require(dashboard["user_id"] == state["users"]["student"] and dashboard["total_courses"] == 2, "learner_dashboard_drift")
    rows = {c["enrollment_id"]: c for c in dashboard["enrolled_courses"]}
    require(set(rows) == {c["enrollment_id"] for c in state["courses"]}, "learner_assignment_drift")
    for n, entry in enumerate(state["courses"]):
        course = next(c for c in courses if c["id"] == entry["course_id"])
        require(course["tenant_id"] == state["tenant_id"] and course["status"] == "published" and course["title"] == entry["title"], "course_identity_drift")
        enrollments = client.request("GET", f"/courses/{entry['course_id']}/enrollments", method)
        require(len(enrollments) == 1 and enrollments[0]["id"] == entry["enrollment_id"] and enrollments[0]["user_id"] == state["users"]["student"], "enrollment_identity_drift")
        require(enrollments[0].get("notification_attempt_count", 0) == 0, "unexpected_notification_attempt")
        quiz = client.request("GET", f"/quizzes/{entry['quiz_id']}", method)
        require(quiz["lesson_id"] == entry["lesson_id"] and quiz["attempt_limit"] == 2, "quiz_identity_drift")
        attempts = client.request("GET", f"/quizzes/{entry['quiz_id']}/attempts", learner)
        require(len(attempts) == n + 1 and {a["id"] for a in attempts} == set(entry["attempt_ids"]), "attempt_count_drift")
        require(all(not a["passed"] and a["enrollment_id"] == entry["enrollment_id"] for a in attempts), "attempt_outcome_drift")
        row = rows[entry["enrollment_id"]]
        require(row["assignment_source"] == "manual" and row["can_resume"], "assignment_source_or_resume_drift")
        require(datetime.fromisoformat(row["assignment_due_at"]) == datetime.fromisoformat(entry["due_at"]), "assignment_deadline_drift")
        require(row["resume_href"] == f"/courses/{entry['course_id']}?lessonId={entry['lesson_id']}", "canonical_resume_drift")
    summary = client.request("GET", "/admin/training-log/summary", method)
    require(summary["total"] == 2 and summary["failed_current"] == 2 and summary["exhausted_attempts"] == 1, "summary_drift")
    for status, expected in [("failed", state["courses"]), ("exhausted", state["courses"][1:])]:
        params = {"assessment_status": status}
        page = client.request("GET", "/admin/training-log", method, params=params)
        filtered = client.request("GET", "/admin/training-log/summary", method, params=params)
        require(page["total"] == len(expected) and filtered["total"] == len(expected), "filter_count_drift")
        require({r["enrollment_id"] for r in page["items"]} == {e["enrollment_id"] for e in expected}, "filter_identity_drift")
        exported = client.request("GET", "/admin/training-log", method, raw=True, params={**params, "format": "csv"})
        csv_rows = list(csv.reader(io.StringIO(exported.lstrip("\ufeff"))))
        require(len(csv_rows) == len(expected) + 1, "csv_filter_count_drift")
    actions = client.request("GET", "/admin/learning-actions", method)
    require(actions["actions"] == [], "unexpected_persistent_action_records")
    return {"status": "PASS", "tenant_id": state["tenant_id"], "users": 2, "courses": 2, "assignments": 2,
            "failed": 2, "exhausted": 1, "verification_business_mutations": 0, "auth_session_audit_only": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["bootstrap", "verify"])
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-revision", choices=["0168", "0169", "0172", "0173", "0174"], default="0168")
    parser.add_argument("--confirm-bootstrap")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    require(len(args.expected_sha) == 40 and all(c in "0123456789abcdef" for c in args.expected_sha), "exact_sha_required")
    if args.mode == "bootstrap":
        require(args.expected_revision == "0168", "bootstrap_schema_contract_unchanged")
        require(args.confirm_bootstrap == APPROVAL_ID, "bootstrap_owner_confirmation_required")
    values = dict(dotenv_values(ENV))
    required = ["DEV_QA_METHODOLOGIST_PASSWORD"]
    if args.mode == "bootstrap":
        required += ["SUPERADMIN_EMAIL", "SUPERADMIN_PASSWORD"]
    require(all(values.get(k) for k in required), "canonical_credentials_missing")
    result: dict[str, Any] = {"mode": args.mode, "expected_sha": args.expected_sha,
                              "expected_revision": args.expected_revision, "status": "STOP"}
    try:
        with httpx.Client(timeout=httpx.Timeout(90, connect=30), follow_redirects=False,
                          headers={"Origin": ORIGIN, "User-Agent": "Kamilya-DEV-permanent-QA/1"}) as http:
            client = Client(http, bootstrap=args.mode == "bootstrap")
            health = client.request("GET", "/health")
            require(health.get("deployment_environment") == "render-development" and health.get("release_sha") == args.expected_sha, "runtime_identity_mismatch")
            asyncio.run(database_readback(values, expected_revision=args.expected_revision))
            state = bootstrap(client, values, args.manifest, args.expected_sha) if args.mode == "bootstrap" else json.loads(args.manifest.read_text(encoding="utf-8"))
            validate_manifest(state)
            asyncio.run(database_readback(values, state, expected_revision=args.expected_revision))
            # Even bootstrap acceptance now uses the mutation-protected client.
            result.update(verify(Client(http), values, state))
    except Exception as exc:
        # Never serialize transport/SQL exceptions containing connection details.
        result["error"] = str(exc) if isinstance(exc, StandError) else type(exc).__name__
    result["bootstrap_business_mutations_authorized"] = args.mode == "bootstrap"
    result["at"] = datetime.now(UTC).isoformat()
    persist(args.evidence, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
