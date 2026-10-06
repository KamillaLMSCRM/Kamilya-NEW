"""Actual isolated SQL/services; fake external bytes and validated LLM boundary only."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from kb_rag_isolated_dev_gate import GateBlocked
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from workbench_document_dev_gate import safe_schema

BLOB = b"| Article | Material |\n| --- | --- |\n| A100 | steel |\n"


def require(condition, label):
    if not condition:
        raise GateBlocked(label)


async def fixture_facts(document, storage):
    from app.modules.ai.direct_source import build_direct_source_corpus
    from app.modules.ai.evidence_engine.application import build_evidence_source

    corpus = await build_direct_source_corpus(
        [document], tenant_id=document.tenant_id, storage=storage
    )
    facts = build_evidence_source(corpus).generation_facts
    require(bool(facts) and len(facts) <= 64, "fixture_source_missing")
    content = "\n\n".join(
        f"{fact.subject}\n{fact.attribute}: {fact.value}" for fact in facts
    )
    references = [
        {
            "fact_id": f.fact_id,
            "doc_id": str(document.id),
            "source_locator": f.source_locator,
        }
        for f in facts
    ]
    return content, references


class FakeLLM:
    def __init__(
        self,
        content,
        evidence_count,
        *,
        callback=None,
        entered=None,
        release=None,
        fails=False,
    ):
        self.content, self.evidence_count = content, evidence_count
        self.callback, self.entered, self.release, self.fails = (
            callback,
            entered,
            release,
            fails,
        )
        self.calls = 0

    async def ainvoke_validated(self, _messages, parser):
        from app.modules.ai.llm_client import ValidatedLLMResult

        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            async with asyncio.timeout(20):
                await self.release.wait()
        if self.callback:
            await self.callback()
        if self.fails:
            raise RuntimeError("synthetic_boundary_failure")
        value = parser(
            json.dumps(
                {
                    "action": "propose",
                    "content": self.content,
                    "evidence": list(range(self.evidence_count)),
                }
            )
        )
        return ValidatedLLMResult("synthetic", "gate-model", value)


async def verify_service(
    owner_engine, runtime_engine, schema, set_context, apply_migration, *, checks=None
):
    from app.models.document import Document
    from app.models.registry import load_all_models
    from app.models.tenant_settings import TenantSettings
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.course_approval.models import CourseApprovalPolicy
    from app.modules.courses.models import Course
    from app.modules.lessons.models import ContentBlock, Lesson, Module
    from app.modules.methodologist_workbench import correction_service as service
    from app.modules.methodologist_workbench.assignment_service import (
        WorkbenchConflict,
        WorkbenchNotFound,
    )
    from app.modules.methodologist_workbench.correction_contract import CorrectionError
    from app.modules.methodologist_workbench.correction_schemas import (
        CorrectionPreviewRequest,
    )
    from app.modules.methodologist_workbench.plan_contract import ActorContext
    from app.modules.quizzes.models import Question, Quiz, QuizChoice

    load_all_models()
    checks = [] if checks is None else checks
    qualified = safe_schema(schema)
    from app.core.db import Base

    async with owner_engine.connect() as connection:
        from workbench_correction_dev_gate import CLONE_TABLES

        for table in CLONE_TABLES:
            names = set(
                (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema=:s AND table_name=:t"
                        ),
                        {"s": schema, "t": table},
                    )
                ).scalars()
            )
            for column in Base.metadata.tables[table].columns:
                require(
                    column.name in names, f"clone_column_missing_{table}_{column.name}"
                )
    checks.append("cloned_neighbor_model_shape")
    tenant, foreign, owner, sibling, foreign_owner = (uuid4() for _ in range(5))
    (
        course_id,
        module_id,
        lesson_id,
        other_lesson,
        doc_id,
        block_id,
        quiz_id,
        question_id,
        choice_id,
        policy_id,
    ) = (uuid4() for _ in range(10))
    actor = ActorContext(tenant_id=tenant, actor_id=owner, active_role="methodologist")
    storage_key = f"synthetic/{doc_id}.md"
    blobs = {storage_key: BLOB}
    storage = SimpleNamespace(get_bytes=lambda key: blobs.get(key))

    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await set_context(db, schema, tenant, owner)
        db.add_all(
            [
                Tenant(id=tenant, name="Correction gate", slug=f"gate-{tenant.hex}"),
                Tenant(id=foreign, name="Foreign gate", slug=f"gate-{foreign.hex}"),
            ]
        )
        await db.flush()
        db.add_all(
            [
                User(
                    id=user_id,
                    tenant_id=at,
                    first_name="Synthetic",
                    last_name="Gate",
                    role="methodologist",
                    status="active",
                    is_active=True,
                )
                for user_id, at in (
                    (owner, tenant),
                    (sibling, tenant),
                    (foreign_owner, foreign),
                )
            ]
        )
        db.add(
            TenantSettings(
                id=uuid4(), tenant_id=tenant, monthly_llm_budget_usd_cents=5000
            )
        )
        document = Document(
            id=doc_id,
            tenant_id=tenant,
            uploaded_by=owner,
            title="Synthetic source",
            filename="source.md",
            content_type="text/markdown",
            s3_key=storage_key,
            size=len(BLOB),
            content_sha256=hashlib.sha256(BLOB).hexdigest(),
            index_status="ready",
            lifecycle_status="active",
        )
        db.add(document)
        db.add(
            Course(
                id=course_id,
                tenant_id=tenant,
                title="Synthetic course",
                status="draft",
                delivery_type="native",
                source_document_ids=[str(doc_id)],
            )
        )
        await db.flush()
        content, references = await fixture_facts(document, storage)
        db.add(
            Module(
                id=module_id,
                tenant_id=tenant,
                course_id=course_id,
                title="Synthetic module",
                order_index=0,
            )
        )
        await db.flush()
        db.add_all(
            [
                Lesson(
                    id=lesson_id,
                    tenant_id=tenant,
                    module_id=module_id,
                    title="Material",
                    content_type="text",
                    content="A100\nMaterial: wood",
                    source_document_ids=[str(doc_id)],
                    source_references=references,
                    order_index=0,
                ),
                Lesson(
                    id=other_lesson,
                    tenant_id=tenant,
                    module_id=module_id,
                    title="Neighbor",
                    content_type="text",
                    content="Neighbor v1",
                    order_index=1,
                ),
            ]
        )
        await db.flush()
        db.add(
            ContentBlock(
                id=block_id,
                lesson_id=other_lesson,
                block_type="text",
                content="Block v1",
            )
        )
        db.add(
            Quiz(id=quiz_id, tenant_id=tenant, lesson_id=other_lesson, title="Quiz v1")
        )
        db.add(
            CourseApprovalPolicy(
                id=policy_id,
                tenant_id=tenant,
                course_id=course_id,
                requires_approval=False,
                review_enabled=True,
            )
        )
        await db.flush()
        db.add(
            Question(
                id=question_id,
                quiz_id=quiz_id,
                text="Question v1",
                type="single_choice",
            )
        )
        await db.flush()
        db.add(
            QuizChoice(
                id=choice_id, question_id=question_id, text="Choice v1", is_correct=True
            )
        )
        await db.commit()
    from app.modules.lessons.schemas import ContentBlockResponse

    for value, expected in (
        (None, None),
        ("exact metadata", "exact metadata"),
        ({"section": "synthetic"}, '{"section":"synthetic"}'),
        (None, None),
    ):
        async with AsyncSession(owner_engine, expire_on_commit=False) as db:
            await set_context(db, schema, tenant, owner)
            block = await db.get(ContentBlock, block_id)
            block.metadata_ = value
            await db.commit()
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, tenant, owner)
            block = await db.get(ContentBlock, block_id)
            require(
                block.metadata_ == value
                and ContentBlockResponse.model_validate(block).metadata == expected,
                "block_metadata_roundtrip_mismatch",
            )
    checks += [
        "synthetic_source_actual_converter",
        "block_metadata_orm_response_roundtrip",
    ]
    body = CorrectionPreviewRequest(
        request_key=uuid4(),
        lesson_id=lesson_id,
        instruction="Correct material from source.",
        locale="en",
    )

    async def sql(statement, params=None):
        async with owner_engine.begin() as db:
            return await db.execute(text(statement), params or {})

    async def accounting():
        row = await sql(
            f"SELECT COALESCE(sum(cost_cents),0), COALESCE(sum(request_count),0) FROM {qualified}.tenant_llm_usage WHERE tenant_id=:t",
            {"t": tenant},
        )
        return tuple(row.one())

    async def claim_count(key):
        return (
            await sql(
                f"SELECT count(*) FROM {qualified}.workbench_lesson_correction_plans WHERE tenant_id=:t AND request_key=:k",
                {"t": tenant, "k": key},
            )
        ).scalar_one()

    async def create(request=None, llm=None):
        request = request or body.model_copy(update={"request_key": uuid4()})
        llm = llm or FakeLLM(content, len(references))

        async def resolver(_tenant):
            require(_tenant == tenant, "provider_wrong_scope")
            return llm

        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, tenant, owner)
            result = await service.create_correction_preview(
                db, actor, request, provider_resolver=resolver
            )
            await db.commit()
            return result

    async def read(plan_id, caller=actor):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await set_context(db, schema, caller.tenant_id, caller.actor_id)
            return await service.get_correction_preview(db, caller, plan_id)

    async def db_reject(
        statement, params, label, *, identity=actor, expected_states=None
    ):
        async with runtime_engine.begin() as db:
            await set_context(db, schema, identity.tenant_id, identity.actor_id)
            try:
                async with db.begin_nested():
                    await db.execute(text(statement), params)
            except DBAPIError as exc:
                code = getattr(exc.orig, "sqlstate", None)
                require(
                    code in (expected_states or {"42501", "P0001", "23514"}),
                    f"{label}_unexpected_state",
                )
            else:
                raise GateBlocked(f"{label}_accepted")
        checks.append(label)

    with patch("app.core.storage.get_storage", return_value=storage):
        llm = FakeLLM(content, len(references))
        first = await create(body, llm)
        require(
            first.state == "ready"
            and first.proposal is not None
            and first.fingerprint is not None,
            "preview_not_ready",
        )
        require(await accounting() == (10, 1), "admission_accounting_mismatch")
        require(
            (await read(first.plan_id)).fingerprint == first.fingerprint,
            "ready_read_changed",
        )
        require(
            (await create(body, llm)).plan_id == first.plan_id
            and llm.calls == 1
            and await accounting() == (10, 1),
            "replay_recharged",
        )
        checks += ["preview_ready_read", "same_key_replay_one_charge"]
        try:
            await create(
                body.model_copy(update={"instruction": "Different instruction"}), llm
            )
        except WorkbenchConflict as exc:
            require(str(exc) == "request_key_collision", "collision_wrong_error")
        else:
            raise GateBlocked("collision_accepted")
        require(llm.calls == 1 and await accounting() == (10, 1), "collision_recharged")
        checks.append("digest_collision_denied")

        entered, release = asyncio.Event(), asyncio.Event()
        concurrent = FakeLLM(content, len(references), entered=entered, release=release)
        concurrent_body = body.model_copy(update={"request_key": uuid4()})
        task = asyncio.create_task(create(concurrent_body, concurrent))
        try:
            async with asyncio.timeout(20):
                await entered.wait()
                loser = await create(concurrent_body, concurrent)
                require(loser.state == "pending", "concurrent_loser_not_pending")
                release.set()
                winner = await task
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        require(
            winner.state == "ready"
            and winner.plan_id == loser.plan_id
            and concurrent.calls == 1,
            "concurrent_duplicate_provider",
        )
        require(
            await claim_count(concurrent_body.request_key) == 1
            and await accounting() == (20, 2),
            "concurrent_duplicate_charge",
        )
        checks.append("concurrent_same_key_one_claim_charge")

        await sql(
            f"UPDATE {qualified}.tenant_settings SET monthly_llm_budget_usd_cents=0 WHERE tenant_id=:t",
            {"t": tenant},
        )
        zero_body, zero_llm = (
            body.model_copy(update={"request_key": uuid4()}),
            FakeLLM(content, len(references)),
        )
        try:
            await create(zero_body, zero_llm)
        except HTTPException as exc:
            require(exc.status_code == 429, "zero_wrong_denial")
        else:
            raise GateBlocked("zero_budget_accepted")
        require(
            zero_llm.calls == 0
            and await claim_count(zero_body.request_key) == 0
            and await accounting() == (20, 2),
            "zero_claim_not_rolled_back",
        )
        await sql(
            f"UPDATE {qualified}.tenant_settings SET monthly_llm_budget_usd_cents=5000 WHERE tenant_id=:t",
            {"t": tenant},
        )
        checks.append("zero_budget_rolls_back_claim")

        failed_llm = FakeLLM(content, len(references), fails=True)
        failed_body = body.model_copy(update={"request_key": uuid4()})
        failed = await create(failed_body, failed_llm)
        require(
            failed.state == "failed"
            and failed.error_code == "proposal_unavailable"
            and await accounting() == (20, 2),
            "failure_not_refunded",
        )
        require(
            (await create(failed_body, failed_llm)).state == "failed"
            and failed_llm.calls == 1
            and await accounting() == (20, 2),
            "failure_replay_recharged",
        )
        checks.append("failure_closure_refund_once")

        for caller, label in (
            (
                ActorContext(
                    tenant_id=tenant, actor_id=sibling, active_role="methodologist"
                ),
                "sibling_denied",
            ),
            (
                ActorContext(
                    tenant_id=foreign,
                    actor_id=foreign_owner,
                    active_role="methodologist",
                ),
                "foreign_tenant_denied",
            ),
        ):
            try:
                await read(first.plan_id, caller)
            except WorkbenchNotFound:
                pass
            else:
                raise GateBlocked(f"{label}_read_visible")
            async with runtime_engine.begin() as db:
                await set_context(db, schema, caller.tenant_id, caller.actor_id)
                require(
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM workbench_lesson_correction_plans WHERE id=:id"
                        ),
                        {"id": first.plan_id},
                    )
                    == 0,
                    f"{label}_raw_visible",
                )
                result = await db.execute(
                    text(
                        "UPDATE workbench_lesson_correction_plans SET error_code='test' WHERE id=:id"
                    ),
                    {"id": first.plan_id},
                )
                require(result.rowcount == 0, f"{label}_update_visible")
            checks.append(label)
        async with runtime_engine.begin() as db:
            await set_context(db, schema)
            require(
                await db.scalar(
                    text("SELECT count(*) FROM workbench_lesson_correction_plans")
                )
                == 0,
                "absent_context_visible",
            )
        checks.append("absent_context_denied")
        await db_reject(
            "UPDATE workbench_lesson_correction_plans SET actor_id=:a WHERE id=:id",
            {"a": sibling, "id": first.plan_id},
            "column_acl_denied",
        )
        await db_reject(
            "UPDATE workbench_lesson_correction_plans SET error_code='test' WHERE id=:id",
            {"id": first.plan_id},
            "terminal_immutable",
        )

        async def revoke():
            await sql(
                f"UPDATE {qualified}.users SET role='student' WHERE id=:id",
                {"id": owner},
            )
            pending_id = (
                await sql(
                    f"SELECT id FROM {qualified}.workbench_lesson_correction_plans WHERE tenant_id=:t AND actor_id=:a AND status='pending'",
                    {"t": tenant, "a": owner},
                )
            ).scalar_one()
            await db_reject(
                "UPDATE workbench_lesson_correction_plans SET status='ready',proposal='{}'::jsonb,fingerprint=:f WHERE id=:id",
                {"id": pending_id, "f": "a" * 64},
                "revoked_role_ready_rls_denied",
                expected_states={"42501"},
            )

        role_failed = await create(
            llm=FakeLLM(content, len(references), callback=revoke)
        )
        require(
            role_failed.state == "failed"
            and role_failed.error_code == "role_denied"
            and await accounting() == (20, 2),
            "revoked_closure_not_refunded",
        )
        try:
            await read(first.plan_id)
        except CorrectionError as exc:
            require(str(exc) == "role_denied", "revoked_read_wrong_error")
        else:
            raise GateBlocked("revoked_read_accepted")
        await sql(
            f"UPDATE {qualified}.users SET role='methodologist' WHERE id=:id",
            {"id": owner},
        )
        checks.append("revoked_role_failed_closure_read_denied")

        for table, field, value, row_id in (
            ("lessons", "content", "Neighbor v2", other_lesson),
            ("modules", "title", "Module v2", module_id),
            ("content_blocks", "content", "Block v2", block_id),
            ("quizzes", "title", "Quiz v2", quiz_id),
            ("questions", "text", "Question v2", question_id),
            ("quiz_choices", "text", "Choice v2", choice_id),
            ("documents", "index_revision", 2, doc_id),
            ("course_approval_policies", "requires_approval", True, policy_id),
        ):

            async def change(table=table, field=field, value=value, row_id=row_id):
                await sql(
                    f"UPDATE {qualified}.{table} SET {field}=:v WHERE id=:id",
                    {"v": value, "id": row_id},
                )

            stale = await create(llm=FakeLLM(content, len(references), callback=change))
            require(
                stale.state == "failed"
                and stale.error_code == "stale"
                and await accounting() == (20, 2),
                f"freshness_{table}_not_refused",
            )
            checks.append(f"freshness_{table}")
        try:
            await read(first.plan_id)
        except CorrectionError as exc:
            require(str(exc) == "stale", "stale_read_wrong_error")
        else:
            raise GateBlocked("stale_ready_read_accepted")
        checks.append("stale_ready_read_denied")

        async def corrupt_blob():
            blobs[storage_key] = BLOB.replace(b"steel", b"wood")

        corrupted = await create(
            llm=FakeLLM(content, len(references), callback=corrupt_blob)
        )
        blobs[storage_key] = BLOB
        require(
            corrupted.state == "failed"
            and corrupted.error_code == "lesson_source_unavailable"
            and await accounting() == (20, 2),
            "changed_original_not_refused",
        )
        checks.append("changed_original_blob_refused")

        async with owner_engine.begin() as connection:
            try:
                async with connection.begin_nested():
                    await connection.execute(
                        text(
                            f"UPDATE {qualified}.workbench_lesson_correction_plans SET created_at=created_at+interval '1 minute' WHERE id=:id"
                        ),
                        {"id": first.plan_id},
                    )
            except DBAPIError as exc:
                require(
                    getattr(exc.orig, "sqlstate", None) == "P0001",
                    "immutable_time_wrong_state",
                )
            else:
                raise GateBlocked("immutable_time_accepted")
        checks.append("immutable_time_trigger")
        snapshot = (
            await sql(
                f"SELECT snapshot FROM {qualified}.workbench_lesson_correction_plans WHERE id=:id",
                {"id": first.plan_id},
            )
        ).scalar_one()
        snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        pending_id, pending_key = uuid4(), uuid4()
        at = (await sql("SELECT clock_timestamp()")).scalar_one()
        expires = at + timedelta(seconds=3)
        snapshot.update(
            plan_id=str(pending_id),
            created_at=at.isoformat(),
            expires_at=expires.isoformat(),
        )
        async with runtime_engine.begin() as connection:
            await set_context(connection, schema, tenant, owner)
            await connection.execute(
                text(
                    "INSERT INTO workbench_lesson_correction_plans(id,tenant_id,actor_id,request_key,request_digest,snapshot,expires_at) VALUES(:id,:t,:a,:k,:d,CAST(:s AS jsonb),:e)"
                ),
                {
                    "id": pending_id,
                    "t": tenant,
                    "a": owner,
                    "k": pending_key,
                    "d": "b" * 64,
                    "s": json.dumps(snapshot),
                    "e": expires,
                },
            )
        await asyncio.sleep(3.2)
        await db_reject(
            "UPDATE workbench_lesson_correction_plans SET status='ready',proposal='{}'::jsonb,fingerprint=:f WHERE id=:id",
            {"id": pending_id, "f": "a" * 64},
            "expired_pending_ready_trigger_denied",
            expected_states={"P0001"},
        )

        class MonthClock:
            calls = 0

            @classmethod
            def now(cls, tz=None):
                cls.calls += 1
                at = datetime.now(UTC)
                return at if cls.calls == 1 else at.replace(day=1) + timedelta(days=40)

        month_body, month_llm = (
            body.model_copy(update={"request_key": uuid4()}),
            FakeLLM(content, len(references)),
        )
        with patch.object(service, "datetime", MonthClock):
            try:
                await create(month_body, month_llm)
            except WorkbenchConflict as exc:
                require(
                    str(exc) == "correction_accounting_pending", "month_wrong_error"
                )
            else:
                raise GateBlocked("month_crossing_accepted")
        require(
            month_llm.calls == 0
            and await claim_count(month_body.request_key) == 0
            and await accounting() == (20, 2),
            "month_guard_not_rolled_back",
        )
        checks.append("post_charge_month_guard_rollback")

        class RefundClock:
            calls = 0

            @classmethod
            def now(cls, tz=None):
                cls.calls += 1
                at = datetime.now(UTC)
                return at if cls.calls == 1 else at.replace(day=1) + timedelta(days=40)

        refund_body = body.model_copy(update={"request_key": uuid4()})

        async def crosses_refund_month():
            service.datetime = RefundClock

        original_clock = service.datetime
        try:
            await create(
                refund_body,
                FakeLLM(
                    content, len(references), callback=crosses_refund_month, fails=True
                ),
            )
        except WorkbenchConflict as exc:
            require(
                str(exc) == "correction_accounting_pending", "refund_month_wrong_error"
            )
        else:
            raise GateBlocked("refund_month_crossing_accepted")
        finally:
            service.datetime = original_clock
        persisted = (
            await sql(
                f"SELECT status FROM {qualified}.workbench_lesson_correction_plans WHERE request_key=:k",
                {"k": refund_body.request_key},
            )
        ).scalar_one()
        require(
            persisted == "pending" and await accounting() == (30, 3),
            "refund_month_rollback_lost_reservation",
        )
        checks.append("post_refund_month_guard_preserves_pending")

    async with owner_engine.begin() as connection:
        await set_context(connection, schema)
        try:
            async with connection.begin_nested():
                await apply_migration(connection, schema, "downgrade")
        except RuntimeError:
            pass
        else:
            raise GateBlocked("populated_downgrade_accepted")
        require(
            await connection.scalar(
                text(
                    f"SELECT count(*) FROM {qualified}.workbench_lesson_correction_plans"
                )
            )
            > 0,
            "downgrade_lost_rows",
        )
        await connection.execute(
            text(f"DELETE FROM {qualified}.workbench_lesson_correction_plans")
        )
        await apply_migration(connection, schema, "downgrade")
        require(
            await connection.scalar(
                text("SELECT to_regclass(:table)"),
                {"table": f"{schema}.workbench_lesson_correction_plans"},
            )
            is None,
            "empty_downgrade_failed",
        )
        await apply_migration(connection, schema)
    checks.append("populated_refusal_empty_downgrade_reupgrade")
    return checks
