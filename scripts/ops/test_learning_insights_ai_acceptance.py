"""No-network contract checks for the bounded AI-COURSE-01 wrapper."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

if "httpx" not in sys.modules:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.HTTPError = type("HTTPError", (Exception,), {})
    httpx_stub.AsyncClient = type("AsyncClient", (), {})
    sys.modules["httpx"] = httpx_stub
if "dotenv" not in sys.modules:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.dotenv_values = lambda _path: {}
    sys.modules["dotenv"] = dotenv_stub

MODULE_PATH = Path(__file__).with_name("learning_insights_ai_acceptance.py")
SPEC = importlib.util.spec_from_file_location("learning_insights_ai_acceptance", MODULE_PATH)
assert SPEC and SPEC.loader
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)

SOURCE_ID = acceptance.PREFERRED_SOURCE_DOCUMENT_ID
COURSE_ID = "11111111-1111-4111-8111-111111111111"
JOB_ID = "22222222-2222-4222-8222-222222222222"
QUIZ_ID = "33333333-3333-4333-8333-333333333333"
QUESTION_ID = "44444444-4444-4444-8444-444444444444"
CHOICE_ID = "55555555-5555-4555-8555-555555555555"
LESSON_ID = "66666666-6666-4666-8666-666666666666"
EXPECTED_RELEASE_SHA = "7" * 40


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.inventory: list[dict[str, Any]] = []
        self.jobs = {JOB_ID: {"id": JOB_ID, "status": "completed", "job_type": "course_generation", "course_id": COURSE_ID}}

    async def validate_source_download(self, token: str, document_id: str) -> None:
        assert (token, document_id) == ("method-token", SOURCE_ID)
        self.calls.append(("GET", f"/documents/{document_id}/download"))

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append((method, path))
        expected = kwargs.get("expected", (200,))
        if method == "GET" and path == "/documents/catalog?limit=100":
            return {"items": [{"id": SOURCE_ID, "title": acceptance.PREFERRED_SOURCE_TITLE, "index": {"status": "ready"}}], "page": {"has_more": False}}
        if method == "GET" and path == f"/documents/{SOURCE_ID}":
            return {"id": SOURCE_ID, "title": acceptance.PREFERRED_SOURCE_TITLE}
        if method == "GET" and path == "/courses?per_page=100":
            return list(self.inventory)
        if method == "POST" and path == "/ai/generate-course":
            assert kwargs["json_body"]["documents"] == [SOURCE_ID]
            assert kwargs['json_body']['reuse_reason'] == 'other'
            assert 'course_id' not in kwargs['json_body']
            return {"id": JOB_ID, "status": "queued", "job_type": "course_generation", "course_id": None}
        if method == "GET" and path == f"/ai/jobs/{JOB_ID}":
            return self.jobs[JOB_ID]
        if method == "GET" and path == f"/courses/{COURSE_ID}":
            if expected == (404,):
                return None
            return {"id": COURSE_ID, "tenant_id": acceptance.TENANT_ID, "ai_generated": True, "source_document_ids": [SOURCE_ID]}
        if method == "GET" and path == f"/courses/{COURSE_ID}/structure":
            return {"modules": [{"lessons": [{"id": LESSON_ID, "title": "Русский урок"}]}]}
        if method == "GET" and path == "/quizzes":
            return [{"id": QUIZ_ID, "lesson_id": LESSON_ID, "title": "Q", "pass_score": 80, "attempt_limit": 3,
                     "questions": [{"id": QUESTION_ID, "text": "Question", "type": "MCQ", "points": 1, "order_index": 0,
                                    "choices": [{"id": CHOICE_ID, "text": "Yes", "order_index": 0, "is_correct": True}]}]}]
        if method == "DELETE" and path == f"/courses/{COURSE_ID}":
            assert expected == (204,)
            return None
        raise AssertionError(f"unexpected route {method} {path}")


async def fake_health(api: Any, sha: str) -> None:
    assert sha == EXPECTED_RELEASE_SHA
    api.calls.append(("GET", "/health"))


async def fake_login(api: Any, email_name: str, password_name: str) -> str:
    assert (email_name, password_name) == acceptance.METHOD_CREDENTIAL_KEYS
    return "method-token"


async def fake_context(api: Any, token: str) -> dict[str, Any]:
    assert token == "method-token"
    return {"tenant_id": acceptance.TENANT_ID, "role": "methodologist", "tenant": None}


async def run_execute(api: FakeApi, **kwargs: Any) -> dict[str, Any]:
    original = acceptance.health, acceptance.login, acceptance.methodologist_context
    acceptance.health, acceptance.login, acceptance.methodologist_context = fake_health, fake_login, fake_context
    try:
        return await acceptance.execute(
            api,
            source_document_id=kwargs.pop("source_document_id", SOURCE_ID),
            expected_release_sha=kwargs.pop("expected_release_sha", EXPECTED_RELEASE_SHA),
            **kwargs,
        )
    finally:
        acceptance.health, acceptance.login, acceptance.methodologist_context = original


async def check_execute_preserves_source_and_restores_inventory() -> None:
    api = FakeApi()
    result = await run_execute(api)
    assert result["status"] == "PASS" and result["course_deleted"] and not result["document_deleted"]
    assert result["modules"] == result["lessons"] == result["quizzes"] == result["questions"] == result["choices"] == 1
    assert api.calls.count(("GET", f"/documents/{SOURCE_ID}/download")) == 2
    assert ("DELETE", f"/courses/{COURSE_ID}") in api.calls
    assert not any("/documents/upload" in path or (method == "DELETE" and "/documents/" in path) for method, path in api.calls)


async def check_bad_uuid_fails_before_requests() -> None:
    api = FakeApi()
    try:
        await run_execute(api, source_document_id="not-a-uuid")
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "source_document_id_missing_or_invalid"
    else:
        raise AssertionError("bad UUID was accepted")
    assert not api.calls


async def check_wrong_source_hash_fails_before_generation() -> None:
    api = FakeApi()
    async def wrong_hash(token: str, document_id: str) -> None:
        raise acceptance.AcceptanceBlocked("source_download_sha256_mismatch")
    api.validate_source_download = wrong_hash
    try:
        await run_execute(api)
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "source_download_sha256_mismatch"
    else:
        raise AssertionError("wrong source hash was accepted")
    assert ("POST", "/ai/generate-course") not in api.calls


async def check_existing_course_returned_is_never_deleted() -> None:
    api = FakeApi()
    api.inventory = [{"id": COURSE_ID}]
    try:
        await run_execute(api)
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "generated_course_preexisting"
    else:
        raise AssertionError("existing course return was accepted")
    assert ("DELETE", f"/courses/{COURSE_ID}") not in api.calls


async def check_cleanup_uncertainty_does_not_repeat_delete() -> None:
    api = FakeApi()
    original_request = api.request
    async def uncertain_delete(method: str, path: str, **kwargs: Any) -> Any:
        if method == "DELETE" and path == f"/courses/{COURSE_ID}":
            api.calls.append((method, path))
            raise RuntimeError("transport uncertain")
        return await original_request(method, path, **kwargs)
    api.request = uncertain_delete
    try:
        await run_execute(api)
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "RuntimeError" and error.evidence["cleanup_started"] is True
    else:
        raise AssertionError("uncertain cleanup was accepted")
    assert api.calls.count(("DELETE", f"/courses/{COURSE_ID}")) == 1


async def check_failed_terminal_without_course_has_no_cleanup() -> None:
    api = FakeApi()
    api.jobs[JOB_ID] = {"id": JOB_ID, "status": "failed", "job_type": "course_generation", "course_id": None}
    try:
        await run_execute(api)
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "generation_not_completed"
    else:
        raise AssertionError("failed terminal generation was accepted")
    assert not any(method == "DELETE" for method, _ in api.calls)


async def check_residual_evidence_keeps_failed_terminal_course_id() -> None:
    api = FakeApi()
    api.jobs[JOB_ID] = {"id": JOB_ID, "status": "failed", "job_type": "course_generation", "course_id": COURSE_ID}
    try:
        await run_execute(api)
    except acceptance.AcceptanceBlocked as error:
        assert str(error) == "generation_not_completed"
        assert error.evidence["generation_job_id"] == JOB_ID and error.evidence["course_id"] == COURSE_ID
        assert error.evidence["source_document_id"] == SOURCE_ID and error.evidence["original_course_ids"] == []
    else:
        raise AssertionError("failed terminal generation was accepted")
    assert not any(method == "DELETE" for method, _ in api.calls)


async def check_real_stream_hashing() -> None:
    source = b"x" * acceptance.PREFERRED_SOURCE_BYTES
    original_hash = acceptance.PREFERRED_SOURCE_SHA256
    acceptance.PREFERRED_SOURCE_SHA256 = hashlib.sha256(source).hexdigest()
    class StreamResponse:
        status_code = 200
        headers = {"Content-Length": str(len(source))}
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return None
        async def aiter_bytes(self):
            yield source[:123]
            yield source[123:]
    class Client:
        def stream(self, *_args, **_kwargs): return StreamResponse()
    try:
        await acceptance.AcceptanceApi(Client(), "https://example.invalid").validate_source_download("token", SOURCE_ID)
    finally:
        acceptance.PREFERRED_SOURCE_SHA256 = original_hash


def test_exact_two_key_loader_overrides_ambient_values() -> None:
    original_values = acceptance.dotenv_values
    original = {key: os.environ.get(key) for key in (*acceptance.METHOD_CREDENTIAL_KEYS, "UNRELATED_TEST_VALUE")}
    acceptance.dotenv_values = lambda _path: {acceptance.METHOD_CREDENTIAL_KEYS[0]: "root-email", acceptance.METHOD_CREDENTIAL_KEYS[1]: "root-password"}
    os.environ["UNRELATED_TEST_VALUE"] = "ambient-unrelated"
    try:
        acceptance.load_methodologist_credentials()
        assert os.environ["UNRELATED_TEST_VALUE"] == "ambient-unrelated"
    finally:
        acceptance.dotenv_values = original_values
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_default_is_execution_opt_in_and_upload_free() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert 'if not args.execute:' in source and '"status": "READY", "read_only": True' in source
    assert "/documents/upload" not in source and "PREFERRED_SOURCE_SHA256" in source
    assert "canonical_uuid" in source and "--source-sha256" not in source
    assert '"--expected-release-sha"' in source and "required=True" in source
    assert "manager_attention_api_acceptance" not in source


def test_login_checks_auth_tenant_and_active_role(monkeypatch) -> None:
    for key in acceptance.METHOD_CREDENTIAL_KEYS:
        monkeypatch.setenv(key, 'synthetic-test-value')
    class AuthApi:
        demo = True
        role = 'methodologist'
        async def request(self, method, path, **kwargs):
            assert (method, path) == ('POST', '/auth/login')
            return {'access_token': 'test-token', 'user': {
                'tenant_id': acceptance.TENANT_ID, 'role': self.role,
                'tenant': {'id': acceptance.TENANT_ID, 'slug': acceptance.TENANT_SLUG, 'is_demo': self.demo}}}
    api = AuthApi()
    assert asyncio.run(acceptance.login(api, *acceptance.METHOD_CREDENTIAL_KEYS)) == 'test-token'
    for demo, role in [(False, 'methodologist'), (True, 'admin')]:
        api.demo, api.role = demo, role
        try:
            asyncio.run(acceptance.login(api, *acceptance.METHOD_CREDENTIAL_KEYS))
        except acceptance.AcceptanceBlocked as exc:
            assert str(exc) == 'synthetic_tenant_contract_mismatch'
        else:
            raise AssertionError('unsafe tenant or role accepted')


def test_cancel_route_status_only_response_gets_independent_readback() -> None:
    class CancelApi:
        cancelled = False
        reads = 0
        async def request(self, method, path, **kwargs):
            if method == 'POST':
                assert path == f'/ai/jobs/{JOB_ID}/cancel'
                self.cancelled = True
                return {'status': 'cancelled'}
            assert path == f'/ai/jobs/{JOB_ID}'
            self.reads += 1
            return {'id': JOB_ID, 'job_type': 'course_generation', 'course_id': None,
                    'status': 'cancelled' if self.cancelled else 'running'}
    api = CancelApi()
    assert asyncio.run(acceptance.cancel_owned_job_on_timeout(api, 'test-token', JOB_ID)) is None
    assert api.cancelled and api.reads == 2


def test_default_main_serializes_sorted_inventory() -> None:
    original_preflight, original_load, original_client, original_argv = acceptance.preflight, acceptance.load_methodologist_credentials, acceptance.httpx.AsyncClient, sys.argv
    async def preflight_with_set(
        _api: Any,
        *,
        source_document_id: str | None,
        expected_release_sha: str,
    ) -> tuple[str, dict[str, Any]]:
        assert source_document_id == SOURCE_ID
        assert expected_release_sha == EXPECTED_RELEASE_SHA
        return "token", {"document_id": SOURCE_ID, "course_ids": sorted({COURSE_ID, "77777777-7777-4777-8777-777777777777"})}
    class Client:
        def __init__(self, **_kwargs: Any): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args: Any): return None
    acceptance.preflight, acceptance.load_methodologist_credentials, acceptance.httpx.AsyncClient = preflight_with_set, lambda: None, Client
    sys.argv = [
        str(MODULE_PATH),
        "--source-document-id",
        SOURCE_ID,
        "--expected-release-sha",
        EXPECTED_RELEASE_SHA,
    ]
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            assert acceptance.main() == 0
    finally:
        acceptance.preflight, acceptance.load_methodologist_credentials, acceptance.httpx.AsyncClient, sys.argv = original_preflight, original_load, original_client, original_argv
    payload = json.loads(output.getvalue())
    assert payload["status"] == "READY" and payload["course_ids"] == sorted(payload["course_ids"])


def test_execute_preserves_source_and_restores_inventory() -> None:
    asyncio.run(check_execute_preserves_source_and_restores_inventory())


def test_bad_uuid_fails_before_requests() -> None:
    asyncio.run(check_bad_uuid_fails_before_requests())


def test_wrong_source_hash_fails_before_generation() -> None:
    asyncio.run(check_wrong_source_hash_fails_before_generation())


def test_existing_course_returned_is_never_deleted() -> None:
    asyncio.run(check_existing_course_returned_is_never_deleted())


def test_cleanup_uncertainty_does_not_repeat_delete() -> None:
    asyncio.run(check_cleanup_uncertainty_does_not_repeat_delete())


def test_failed_terminal_without_course_has_no_cleanup() -> None:
    asyncio.run(check_failed_terminal_without_course_has_no_cleanup())


def test_residual_evidence_keeps_failed_terminal_course_id() -> None:
    asyncio.run(check_residual_evidence_keeps_failed_terminal_course_id())


def test_real_stream_hashing() -> None:
    asyncio.run(check_real_stream_hashing())


def main() -> int:
    test_default_is_execution_opt_in_and_upload_free()
    test_default_main_serializes_sorted_inventory()
    test_exact_two_key_loader_overrides_ambient_values()
    test_execute_preserves_source_and_restores_inventory()
    test_bad_uuid_fails_before_requests()
    test_wrong_source_hash_fails_before_generation()
    test_existing_course_returned_is_never_deleted()
    test_cleanup_uncertainty_does_not_repeat_delete()
    test_failed_terminal_without_course_has_no_cleanup()
    test_residual_evidence_keeps_failed_terminal_course_id()
    test_real_stream_hashing()
    print(json.dumps({"status": "PASS", "cases": 10}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
