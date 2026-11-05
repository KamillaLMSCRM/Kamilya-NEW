import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.ai.v3.practical_service import practical_artifacts
from app.modules.courses.draft_review import learning_content_snapshot, read_draft_review
from app.modules.courses.source_uncertainty import (
    get_active_source_defects,
    require_current_draft_review,
    resolve_source_uncertainty,
)
from tests.unit.test_v3_editorial_draft import prepared

pytest_plugins = ("tests.unit.test_v3_practical_cycle",)


def analysis(case):
    corpus, packet, result = prepared(case)
    a = practical_artifacts(result, corpus, packet, "a" * 64)
    return {"evidence_v3": a.diagnostics, "unresolved_source_uncertainty": {"status": "review_required"}}


def resolve(value, **changes):
    args = dict(
        reason="Checked the complete draft against its source.",
        methodologist_user_id="methodologist",
        expected_content_hash="a" * 64,
        actual_content_hash="a" * 64,
        verified_revision="rev1",
        available_revisions=["rev1"],
        defect_resolutions=[
            {
                "defect_id": d["defect_id"],
                "action": "manual_verification_passed",
                "rationale": "Verified the current source and answer.",
            }
            for d in get_active_source_defects(value)
        ],
    )
    return resolve_source_uncertainty(value, **{**args, **changes})


def test_one_registry_keeps_human_history_without_rewriting_generation_evidence(case):
    source = analysis(case)
    manifest = read_draft_review(source)
    reviewed = resolve(source)
    assert read_draft_review(reviewed) == manifest
    assert "unresolved_source_uncertainty" not in reviewed
    assert source.get("unresolved_source_uncertainty")
    again = resolve(reviewed)
    assert len(again["resolutions_history"]) == 2
    assert again["source_uncertainty_resolution"]["resolved_by"] == "methodologist"


@pytest.mark.parametrize("mutation", ["content", "source", "missing", "duplicate", "extra"])
def test_stale_or_incomplete_review_does_not_clear_any_issue(case, mutation):
    source = analysis(case)
    kwargs = {}
    if mutation == "content":
        kwargs["actual_content_hash"] = "b" * 64
    elif mutation == "source":
        kwargs["available_revisions"] = ["rev2"]
    else:
        rows = [
            {
                "defect_id": d["defect_id"],
                "action": "manual_verification_passed",
                "rationale": "Checked against the current source.",
            }
            for d in get_active_source_defects(source)
        ]
        if mutation == "missing":
            rows = []
        elif mutation == "duplicate":
            rows += copy.deepcopy(rows)
        else:
            rows += [
                {
                    "defect_id": "foreign-issue",
                    "action": "manual_verification_passed",
                    "rationale": "Not a current issue.",
                }
            ]
        kwargs["defect_resolutions"] = rows
    with pytest.raises(ValueError):
        resolve(source, **kwargs)
    assert "unresolved_source_uncertainty" in source


def test_learning_hash_ignores_review_bookkeeping_but_never_content_or_sources(case):
    source = analysis(case)
    snapshot = {
        "course": {"source_analysis": source, "title": "Course", "review_status": "pending"},
        "source_documents": [{"id": "doc", "revision": "rev1"}],
        "modules": [
            {
                "lessons": [
                    {
                        "content": "Source rule.",
                        "source_validation_status": "needs_review",
                        "quizzes": [{"review_status": "needs_review", "questions": [{"key": 0}]}],
                    }
                ]
            }
        ],
    }
    base = learning_content_snapshot(snapshot)
    bookkeeping = copy.deepcopy(snapshot)
    bookkeeping["course"]["review_status"] = "approved"
    bookkeeping["modules"][0]["lessons"][0]["source_validation_status"] = "verified"
    bookkeeping["modules"][0]["lessons"][0]["quizzes"][0]["review_status"] = "approved"
    assert learning_content_snapshot(bookkeeping) == base
    for mutate in (
        lambda s: s["modules"][0]["lessons"][0].update(content="Changed rule."),
        lambda s: s["modules"][0]["lessons"][0]["quizzes"][0]["questions"][0].update(key=1),
        lambda s: s["source_documents"][0].update(revision="rev2"),
    ):
        changed = copy.deepcopy(snapshot)
        mutate(changed)
        assert learning_content_snapshot(changed) != base


