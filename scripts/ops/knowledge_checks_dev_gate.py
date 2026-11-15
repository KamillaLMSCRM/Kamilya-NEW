#!/usr/bin/env python3
"""Real standalone workflow/RLS proof in an owned disposable Supabase DEV schema.

No public data is copied or changed. Reuses canonical DEV identity validation,
uses the real lms_app role, real migration and application handlers. Authentication
and UI are separately verified in deployed DEV; this gate does not claim them.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import hashlib
import json
import os
import re
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
for directory in (ROOT / "apps/api", ROOT / "scripts/ops"):
    sys.path.insert(0, str(directory))

from source_actuality_dev_gate import public_snapshot  # noqa: E402
from workbench_document_dev_gate import canonical_config  # noqa: E402

SCHEMA_RE = re.compile(r"knowledge_check_gate_[a-f0-9]{12}\Z")
MIGRATION = ROOT / "apps/api/alembic/versions/0188_standalone_knowledge_checks.py"


def require(value, code):
    if not value:
        raise RuntimeError(code)


def quoted(schema):
    require(bool(SCHEMA_RE.fullmatch(schema)), "unsafe_schema")
    return f'"{schema}"'


async def migrate(connection, schema, action):
    spec = importlib.util.spec_from_file_location("knowledge_gate_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def apply(sync):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        with Operations.context(MigrationContext.configure(sync, opts={"version_table_schema": schema})):
            getattr(module, action)()

    await connection.run_sync(apply)


def sample_content():
    questions = []
    for kind, points, keys in (("MCQ", 2, [True, False]),
                               ("multiple_choice", 3, [True, True, False]),
                               ("true_false", 5, [False, True])):
        questions.append({"id": str(uuid4()), "text": f"Synthetic {kind}", "type": kind,
                          "points": points, "explanation": "Answer explanation must remain private",
                          "choices": [{"id": str(uuid4()), "text": f"Choice {index}", "is_correct": key}
                                      for index, key in enumerate(keys)]})
    return {"title": "QA standalone knowledge check", "instructions": "Synthetic only",
            "pass_score": 80, "attempt_limit": 2, "time_limit_minutes": 1, "questions": questions}


async def run(config):
    from app.models.registry import load_all_models
    from app.modules.knowledge_checks import router as api
    from app.modules.knowledge_checks.schemas import Answer, Answers, Assign, Create, Replace, Revision

    load_all_models()
    sources = [MIGRATION, *(ROOT / "apps/api/app/modules/knowledge_checks").glob("*.py")]
    def source_hashes():
        return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    source_before = source_hashes()
    schema = "knowledge_check_gate_" + uuid4().hex[:12]
    target = quoted(schema)
    owner = create_async_engine(config["owner_url"], poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(config["runtime_url"], poolclass=NullPool, hide_parameters=True)
    factory = async_sessionmaker(runtime, expire_on_commit=False)

    @event.listens_for(runtime.sync_engine, "begin")
    def bind_schema(connection):
        connection.exec_driver_sql(f"SET LOCAL search_path TO {target},pg_catalog")

    checks = []
    stage = "initial_identity"
    cleanup = False
    neutral = False
    owned = False
    failure = None
    before = None
    tenant_a, tenant_b, author_id, learner_id, other_id = [uuid4() for _ in range(5)]
    author = SimpleNamespace(id=author_id, tenant_id=tenant_a, role="methodologist")
    student = SimpleNamespace(id=learner_id, tenant_id=tenant_a, role="student")
    stranger = SimpleNamespace(id=other_id, tenant_id=tenant_b, role="student")

    async def context(db, user):
        await db.execute(text("SELECT set_config('app.tenant_id',:tenant,true),set_config('app.user_id',:actor,true),set_config('app.is_superadmin','false',true)"),
                         {"tenant": str(user.tenant_id), "actor": str(user.id)})

    async def call(user, method, **kwargs):
        async with factory.begin() as db:
            await context(db, user)
            return await method(user=user, db=db, **kwargs)

    async def http_negative(code, user, method, **kwargs):
        try:
            await call(user, method, **kwargs)
        except HTTPException as exc:
            require(exc.status_code == code, "unexpected_http_status")
            return
        raise RuntimeError("negative_was_accepted")

    async def sql_negative(statement, parameters, user=author):
        async with factory() as db:
            try:
                await context(db, user)
                await db.execute(text(statement), parameters)
                await db.flush()
            except Exception as exc:
                state = getattr(getattr(exc, "orig", exc), "sqlstate", None)
                require(state in {"23503", "23514", "42501"}, "unexpected_sqlstate")
                await db.rollback()
                return
            await db.rollback()
            raise RuntimeError("database_negative_was_accepted")

    try:
        async with runtime.connect() as conn:
            identity = (await conn.execute(text("SELECT current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"))).one()
            require(tuple(identity) == ("lms_app", False, False), "runtime_role_mismatch")
        async with owner.begin() as conn:
            before = await public_snapshot(conn)
            require(not await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema}), "schema_collision")
            await conn.execute(text(f"CREATE SCHEMA {target}"))
            owned = True
            await conn.execute(text(f"REVOKE ALL ON SCHEMA {target} FROM PUBLIC"))
            await conn.execute(text(f"GRANT USAGE ON SCHEMA {target} TO lms_app"))
            for table in ("tenants", "users"):
                await conn.execute(text(f"CREATE TABLE {target}.{table}(LIKE public.{table} INCLUDING DEFAULTS INCLUDING CONSTRAINTS INCLUDING INDEXES)"))
                await conn.execute(text(f"REVOKE ALL ON {target}.{table} FROM PUBLIC,lms_app"))
                await conn.execute(text(f"GRANT SELECT,INSERT,UPDATE ON {target}.{table} TO lms_app"))
            await conn.execute(text(f"ALTER TABLE {target}.users ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {target}.users FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(f"CREATE POLICY gate_users_tenant ON {target}.users TO lms_app USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)"))
            # The real existing platform-actor helper is not this test's subject;
            # the owned stub rejects all exceptions. All test actors are tenant staff.
            await conn.execute(text(f"CREATE FUNCTION {target}.course_approval_platform_actor_bound(uuid,uuid) RETURNS boolean LANGUAGE sql IMMUTABLE AS 'SELECT false'"))
            stage = "migration_upgrade_downgrade_reupgrade"
            await migrate(conn, schema, "upgrade")
            await migrate(conn, schema, "downgrade")
            await migrate(conn, schema, "upgrade")
            flags = (await conn.execute(text("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname=:schema AND relname LIKE 'knowledge_%' AND relkind='r'"), {"schema": schema})).all()
            require(len(flags) == 3 and all(row[1] and row[2] for row in flags), "force_rls_missing")
            for tid in (tenant_a, tenant_b):
                await conn.execute(text(f"INSERT INTO {target}.tenants(id,name,slug,status,plan,settings) VALUES(:id,'Synthetic gate',:slug,'active','free','{{}}')"), {"id": tid, "slug": str(tid)})
            # Owner bypass is used only to seed new owned synthetic parent rows.
            for uid, tid, role in ((author_id, tenant_a, "methodologist"), (learner_id, tenant_a, "student"), (other_id, tenant_b, "student")):
                await conn.execute(text(f"INSERT INTO {target}.users(id,tenant_id,email,first_name,last_name,role,is_active,status) VALUES(:id,:tenant,:email,'Synthetic','Gate',:role,true,'active')"), {"id": uid, "tenant": tid, "email": f"{uid}@example.invalid", "role": role})
        checks.append("upgrade_empty_downgrade_reupgrade_force_rls")
        stage = "application_create_publish_assign"
        content = sample_content()
        check_id = uuid4()
        created = await call(author, api.create_check, body=Create(id=check_id, **content))
        require(created["revision"] == 1 and created["status"] == "draft", "create_bad")
        await call(author, api.publish, check_id=check_id, body=Revision(expected_revision=1))
        await http_negative(404, author, api.assign, check_id=check_id, body=Assign(expected_revision=1, user_ids=[learner_id, other_id]))
        await http_negative(404, author, api.assign, check_id=check_id, body=Assign(expected_revision=1, user_ids=[learner_id, author_id]))
        require((await call(student, api.my_assignments))["items"] == [], "partial_audience_write")
        assigned = await call(author, api.assign, check_id=check_id, body=Assign(expected_revision=1, user_ids=[learner_id]))
        assignment_id = assigned["items"][0]["id"]
        again = await call(author, api.assign, check_id=check_id, body=Assign(expected_revision=1, user_ids=[learner_id]))
        require(again["items"][0]["id"] == assignment_id, "duplicate_assignment")
        checks.append("create_publish_atomic_audience_idempotent_assignment")
        stage = "parallel_start_save_reload"
        starts = await asyncio.gather(*[call(student, api.start, assignment_id=assignment_id) for _ in range(2)])
        require(starts[0]["id"] == starts[1]["id"], "parallel_start_duplicate")
        attempt_id = starts[0]["id"]
        require("is_correct" not in json.dumps(starts[0], default=str) and "explanation" not in json.dumps(starts[0], default=str), "answer_key_leaked")
        good = [Answer(question_id=q["id"], selected_choice_ids=[c["id"] for c in q["choices"] if c["is_correct"]]) for q in content["questions"]]
        saved = await call(student, api.save_answers, attempt_id=attempt_id, body=Answers(answers=good[:1]))
        reloaded = await call(student, api.attempt_detail, attempt_id=attempt_id)
        require(saved["answers"] == reloaded["answers"], "draft_not_restored")
        await http_negative(404, stranger, api.attempt_detail, attempt_id=attempt_id)
        await http_negative(404, stranger, api.assignment_detail, assignment_id=assignment_id)
        await http_negative(422, student, api.submit, attempt_id=attempt_id, body=Answers(answers=good[:1]))
        checks.append("parallel_start_single_attempt_draft_reload_no_keys_cross_tenant")
        stage = "parallel_submit_history"
        result = await asyncio.gather(*[call(student, api.submit, attempt_id=attempt_id, body=Answers(answers=good)) for _ in range(2)])
        require(result[0]["score_percent"] == 100 and result[0]["completed_at"] == result[1]["completed_at"], "submit_not_idempotent")
        await http_negative(409, student, api.submit, attempt_id=attempt_id, body=Answers(answers=[]))
        await http_negative(409, student, api.start, assignment_id=assignment_id)
        checks.append("parallel_submit_one_terminal_result_conflicting_replay_and_pass_lock")
        stage = "new_revision_old_snapshot"
        changed = deepcopy(content)
        changed["title"] += " revision2"
        changed["questions"][0]["text"] += " changed"
        await call(author, api.replace_check, check_id=check_id, body=Replace(expected_revision=1, **changed))
        await http_negative(409, author, api.replace_check, check_id=check_id, body=Replace(expected_revision=1, **changed))
        replay = await call(author, api.create_check, body=Create(id=check_id, **content))
        require(replay["revision"] == 2 and replay["title"] == changed["title"], "create_replay_overwrote_edit")
        old = await call(student, api.attempt_detail, attempt_id=attempt_id)
        require(old["snapshot"]["title"] == content["title"] and old["score_percent"] == 100, "old_evidence_changed")
        await call(author, api.publish, check_id=check_id, body=Revision(expected_revision=2))
        newer = await call(author, api.assign, check_id=check_id, body=Assign(expected_revision=2, user_ids=[learner_id]))
        require(newer["items"][0]["id"] != assignment_id, "new_revision_overwrote_assignment")
        history = await call(author, api.results, check_id=check_id)
        require(len(history["items"]) == 2 and any(r["score_percent"] == 100 for r in history["items"]), "author_history_missing")
        checks.append("new_revision_preserves_assignment_attempt_and_author_history")
        stage = "database_invariants"
        from app.modules.knowledge_checks.service import digest
        insertion = f"INSERT INTO {target}.knowledge_check_assignments(id,tenant_id,check_id,user_id,assigned_by,revision,snapshot,snapshot_sha256) VALUES(:id,:tenant,:check,:user,:actor,2,CAST(:snapshot AS jsonb),:digest)"
        parameters = {"id": uuid4(), "tenant": tenant_a, "check": check_id,
                      "user": other_id, "actor": author_id,
                      "snapshot": json.dumps(changed), "digest": digest(changed)}
        await sql_negative(insertion, parameters)
        await sql_negative(insertion, {**parameters, "id": uuid4(), "user": author_id})
        await sql_negative(f"UPDATE {target}.knowledge_check_assignments SET id=id WHERE id=:id", {"id": assignment_id})
        await sql_negative(f"UPDATE {target}.knowledge_check_attempts SET score_percent=0 WHERE id=:id", {"id": attempt_id})
        async with factory.begin() as db:
            await context(db, author)
            deleted = await db.execute(text(f"DELETE FROM {target}.knowledge_check_attempts WHERE id=:id"), {"id": attempt_id})
            require(deleted.rowcount == 0, "ordinary_role_can_delete_result")
        await sql_negative(f"UPDATE {target}.knowledge_checks SET tenant_id=:tid WHERE id=:id", {"tid": tenant_b, "id": check_id})
        async with factory.begin() as db:
            await context(db, stranger)
            require(await db.scalar(text(f"SELECT count(*) FROM {target}.knowledge_checks")) == 0, "rls_cross_tenant_read")
        async with factory.begin() as db:
            require(await db.scalar(text(f"SELECT count(*) FROM {target}.knowledge_checks")) == 0, "rls_missing_context_read")
        checks.append("foreign_employee_role_insert_assignment_terminal_immutable_column_grants_and_runtime_rls")
        stage = "expired_attempt_saved_answers_only"
        exp_id = newer["items"][0]["id"]
        real_now = datetime.now(UTC)
        class Clock:
            @classmethod
            def now(cls, _tz):
                return real_now - timedelta(seconds=90)
        with patch.object(api, "datetime", Clock):
            expiry = await call(student, api.start, assignment_id=exp_id)
            await call(student, api.save_answers, attempt_id=expiry["id"], body=Answers(answers=good[:1]))
        expired = await call(student, api.submit, attempt_id=expiry["id"], body=Answers(answers=good))
        require(expired["status"] == "expired" and expired["score_percent"] == 20, "late_answers_accepted")
        retry = await call(student, api.start, assignment_id=exp_id)
        require(retry["number"] == 2, "retry_history_lost")
        wrong = [Answer(question_id=q["id"], selected_choice_ids=[next(c["id"] for c in q["choices"] if not c["is_correct"])]) for q in changed["questions"]]
        failed = await call(student, api.submit, attempt_id=retry["id"], body=Answers(answers=wrong))
        require(failed["score_percent"] == 0 and failed["passed"] is False, "incorrect_grade")
        await http_negative(409, student, api.start, assignment_id=exp_id)
        checks.append("expiry_grades_saved_only_retry_retained_attempt_limit")
        stage = "populated_downgrade_preserves_evidence"
        async with owner.begin() as conn:
            try:
                await migrate(conn, schema, "downgrade")
            except RuntimeError as exc:
                require("requires empty tables" in str(exc), "unexpected_downgrade_rejection")
            else:
                raise RuntimeError("populated_downgrade_accepted")
            flags = (await conn.execute(text("SELECT relforcerowsecurity FROM pg_class JOIN pg_namespace n ON n.oid=relnamespace WHERE n.nspname=:schema AND relname LIKE 'knowledge_%' AND relkind='r'"), {"schema": schema})).all()
            require(len(flags) == 3 and all(row[0] for row in flags), "downgrade_lost_force_rls")
        retained = await call(author, api.results, check_id=check_id)
        require(sum(len(item["attempts"]) for item in retained["items"]) == 3, "downgrade_lost_results")
        checks.append("populated_downgrade_rejected_force_restored_all_three_attempts_retained")
    except Exception as exc:
        original = getattr(exc, "orig", exc)
        failure = {"class": type(exc).__name__, "sqlstate": getattr(original, "sqlstate", None)}
        if isinstance(exc, RuntimeError):
            failure["code"] = str(exc)[:100]
    finally:
        if owned:
            async with owner.begin() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {target} CASCADE"))
            async with owner.connect() as conn:
                cleanup = not await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:schema)"), {"schema": schema})
                neutral = before == await public_snapshot(conn)
        await runtime.dispose()
        await owner.dispose()
    unchanged_sources = source_hashes() == source_before
    return {"status": "PASS" if failure is None and cleanup and neutral and unchanged_sources else "FAIL", "stage": stage,
            "checks": checks, "cleanup": cleanup, "public_revision_and_catalog_unchanged": neutral,
            "source_hashes": source_before, "sources_unchanged": unchanged_sources,
            "failure": failure, "proof_boundary": "real migration/RLS/application handlers; auth/UI separate; synthetic owned data only"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = canonical_config(args.env_file)
        load_dotenv(args.env_file, override=True)
        # Only settings initialization; the actual application session is injected
        # and connects to the isolated owned schema using the validated runtime URL.
        os.environ["DATABASE_URL"] = config["runtime_url"]
        result = asyncio.run(run(config))
    except Exception as exc:
        result = {"status": "FAIL", "stage": "configuration_or_cleanup", "failure": type(exc).__name__}
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
