"""Database-free contract tests for the persistent DEV QA stand helper."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from scripts.ops import dev_qa_stand as stand


def _client(*, bootstrap: bool = False, calls: list[httpx.Request] | None = None) -> stand.Client:
    seen = calls if calls is not None else []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"access_token": "token"}, request=request)

    return stand.Client(httpx.Client(transport=httpx.MockTransport(handler)), bootstrap=bootstrap)


def test_verify_client_allows_login_but_rejects_business_mutations_before_http():
    calls: list[httpx.Request] = []
    client = _client(calls=calls)

    assert client.login("qa@example.test", "password") == "token"
    assert len(calls) == 1

    forbidden = [
        ("POST", "/quizzes/quiz-1/submit"),
        ("POST", "/admin/super/tenants"),
        ("POST", "/users/user-1/reset-password"),
        ("DELETE", "/courses/course-1"),
    ]
    for method, path in forbidden:
        with pytest.raises(stand.StandError, match="verify_mutation_forbidden"):
            client.request(method, path, "token")

    assert len(calls) == 1, "verify-mode guard must fail before making any forbidden request"


def test_main_configures_expected_origin_header_in_http_client_source():
    source = Path(stand.__file__).read_text(encoding="utf-8")
    assert 'headers={"Origin": ORIGIN' in source
    assert stand.ORIGIN == "https://kamilya-lms-dev.vercel.app"


def _valid_manifest() -> dict[str, object]:
    return {
        "schema": stand.MARKER,
        "slug": stand.SLUG,
        "status": "READY",
        "tenant_id": "tenant-1",
        "users": {"methodologist": "method-1", "student": "student-1"},
        "courses": [
            {"course_id": "course-1", "attempt_ids": ["attempt-1"]},
            {"course_id": "course-2", "attempt_ids": ["attempt-2", "attempt-3"]},
        ],
    }


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda state: state.update(schema="WRONG"), "manifest_identity_drift"),
        (lambda state: state.update(status="PARTIAL"), "stand_missing_or_partial"),
        (lambda state: state.update(courses=state["courses"][:1]), "manifest_course_count_drift"),
        (lambda state: state["courses"].__setitem__(1, {"course_id": "course-1", "attempt_ids": ["a", "b"]}), "manifest_duplicate_courses"),
        (lambda state: state["courses"].__setitem__(0, {"course_id": "course-1", "attempt_ids": []}), "manifest_attempt_count_drift"),
    ],
)
def test_validate_manifest_rejects_identity_partial_count_and_duplicate_drift(mutation, code):
    state = _valid_manifest()
    mutation(state)
    with pytest.raises(stand.StandError, match=code):
        stand.validate_manifest(state)


def test_validate_manifest_accepts_complete_identity_and_attempt_counts():
    stand.validate_manifest(_valid_manifest())


def test_bootstrap_refuses_existing_manifest_before_login_or_external_request(tmp_path):
    manifest = tmp_path / "kamilya-dev-qa.json"
    manifest.write_text("{}", encoding="utf-8")

    class NoLoginClient:
        def login(self, *args, **kwargs):  # pragma: no cover - assertion is the contract
            raise AssertionError("login must not be attempted")

    with pytest.raises(stand.StandError, match="manifest_exists_bootstrap_forbidden"):
        stand.bootstrap(NoLoginClient(), {}, manifest, "a" * 40)


def test_tenant_and_user_identity_fail_closed_on_drift():
    state = {"tenant_id": "tenant-1", "users": {"student": "student-1"}}
    tenant = {
        "id": "tenant-1",
        "slug": stand.SLUG,
        "is_demo": True,
        "is_financial_organization": False,
        "notes": stand.MARKER,
        "status": "active",
    }
    stand.tenant_identity(tenant, state)
    tenant["slug"] = "other"
    with pytest.raises(stand.StandError, match="tenant_identity_drift"):
        stand.tenant_identity(tenant, state)

    class UserClient:
        def request(self, *args, **kwargs):
            return {"id": "student-1", "tenant_id": "wrong", "role": "student", "email": stand.EMAILS["student"], "is_active": True}

    with pytest.raises(stand.StandError, match="user_identity_drift"):
        stand.user_identity(UserClient(), "token", state, "student")
