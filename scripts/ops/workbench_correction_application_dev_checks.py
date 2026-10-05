"""Real application/SQL owners. Only original bytes/model/commit transport are synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from workbench_correction_dev_checks import BLOB, FakeLLM, fixture_facts, require
from workbench_document_dev_gate import GateBlocked, safe_schema, set_context


async def drain_concurrent(*calls, busy_type=None):
    """Never drop an owned schema while a peer application still owns locks."""
    results = await asyncio.gather(*calls, return_exceptions=True)
    outcomes = []
    failure = None
    for result in results:
        if isinstance(result, BaseException):
            if (
                busy_type is not None
                and isinstance(result, busy_type)
                and str(result) == "correction_application_busy"
            ):
                outcomes.append({"status": "FAILED", "class": type(result).__name__})
                continue
            failure = failure or result
            outcomes.append(
                {
                    "status": "FAILED",
                    "class": type(result).__name__,
                    "state": getattr(getattr(result, "orig", None), "sqlstate", None),
                }
            )
        else:
            outcomes.append({"status": "COMPLETED"})
    if failure is not None:
        failure.gate_outcomes = outcomes
        raise failure
    return results


async def release_and_drain(unlock, task, primary_error=None):
    """Cleanup failures never erase the earlier probe/application failure."""
    unlock_error = None
    try:
        await unlock
    except BaseException as exc:
        unlock_error = exc
    task_error = None
    if task is not None:
        result = (await asyncio.gather(task, return_exceptions=True))[0]
        if isinstance(result, BaseException):
            task_error = result
    if primary_error is not None:
        raise primary_error
    if task_error is not None:
        raise task_error
    if unlock_error is not None:
        raise unlock_error


async def verify_application(owner_engine, runtime_engine, schema, checks):
    from app.models.document import Document
    from app.models.registry import load_all_models
    from app.models.tenant_settings import TenantSettings
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.course_approval.models import (
        CourseApprovalRequest,
        CourseApprovalRevision,
        WorkflowAccessCredential,
        WorkflowWorkItem,
    )
    from app.modules.course_approval.service import cancel_request
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.lessons.models import ContentBlock, Lesson, Module
    from app.modules.lessons.schemas import LessonUpdate
    from app.modules.lessons.service import update_lesson
    from app.modules.methodologist_workbench import (
        correction_application as application,
    )
    from app.modules.methodologist_workbench.assignment_service import (
        WorkbenchConflict,
        WorkbenchNotFound,
    )
    from app.modules.methodologist_workbench.correction_contract import CorrectionError
    from app.modules.methodologist_workbench.correction_schemas import (
        CorrectionPreviewRequest,
    )
    from app.modules.methodologist_workbench.correction_service import (
        create_correction_preview,
    )
    from app.modules.methodologist_workbench.plan_contract import (
        ActorContext,
        ConfirmationRequest,
    )
    from app.modules.quizzes.models import Question, Quiz, QuizChoice
    from app.modules.scorm.models import ScormPackage
    from workbench_correction_application_dev_gate import TABLES, apply_0177

    load_all_models()
    q = safe_schema(schema)
    tenant, foreign, actor_id, sibling_id, foreign_id, doc_id = [
        uuid4() for _ in range(6)
    ]
    actor = ActorContext(
        tenant_id=tenant, actor_id=actor_id, active_role="methodologist"
    )
    storage = SimpleNamespace(
        get_bytes=lambda key: BLOB if key == "synthetic.md" else None
    )
    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await set_context(db, schema, tenant, actor_id)
        db.add_all(
            [
                Tenant(id=tenant, name="Application gate", slug=f"gate-{tenant.hex}"),
                Tenant(id=foreign, name="Foreign", slug=f"gate-{foreign.hex}"),
            ]
        )
        await db.flush()
        db.add_all(
            [
                User(
                    id=i,
                    tenant_id=t,
                    first_name="Synthetic",
                    last_name="Gate",
                    role="methodologist",
                    status="active",
                    is_active=True,
                )
                for i, t in (
                    (actor_id, tenant),
                    (sibling_id, tenant),
                    (foreign_id, foreign),
                )
            ]
        )
        db.add(
            TenantSettings(
                id=uuid4(), tenant_id=tenant, monthly_llm_budget_usd_cents=5000
            )
        )
        await db.flush()
        document = Document(
            id=doc_id,
            tenant_id=tenant,
            uploaded_by=actor_id,
            title="Source",
            filename="source.md",
            content_type="text/markdown",
            s3_key="synthetic.md",
            size=len(BLOB),
            content_sha256=hashlib.sha256(BLOB).hexdigest(),
            index_status="ready",
            lifecycle_status="active",
        )
        db.add(document)
        await db.flush()
        content, references = await fixture_facts(document, storage)
        await db.commit()

    async def sql(statement, params=None):
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            return await db.execute(text(statement), params or {})

    async def state():
        values = []
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            for table in TABLES + (
                "workbench_lesson_correction_plans",
                "workbench_lesson_correction_applications",
            ):
                # IDs/text never leave process-local oracle; sanitize labels only.
                result = await db.execute(
                    text(
                        f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') FROM {q}.{table} t"
                    )
                )
                values.append(result.scalar_one())
        return values

    async def scenario():
        (
            c,
            m,
            lesson_id,
            z,
            revision,
            request,
            item,
            key,
            block,
            question,
            choice,
            scorm,
            empty_revision,
        ) = [uuid4() for _ in range(13)]
        async with AsyncSession(owner_engine, expire_on_commit=False) as db:
            await set_context(db, schema, tenant, actor_id)
            db.add(
                Course(
                    id=c,
                    tenant_id=tenant,
                    title="Synthetic",
                    status="draft",
                    delivery_type="native",
                    source_document_ids=[str(doc_id)],
                    review_status="approved",
                    reviewed_by=actor_id,
                    reviewed_at=datetime.now(UTC),
                    review_comment="old",
                )
            )
            await db.flush()
            db.add(
                Module(
                    id=m, tenant_id=tenant, course_id=c, title="Module", order_index=0
                )
            )
            await db.flush()
            db.add(
                Lesson(
                    id=lesson_id,
                    tenant_id=tenant,
                    module_id=m,
                    title="Material",
                    content_type="text",
                    content="A100\nMaterial: wood",
                    source_document_ids=[str(doc_id)],
                    source_references=references,
                    source_validation_status="verified",
                    order_index=0,
                )
            )
            db.add(
                CourseApprovalRevision(
                    id=revision,
                    tenant_id=tenant,
                    course_id=c,
                    revision_number=1,
                    state="pending",
                    snapshot={"history": "fixed"},
                    snapshot_sha256="b" * 64,
                    source_fingerprint="c" * 64,
                    created_by=actor_id,
                )
            )
            db.add(
                CourseApprovalRevision(
                    id=empty_revision,
                    tenant_id=tenant,
                    course_id=c,
                    revision_number=2,
                    state="cancelled",
                    snapshot={"history": "empty"},
                    snapshot_sha256="b" * 64,
                    source_fingerprint="c" * 64,
                    created_by=actor_id,
                )
            )
            db.add(
                ContentRelease(
                    id=uuid4(),
                    tenant_id=tenant,
                    course_id=c,
                    version=1,
                    snapshot={"history": "release"},
                    snapshot_sha256="d" * 64,
                    published_by=actor_id,
                )
            )
            db.add(
                ScormPackage(
                    id=scorm,
                    tenant_id=tenant,
                    course_id=c,
                    version="scorm_1_2",
                    title="Inactive fixture",
                    entrypoint="index.html",
                    storage_key="synthetic/scorm",
                    manifest_json={},
                )
            )
            await db.flush()
            db.add(
                ContentBlock(
                    id=block,
                    lesson_id=lesson_id,
                    block_type="text",
                    content="Fixed block",
                )
            )
            db.add(
                Quiz(
                    id=z,
                    tenant_id=tenant,
                    lesson_id=lesson_id,
                    title="Quiz",
                    review_status="approved",
                    reviewed_by=actor_id,
                    reviewed_at=datetime.now(UTC),
                )
            )
            db.add(
                CourseApprovalRequest(
                    id=request,
                    tenant_id=tenant,
                    revision_id=revision,
                    requested_by=actor_id,
                    delivery_mode="personal_link",
                    outcome="pending",
                )
            )
            db.add(
                WorkflowWorkItem(
                    id=item,
                    tenant_id=tenant,
                    kind="reviewer",
                    review_revision_id=revision,
                    target_user_id=actor_id,
                    outcome="pending",
                    access_state="active",
                )
            )
            await db.flush()
            db.add(
                Question(id=question, quiz_id=z, text="Material?", type="single_choice")
            )
            db.add(
                WorkflowAccessCredential(
                    id=key,
                    tenant_id=tenant,
                    work_item_id=item,
                    reviewer_user_id=actor_id,
                    token_hash=uuid4().hex * 2,
                    pin_hash="synthetic-only",
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            await db.flush()
            db.add(
                QuizChoice(
                    id=choice, question_id=question, text="steel", is_correct=True
                )
            )
            await db.commit()
        llm = FakeLLM(content, len(references))

        async def resolver(_tenant):
            require(_tenant == tenant, "model_wrong_scope")
            return llm

        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, tenant, actor_id)
            preview = await create_correction_preview(
                db,
                actor,
                CorrectionPreviewRequest(
                    request_key=uuid4(),
                    lesson_id=lesson_id,
                    instruction="Correct material from source.",
                    locale="en",
                ),
                provider_resolver=resolver,
            )
            require(
                preview.state == "ready" and preview.fingerprint, "preview_not_ready"
            )
        return SimpleNamespace(
            course=c,
            module=m,
            lesson=lesson_id,
            quiz=z,
            revision=revision,
            request=request,
            item=item,
            key=key,
            block=block,
            question=question,
            choice=choice,
            scorm=scorm,
            empty_revision=empty_revision,
            preview=preview,
            llm=llm,
            confirmation=ConfirmationRequest(
                plan_id=preview.plan_id, revision=1, fingerprint=preview.fingerprint
            ),
        )

    async def apply(case, identity=actor, confirmation=None, session_type=AsyncSession):
        async with session_type(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, identity.tenant_id, identity.actor_id)
            return await application.apply_correction_preview(
                db, identity, confirmation or case.confirmation
            )

    async def receipt(case, identity=actor):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, identity.tenant_id, identity.actor_id)
            return await application.get_correction_application(
                db, identity, case.preview.plan_id
            )

    async def expect_refusal(case, label, *, identity=actor, confirmation=None):
        before = await state()
        try:
            await apply(case, identity, confirmation)
        except (CorrectionError, WorkbenchConflict, WorkbenchNotFound):
            pass
        else:
            raise GateBlocked(label + "_accepted")
        require(await state() == before, label + "_changed")
        checks.append(label)

    def fk_probes(fixture):
        probes = []
        for table, parent, value, seed, extra in (
            ("modules", "course_id", fixture.course, fixture.module, {}),
            ("lessons", "module_id", fixture.module, fixture.lesson, {}),
            ("content_blocks", "lesson_id", fixture.lesson, fixture.block, {}),
            ("quizzes", "lesson_id", fixture.lesson, fixture.quiz, {}),
            ("questions", "quiz_id", fixture.quiz, fixture.question, {}),
            (
                "quiz_choices",
                "question_id",
                fixture.question,
                fixture.choice,
                {},
            ),
            ("scorm_packages", "course_id", fixture.course, fixture.scorm, {}),
            (
                "course_approval_revisions",
                "course_id",
                fixture.course,
                fixture.revision,
                {"revision_number": 100},
            ),
            (
                "course_approval_requests",
                "revision_id",
                fixture.empty_revision,
                fixture.request,
                {},
            ),
            (
                "workflow_work_items",
                "review_revision_id",
                fixture.revision,
                fixture.item,
                {},
            ),
            (
                "workflow_access_credentials",
                "work_item_id",
                fixture.item,
                fixture.key,
                {
                    "token_hash": uuid4().hex * 2,
                    "revoked_at": "2000-01-01T00:00:00+00:00",
                },
            ),
        ):
            statement = f"INSERT INTO {q}.{table} SELECT (jsonb_populate_record(NULL::{q}.{table},to_jsonb(t)||CAST(:override AS jsonb))).* FROM {q}.{table} t WHERE t.id=:seed"
            params = {
                "seed": seed,
                "override": json.dumps(
                    {"id": str(uuid4()), parent: str(value), **extra}
                ),
            }
            probes.append((table, statement, params))
        return probes

    async def valid_probe_fixtures(probes):
        async with runtime_engine.connect() as rival:
            for table, statement, params in probes:
                await set_context(rival, schema, tenant, actor_id)
                result = await rival.execute(text(statement), params)
                require(result.rowcount == 1, f"probe_fixture_{table}_missing")
                await rival.rollback()

    async def fault_trigger(table, enabled):
        if enabled:
            await sql(
                f"""CREATE FUNCTION {q}.gate_fail_write() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN RAISE EXCEPTION 'synthetic fault'; END $$"""
            )
            await sql(f"REVOKE ALL ON FUNCTION {q}.gate_fail_write() FROM PUBLIC")
            await sql(
                f"CREATE TRIGGER gate_write_fault BEFORE INSERT ON {q}.{table} FOR EACH ROW EXECUTE FUNCTION {q}.gate_fail_write()"
            )
        else:
            await sql(f"DROP TRIGGER gate_write_fault ON {q}.{table}")
            await sql(f"DROP FUNCTION {q}.gate_fail_write()")

    with patch("app.core.storage.get_storage", return_value=storage):
        case = await scenario()
        await valid_probe_fixtures(fk_probes(case))
        checks.append("fk_probe_fixture_preflight")
        budget = (
            await sql(f"SELECT jsonb_agg(to_jsonb(t)) FROM {q}.tenant_llm_usage t")
        ).scalar_one()
        results = await drain_concurrent(
            apply(case), apply(case), busy_type=WorkbenchConflict
        )
        completed = [
            result for result in results if not isinstance(result, BaseException)
        ]
        require(bool(completed), "concurrent_no_completed_application")
        loaded = await receipt(case)
        require(
            all(result == loaded for result in completed)
            and await apply(case) == loaded,
            "concurrent_receipts_differ",
        )
        require(
            case.llm.calls == 1
            and budget
            == (
                await sql(f"SELECT jsonb_agg(to_jsonb(t)) FROM {q}.tenant_llm_usage t")
            ).scalar_one(),
            "apply_recharged",
        )
        actual = (
            await sql(
                f"SELECT l.content,l.source_validation_status,c.review_status,z.review_status,r.state,w.outcome,w.access_state,k.revoked_at IS NOT NULL,r.snapshot FROM {q}.lessons l JOIN {q}.modules m ON m.id=l.module_id JOIN {q}.courses c ON c.id=m.course_id JOIN {q}.quizzes z ON z.lesson_id=l.id JOIN {q}.course_approval_revisions r ON r.id=:r JOIN {q}.workflow_work_items w ON w.id=:w JOIN {q}.workflow_access_credentials k ON k.id=:k WHERE l.id=:l",
                {"r": case.revision, "w": case.item, "k": case.key, "l": case.lesson},
            )
        ).one()
        require(
            tuple(actual)
            == (
                content,
                "needs_review",
                "pending",
                "needs_review",
                "superseded",
                "superseded",
                "revoked",
                True,
                {"history": "fixed"},
            ),
            "application_state_mismatch",
        )
        count = (
            await sql(
                f"SELECT count(*) FROM {q}.audit_logs WHERE action='workbench.lesson_correction_applied' AND resource_id=:l",
                {"l": str(case.lesson)},
            )
        ).scalar_one()
        require(
            count == 1
            and (
                await sql(
                    f"SELECT count(*) FROM {q}.workbench_lesson_correction_applications WHERE plan_id=:p",
                    {"p": case.preview.plan_id},
                )
            ).scalar_one()
            == 1,
            "duplicate_application",
        )
        checks += ["apply_read_review_invalidation", "same_plan_concurrent_once"]

        # Deterministic busy path: a real owner row lock, not transport latency.
        busy_case = await scenario()
        before = await state()
        async with owner_engine.begin() as blocker:
            await set_context(blocker, schema)
            await blocker.execute(
                text(
                    f"SELECT id FROM {q}.workbench_lesson_correction_plans WHERE id=:id FOR UPDATE"
                ),
                {"id": busy_case.preview.plan_id},
            )
            try:
                await apply(busy_case)
            except WorkbenchConflict as exc:
                require(
                    str(exc) == "correction_application_busy", "busy_plan_wrong_code"
                )
                require(
                    getattr(getattr(exc.__cause__, "orig", None), "sqlstate", None)
                    == "55P03",
                    "busy_plan_wrong_state",
                )
            else:
                raise GateBlocked("busy_plan_accepted")
        require(await state() == before, "busy_plan_changed")
        try:
            await receipt(busy_case)
        except WorkbenchNotFound:
            pass
        else:
            raise GateBlocked("busy_plan_false_receipt")
        require(
            await apply(busy_case) == await receipt(busy_case),
            "busy_plan_resume_failed",
        )
        checks.append("busy_plan_rollback")
        await sql(
            f"UPDATE {q}.lessons SET content='later authorized edit' WHERE id=:l",
            {"l": case.lesson},
        )
        require(
            await apply(case) == loaded
            and (
                await sql(
                    f"SELECT content FROM {q}.lessons WHERE id=:l", {"l": case.lesson}
                )
            ).scalar_one()
            == "later authorized edit",
            "replay_overwrote",
        )
        checks.append("replay_after_later_edit")
        await expect_refusal(
            case,
            "wrong_seal_refused",
            confirmation=case.confirmation.model_copy(update={"fingerprint": "a" * 64}),
        )
        for identity, label in (
            (actor.model_copy(update={"actor_id": sibling_id}), "sibling_refused"),
            (
                ActorContext(
                    tenant_id=foreign, actor_id=foreign_id, active_role="methodologist"
                ),
                "foreign_refused",
            ),
        ):
            await expect_refusal(case, label, identity=identity)
            try:
                await receipt(case, identity)
            except WorkbenchNotFound:
                pass
            else:
                raise GateBlocked(label + "_read_accepted")
        await sql(f"UPDATE {q}.users SET role='student' WHERE id=:a", {"a": actor_id})
        await expect_refusal(case, "revoked_refused")
        await sql(
            f"UPDATE {q}.users SET role='methodologist' WHERE id=:a", {"a": actor_id}
        )
        async with runtime_engine.begin() as db:
            require(
                (
                    await db.scalar(
                        text(
                            f"SELECT count(*) FROM {q}.workbench_lesson_correction_applications"
                        )
                    )
                )
                == 0,
                "absent_context_visible",
            )
        checks.append("absent_context_refused")
        for field, value, label in (
            ("content", "changed", "stale_refused"),
            ("status", "published", "published_refused"),
        ):
            fresh = await scenario()
            table, id_value = (
                ("lessons", fresh.lesson)
                if field == "content"
                else ("courses", fresh.course)
            )
            await sql(
                f"UPDATE {q}.{table} SET {field}=:v WHERE id=:i",
                {"v": value, "i": id_value},
            )
            await expect_refusal(fresh, label)
        for table, label in (
            ("audit_logs", "audit_fault_atomic_rollback"),
            (
                "workbench_lesson_correction_applications",
                "receipt_fault_atomic_rollback",
            ),
        ):
            fresh = await scenario()
            before = await state()
            await fault_trigger(table, True)
            try:
                try:
                    await apply(fresh)
                except DBAPIError as exc:
                    require(
                        getattr(exc.orig, "sqlstate", None) == "P0001",
                        "fault_wrong_state",
                    )
                else:
                    raise GateBlocked("fault_accepted")
                require(await state() == before, "fault_partial_commit")
                checks.append(label)
            finally:
                await fault_trigger(table, False)

        class LostAckSession(AsyncSession):
            async def commit(self):
                await super().commit()
                raise ConnectionError("synthetic commit acknowledgment lost")

        fresh = await scenario()
        try:
            await apply(fresh, session_type=LostAckSession)
        except ConnectionError:
            pass
        else:
            raise GateBlocked("unknown_commit_false_success")
        recovered = await receipt(fresh)
        require(await apply(fresh) == recovered, "unknown_commit_reapply")
        checks.append("lost_commit_ack_recovery")

        fresh = await scenario()
        async with runtime_engine.begin() as db:
            await set_context(db, schema, tenant, actor_id)
            for statement, label, allowed in (
                (
                    f"UPDATE {q}.workbench_lesson_correction_applications SET fingerprint=fingerprint",
                    "receipt_acl_immutable",
                    {"42501", "P0001"},
                ),
                (
                    f"INSERT INTO {q}.workbench_lesson_correction_applications (plan_id,tenant_id,actor_id,course_id,lesson_id,revision,fingerprint,before_sha256,after_sha256) VALUES (:p,:t,:a,:c,:l,1,:f,:b,:h)",
                    "receipt_sql_guard",
                    {"P0001"},
                ),
            ):
                try:
                    async with db.begin_nested():
                        await db.execute(
                            text(statement),
                            {
                                "p": fresh.preview.plan_id,
                                "t": tenant,
                                "a": actor_id,
                                "c": fresh.course,
                                "l": fresh.lesson,
                                "f": fresh.preview.fingerprint,
                                "b": "b" * 64,
                                "h": "c" * 64,
                            },
                        )
                except DBAPIError as exc:
                    require(
                        getattr(exc.orig, "sqlstate", None) in allowed,
                        label + "_wrong_state",
                    )
                else:
                    raise GateBlocked(label + "_accepted")
                checks.append(label)

        # Cancellation holds request->revision; apply NOWAIT must refuse without
        # making a domain write, even though the unchanged preview is still ready.
        fresh = await scenario()
        async with AsyncSession(runtime_engine, expire_on_commit=False) as blocker:
            await set_context(blocker, schema, tenant, actor_id)
            await cancel_request(
                blocker, request_id=fresh.request, tenant_id=tenant, actor_id=actor_id
            )
            before = await state()
            try:
                await apply(fresh)
            except WorkbenchConflict as exc:
                require(
                    str(exc) == "correction_application_busy"
                    and getattr(getattr(exc.__cause__, "orig", None), "sqlstate", None)
                    == "55P03",
                    "approval_wait_not_nowait",
                )
            else:
                raise GateBlocked("approval_contention_accepted")
            require(await state() == before, "approval_contention_changed")
            await blocker.rollback()
        checks.append("approval_cancel_contention")

        # Barrier is an owned SQL trigger, not a mocked application collaborator.
        # Hold one advisory session lock; actual apply acquires its row locks and
        # blocks at BEFORE UPDATE. Observe its advisory wait in pg_locks first.
        fresh = await scenario()
        barrier_key = (int(schema[-8:], 16) & 0x7FFFFFFF) or 1
        ready_key = (barrier_key ^ 0x40000000) or 2
        movable = await sql(
            f"INSERT INTO {q}.modules (id,tenant_id,course_id,title,description,order_index,ai_generated) VALUES (:id,:t,:c,'Movable','',99,false) RETURNING id",
            {"id": uuid4(), "t": tenant, "c": case.course},
        )
        moving_id = movable.scalar_one()
        move_statement = f"UPDATE {q}.modules SET course_id=:c WHERE id=:i"
        await sql(
            f"CREATE FUNCTION {q}.gate_pause_lesson() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN PERFORM pg_advisory_xact_lock({ready_key}); WHILE NOT pg_try_advisory_xact_lock({barrier_key}) LOOP PERFORM pg_sleep(0.05); END LOOP; RETURN NEW; END $$"
        )
        await sql(f"REVOKE ALL ON FUNCTION {q}.gate_pause_lesson() FROM PUBLIC")
        await sql(
            f"CREATE TRIGGER gate_pause BEFORE UPDATE ON {q}.lessons FOR EACH ROW EXECUTE FUNCTION {q}.gate_pause_lesson()"
        )
        task = None
        probe_error = None
        async with owner_engine.connect() as barrier:
            await barrier.execute(
                text("SELECT pg_advisory_lock(:k)"), {"k": barrier_key}
            )
            try:
                task = asyncio.create_task(apply(fresh))
                async with asyncio.timeout(20):
                    while not await barrier.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=:k AND granted)"
                        ),
                        {"k": ready_key},
                    ):
                        if task.done():
                            await task
                            raise GateBlocked("application_barrier_not_entered")
                        await asyncio.sleep(0.05)
                async with AsyncSession(
                    runtime_engine, expire_on_commit=False
                ) as rival:
                    await set_context(rival, schema, tenant, actor_id)
                    await rival.execute(text("SET LOCAL lock_timeout='250ms'"))
                    try:
                        await update_lesson(
                            rival,
                            fresh.lesson,
                            tenant,
                            LessonUpdate(content="rival edit"),
                        )
                    except DBAPIError as exc:
                        require(
                            getattr(exc.orig, "sqlstate", None) == "55P03",
                            "direct_writer_wrong_state",
                        )
                    else:
                        raise GateBlocked("direct_writer_not_serialized")
                    await rival.rollback()
                checks.append("direct_writer_contention")
                # Clone real seeded children with fresh keys; each insertion must
                # wait on its real locked parent FK, and work once locks release.
                probes = fk_probes(fresh)
                async with runtime_engine.connect() as rival:
                    for table, statement, params in probes:
                        await rival.execute(
                            text(
                                "SELECT set_config('app.tenant_id',:tenant,true), set_config('app.user_id',:actor,true), set_config('app.is_superadmin','false',true), set_config('lock_timeout','250ms',true)"
                            ),
                            {"tenant": str(tenant), "actor": str(actor_id)},
                        )
                        try:
                            await rival.execute(text(statement), params)
                        except DBAPIError as exc:
                            require(
                                getattr(exc.orig, "sqlstate", None) == "55P03",
                                f"fk_{table}_wrong_state",
                            )
                            await rival.rollback()
                        else:
                            raise GateBlocked(f"fk_{table}_not_blocked")
                async with runtime_engine.begin() as rival:
                    await set_context(rival, schema, tenant, actor_id)
                    await rival.execute(text("SET LOCAL lock_timeout='250ms'"))
                    try:
                        await rival.execute(
                            text(move_statement), {"c": fresh.course, "i": moving_id}
                        )
                    except DBAPIError as exc:
                        require(
                            getattr(exc.orig, "sqlstate", None) == "55P03",
                            "fk_move_wrong_state",
                        )
                        await rival.rollback()
                    else:
                        raise GateBlocked("fk_move_not_blocked")
            except BaseException as exc:
                probe_error = exc
                raise
            finally:
                await release_and_drain(
                    barrier.execute(
                        text("SELECT pg_advisory_unlock(:k)"), {"k": barrier_key}
                    ),
                    task,
                    probe_error,
                )
        await sql(f"DROP TRIGGER gate_pause ON {q}.lessons")
        await sql(f"DROP FUNCTION {q}.gate_pause_lesson()")
        await valid_probe_fixtures(
            probes
            + [("module_move", move_statement, {"c": fresh.course, "i": moving_id})]
        )
        checks.append("fk_insert_move_contention")

        async with owner_engine.connect() as db:
            await set_context(db, schema)
            try:
                async with db.begin_nested():
                    await apply_0177(db, schema, "downgrade")
            except RuntimeError:
                pass
            else:
                raise GateBlocked("populated_downgrade_accepted")
        checks.append("populated_downgrade_refused")
        await sql(f"DELETE FROM {q}.workbench_lesson_correction_applications")
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            await apply_0177(db, schema, "downgrade")
            await apply_0177(db, schema)
        checks.append("empty_downgrade_reupgrade")