@pytest.mark.asyncio
async def test_approval_rechecks_current_snapshot_after_human_resolution(case, monkeypatch):
    import app.modules.courses.source_uncertainty as module

    reviewed = resolve(analysis(case))
    current = AsyncMock(return_value="a" * 64)
    monkeypatch.setattr(module, "compute_course_content_snapshot_hash", current)
    from app.modules.courses import router

    source_lock = AsyncMock(return_value=(["rev1"], {}, []))
    monkeypatch.setattr(router, "_extract_course_source_revisions", source_lock)
    course = SimpleNamespace(source_analysis=reviewed)
    await require_current_draft_review(object(), course)
    assert source_lock.call_args.kwargs["for_update"] is True
    current.return_value = "b" * 64
    with pytest.raises(HTTPException) as error:
        await require_current_draft_review(object(), course)
    assert error.value.status_code == 409


def test_unknown_or_corrupted_manifest_cannot_fall_back_to_legacy(case):
    source = analysis(case)
    source["evidence_v3"]["draft_review"]["version"] = "unknown"
    with pytest.raises(ValueError):
        get_active_source_defects(source)


@pytest.mark.asyncio
async def test_real_resolution_routes_keep_draft_and_reject_stale_concurrent_content(case, monkeypatch):
    from uuid import uuid4

    from httpx import ASGITransport, AsyncClient

    from tests.unit.test_course_source_uncertainty_api import _build_test_app, _make_course, _make_user

    user = _make_user()
    course = _make_course(uuid4(), user.tenant_id, default_revision="rev1")
    course.source_analysis.update(analysis(case))
    history = []
    app, session = _build_test_app(course, user, history, monkeypatch)
    url = f"/courses/{course.id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        initial = await client.get(url + "/source-uncertainty")
        assert initial.status_code == 200, initial.text
        details = initial.json()
        assert details["draft_review"]["generation_status"] == "draft_prepared"
        body = {
            "reason": "Checked every lesson and answer against the source.",
            "expected_content_hash": details["content_snapshot_hash"],
            "verified_revision": details["available_revisions"][0],
            "verified_revisions": {d["document_id"]: d["authoritative_revision"] for d in details["source_documents"]},
            "defect_resolutions": [
                {
                    "defect_id": d["defect_id"],
                    "action": "manual_verification_passed",
                    "rationale": "Verified this against the original source.",
                }
                for d in details["active_defects"]
            ],
        }
        saved = await client.post(url + "/resolve-source-uncertainty", json=body)
        assert saved.status_code == 200, saved.text
        assert course.status == "draft" and course.review_status == "pending"
        current = (await client.get(url + "/source-uncertainty")).json()
        assert not current["has_active_hold"] and current["active_defects"] == []
        assert len(current["resolutions_history"]) == 1
        course.modules[0].lessons[0].content = "Content concurrently changed after the inspection."
        stale = await client.post(url + "/resolve-source-uncertainty", json=body)
        assert stale.status_code == 409
        assert len(course.source_analysis["resolutions_history"]) == 1
        changed = (await client.get(url + "/source-uncertainty")).json()
        assert changed["has_active_hold"] and changed["active_defects"]
        assert changed["content_snapshot_hash"] != details["content_snapshot_hash"]
        assert session.query_had_lock


@pytest.mark.asyncio
async def test_course_touch_invalidates_only_p30_human_approval_with_tenant_fence():
    from uuid import uuid4

    from sqlalchemy.dialects import postgresql

    from app.modules.courses.release_service import touch_course

    session = SimpleNamespace(execute=AsyncMock())
    course, tenant = uuid4(), uuid4()
    await touch_course(session, course, tenant)
    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "CASE WHEN" in sql and "ELSE courses.review_status" in sql
    assert "courses.tenant_id =" in sql and "courses.id =" in sql
    assert "p30-editorial-draft-v1" in compiled.params.values()
    assert "pending" in compiled.params.values() and tenant in compiled.params.values()
