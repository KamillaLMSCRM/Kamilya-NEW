"""Real SQL/service lifecycle proof. External bytes/model/ack transport are fake.

Historical fixtures use owner-only trigger disabling in the disposable schema;
every runtime check runs with guards enabled. No public object is altered.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from workbench_correction_dev_checks import BLOB, FakeLLM, fixture_facts, require
from workbench_document_dev_gate import safe_schema, set_context


async def verify_lifecycle(owner_engine, runtime_engine, schema, checks):
    from app.models.document import Document
    from app.models.registry import load_all_models
    from app.models.tenant_settings import TenantSettings
    from app.models.tenants import Tenant
    from app.models.users import User
    from app.modules.courses.models import Course
    from app.modules.courses.release_models import ContentRelease
    from app.modules.lessons.models import Lesson, Module
    from app.modules.methodologist_workbench import (
        correction_application as application,
    )
    from app.modules.methodologist_workbench import correction_service as service
    from app.modules.methodologist_workbench.assignment_service import WorkbenchNotFound
    from app.modules.methodologist_workbench.correction_schemas import (
        CorrectionPreviewRequest,
    )
    from app.modules.methodologist_workbench.plan_contract import (
        ActorContext,
        ConfirmationRequest,
    )
    from workbench_correction_application_dev_gate import TABLES
    from workbench_correction_lifecycle_dev_gate import apply_0178

    load_all_models()
    q = safe_schema(schema)
    plans = f"{q}.workbench_lesson_correction_plans"
    ledger = f"{q}.workbench_lesson_correction_accounting"
    receipts = f"{q}.workbench_lesson_correction_applications"
    maintain = f"{q}.maintain_workbench_lesson_corrections"
    tenant, foreign, user, sibling, other, doc_id, course, module, lesson = [uuid4() for _ in range(9)]
    actor = ActorContext(tenant_id=tenant, actor_id=user, active_role="methodologist")
    storage = SimpleNamespace(get_bytes=lambda key: BLOB if key == "synthetic.md" else None)

    async def sql(statement, params=None):
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            return await db.execute(text(statement), params or {})

    async def context(db, at=tenant, who=user, *, superadmin=False):
        await set_context(db, schema, at, who)
        if superadmin:
            await db.execute(text("SELECT set_config('app.is_superadmin','true',true)"))

    async def state(tables=tuple(table for table in TABLES if table != "tenant_llm_usage")):
        values = []
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            for table in tables:
                values.append((await db.execute(text(
                    f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]') FROM {q}.{table} t"
                ))).scalar_one())
        return values

    async def denied(statement, params=None, *, at=tenant, who=user, superadmin=False, absent=False, code=None):
        async with runtime_engine.connect() as db:
            if not absent:
                await context(db, at, who, superadmin=superadmin)
            try:
                await db.execute(text(statement), params or {})
            except DBAPIError as exc:
                actual = getattr(exc.orig, "sqlstate", None)
                require(code is None or actual == code, "denial_state_mismatch")
            else:
                require(False, "expected_sql_denial")
            finally:
                await db.rollback()

    async with AsyncSession(owner_engine, expire_on_commit=False) as db:
        await context(db)
        db.add_all([Tenant(id=t, name="Synthetic lifecycle", slug=f"gate-{t.hex}") for t in (tenant, foreign)])
        await db.flush()
        db.add_all([User(id=u, tenant_id=t, first_name="Synthetic", last_name="Gate", role="methodologist", status="active", is_active=True) for u, t in ((user, tenant), (sibling, tenant), (other, foreign))])
        db.add(TenantSettings(id=uuid4(), tenant_id=tenant, monthly_llm_budget_usd_cents=5000))
        await db.flush()
        document = Document(id=doc_id, tenant_id=tenant, uploaded_by=user, title="Source", filename="source.md", content_type="text/markdown", s3_key="synthetic.md", size=len(BLOB), content_sha256=hashlib.sha256(BLOB).hexdigest(), index_status="ready", lifecycle_status="active")
        db.add(document)
        db.add(Course(id=course, tenant_id=tenant, title="Synthetic", status="draft", delivery_type="native", source_document_ids=[str(doc_id)]))
        await db.flush()
        content, references = await fixture_facts(document, storage)
        db.add(Module(id=module, tenant_id=tenant, course_id=course, title="Module", order_index=0))
        await db.flush()
        db.add(Lesson(id=lesson, tenant_id=tenant, module_id=module, title="Material", content_type="text", content="A100\nMaterial: wood", source_document_ids=[str(doc_id)], source_references=references, source_validation_status="verified", order_index=0))
        db.add(ContentRelease(id=uuid4(), tenant_id=tenant, course_id=course, version=1, snapshot={"history": "fixed"}, snapshot_sha256="d" * 64, published_by=user))
        await db.commit()

    class AckSession(AsyncSession):
        def __init__(self, *args, fault=2, lost=False, **kwargs):
            super().__init__(*args, **kwargs)
            self.commits, self.fault, self.lost = 0, fault, lost

        async def commit(self):
            self.commits += 1
            if self.commits == self.fault:
                if self.lost:
                    await super().commit()
                raise RuntimeError("synthetic_ack_fault")
            return await super().commit()

    class ObservedLLM(FakeLLM):
        validated_responses = 0

        async def ainvoke_validated(self, messages, parser):
            result = await super().ainvoke_validated(messages, parser)
            self.validated_responses += 1
            return result

    async def create(*, fails=False, callback=None, proposal_content=None, session_type=AsyncSession, **session_kwargs):
        body = CorrectionPreviewRequest(request_key=uuid4(), lesson_id=lesson, instruction="Correct material from source.", locale="en")
        llm = ObservedLLM(proposal_content or content, len(references), fails=fails, callback=(lambda: callback(body)) if callback else None)

        async def resolver(at):
            require(at == tenant, "model_scope_mismatch")
            return llm

        async with session_type(runtime_engine, expire_on_commit=False, **session_kwargs) as db:
            await context(db)
            with patch("app.core.storage.get_storage", return_value=storage):
                try:
                    preview = await service.create_correction_preview(db, actor, body, provider_resolver=resolver)
                except RuntimeError as exc:
                    require(str(exc) == "synthetic_ack_fault", "unexpected_transport_error")
                    preview = None
        row = (await sql(f"SELECT * FROM {plans} WHERE request_key=:key", {"key": body.request_key})).mappings().one()
        return SimpleNamespace(preview=preview, llm=llm, body=body, row=dict(row), id=row["id"])

    ready = await create()
    require(ready.preview.state == "ready" and ready.llm.calls == 1, "ready_missing")
    accounting_row = (await sql(f"SELECT * FROM {ledger} WHERE plan_id=:id", {"id": ready.id})).mappings().one()
    require(accounting_row["state"] == "charged" and accounting_row["provider_boundary_at"] is not None and accounting_row["settled_at"] is not None, "charge_missing")
    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db)
        with patch("app.core.storage.get_storage", return_value=storage):
            replay = await service.create_correction_preview(db, actor, ready.body, provider_resolver=lambda _: require(False, "replay_provider_called"))
        require(replay.fingerprint == ready.preview.fingerprint, "replay_changed")
    checks.append("ready_charge_replay")
    usage_before = (await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t", {"t": tenant})).one()
    failed = await create(fails=True)
    require(failed.preview.state == "failed" and failed.llm.calls == 1, "known_failure_missing")
    require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": failed.id})).scalar_one() == "refunded", "refund_missing")
    require((await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t", {"t": tenant})).one() == usage_before, "known_failure_aggregate_changed")
    checks.append("known_failure_refund_once")
    for lost, expected, label in ((False, "reserved", "t2_rollback_no_provider"), (True, "started", "t2_lost_ack_no_provider")):
        item = await create(session_type=AckSession, lost=lost)
        require(item.preview is None and item.llm.calls == 0 and item.row["status"] == "pending", "t2_invoked_provider")
        require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": item.id})).scalar_one() == expected, "t2_durable_state_wrong")
        checks.append(label)
    acknowledged = await create(session_type=AckSession, fault=3, lost=True)
    require(acknowledged.preview.state == "ready" and acknowledged.preview.proposal is not None and acknowledged.llm.calls == 1, "t3_readback_invalid")
    checks.append("t3_lost_ack_ready_readback")

    async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
        await context(db)
        with patch("app.core.storage.get_storage", return_value=storage):
            applied = await application.apply_correction_preview(db, actor, ConfirmationRequest(plan_id=ready.id, revision=1, fingerprint=ready.preview.fingerprint))
        require(applied.plan_id == ready.id, "application_missing")
    domain_before = await state()
    template = ready.row
    receipt_template = dict((await sql(f"SELECT * FROM {receipts} WHERE plan_id=:id", {"id": ready.id})).mappings().one())

    async def historical(*, status="pending", accounting=None, age=timedelta(minutes=1), at=tenant, who=user, applied_age=None, month=None):
        """Owner-only fixture: no runtime guard/constraint/grant is weakened."""
        ident = uuid4()
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            now = (await db.execute(text("SELECT transaction_timestamp()"))).scalar_one()
            expiry = now - age
            created = expiry - timedelta(minutes=15) + timedelta(microseconds=1)
            snapshot = copy.deepcopy(template["snapshot"])
            snapshot.update(plan_id=str(ident), actor_id=str(who), created_at=created.isoformat(), expires_at=expiry.isoformat())
            snapshot["context"]["tenant_id"] = str(at)
            # Only these fresh owned tables, inside one owner transaction.
            for table, trigger in ((plans, "lesson_correction_guard"), (ledger, "lesson_correction_accounting_guard"), (receipts, "lesson_correction_application_guard")):
                await db.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}"))
            await db.execute(text(f"INSERT INTO {plans}(id,tenant_id,actor_id,request_key,request_digest,snapshot,status,proposal,fingerprint,error_code,created_at,expires_at,finished_at) VALUES(:id,:t,:u,:key,:digest,CAST(:snapshot AS jsonb),:status,CAST(:proposal AS jsonb),:fingerprint,:error,:created,:expiry,:finished)"), {"id": ident, "t": at, "u": who, "key": uuid4(), "digest": template["request_digest"], "snapshot": json.dumps(snapshot), "status": status, "proposal": json.dumps(template["proposal"]) if status == "ready" else None, "fingerprint": template["fingerprint"] if status == "ready" else None, "error": "proposal_unavailable" if status == "failed" else None, "created": created, "expiry": expiry, "finished": created + timedelta(seconds=1) if status != "pending" else None})
            if accounting:
                key = month or created.strftime("%Y-%m")
                await db.execute(text(f"INSERT INTO {ledger}(plan_id,tenant_id,actor_id,month_key,estimated_cost_cents,state,created_at,provider_boundary_at,settled_at) VALUES(:id,:t,:u,:month,10,:state,:created,:boundary,:settled)"), {"id": ident, "t": at, "u": who, "month": key, "state": accounting, "created": created, "boundary": created + timedelta(seconds=1) if accounting != "reserved" else None, "settled": created + timedelta(seconds=2) if accounting in {"charged", "retained", "refunded"} else None})
                await db.execute(text(f"INSERT INTO {q}.tenant_llm_usage(id,tenant_id,month_key,cost_cents,request_count) VALUES(:id,:t,:month,10,1) ON CONFLICT(tenant_id,month_key) DO UPDATE SET cost_cents={q}.tenant_llm_usage.cost_cents+10,request_count={q}.tenant_llm_usage.request_count+1"), {"id": uuid4(), "t": at, "month": key})
            if applied_age is not None:
                r = receipt_template
                await db.execute(text(f"INSERT INTO {receipts}(plan_id,tenant_id,actor_id,course_id,lesson_id,revision,fingerprint,before_sha256,after_sha256,applied_at) VALUES(:id,:t,:u,:course,:lesson,:revision,:fingerprint,:before,:after,:applied)"), {"id": ident, "t": at, "u": who, "course": course, "lesson": lesson, "revision": r["revision"], "fingerprint": r["fingerprint"], "before": r["before_sha256"], "after": r["after_sha256"], "applied": now - applied_age})
            for table, trigger in ((plans, "lesson_correction_guard"), (ledger, "lesson_correction_accounting_guard"), (receipts, "lesson_correction_application_guard")):
                await db.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER {trigger}"))
        return ident

    async def maintenance(*, limit=100, apply=False, commit=True, at=tenant):
        async with runtime_engine.connect() as db:
            await context(db, at, user if at == tenant else other, superadmin=True)
            rows = (await db.execute(text(f"SELECT * FROM {maintain}(:limit,:apply)"), {"limit": limit, "apply": apply})).all()
            if commit:
                await db.commit()
            else:
                await db.rollback()
            return rows

    foreign_plan = await historical(accounting="started", at=foreign, who=other)
    for at, who in ((tenant, sibling), (foreign, other)):
        async with runtime_engine.connect() as db:
            await context(db, at, who)
            require((await db.execute(text(f"SELECT count(*) FROM {ledger} WHERE plan_id=:id"), {"id": ready.id})).scalar_one() == 0, "ledger_foreign_visible")
    checks.append("ledger_rls_two_tenants")
    await denied(f"SELECT * FROM {maintain}(100,false)", code="42501")
    await denied(f"SELECT * FROM {maintain}(100,false)", absent=True, code="42501")
    checks.append("maintenance_authority")
    for column, value in (("month_key", "'2020-01'"), ("estimated_cost_cents", "20"), ("actor_id", "gen_random_uuid()"), ("tenant_id", "gen_random_uuid()"), ("created_at", "clock_timestamp()"), ("provider_boundary_at", "clock_timestamp()"), ("settled_at", "clock_timestamp()")):
        await denied(f"UPDATE {ledger} SET {column}={value} WHERE plan_id=:id", {"id": ready.id}, code="42501")
    checks.append("ledger_identity_acl")
    forged_parent = await historical(age=timedelta(minutes=-5))
    forged_month = (await sql(f"SELECT to_char((snapshot->>'created_at')::timestamptz AT TIME ZONE 'UTC','YYYY-MM') FROM {plans} WHERE id=:id", {"id": forged_parent})).scalar_one()
    admission = f"INSERT INTO {ledger}(plan_id,tenant_id,actor_id,month_key,estimated_cost_cents,state,provider_boundary_at,settled_at) VALUES(:id,:t,:u,:month,:cost,:state,:boundary,:settled)"
    valid = {"id": forged_parent, "t": tenant, "u": user, "month": forged_month, "cost": 10, "state": "reserved", "boundary": None, "settled": None}
    for field, value in (("id", uuid4()), ("t", foreign), ("u", sibling), ("month", "1900-01"), ("cost", 20), ("state", "started"), ("boundary", template["created_at"]), ("settled", template["created_at"])):
        await denied(admission, {**valid, field: value})
    require((await sql(f"SELECT count(*) FROM {ledger} WHERE plan_id=:id", {"id": forged_parent})).scalar_one() == 0, "forged_ledger_persisted")
    checks.append("ledger_forged_admission")
    await denied(f"UPDATE {ledger} SET state='refunded' WHERE plan_id=:id", {"id": ready.id}, code="23514")
    checks.append("ledger_terminal_guard")
    for batch in (0, 501, None):
        await denied(f"SELECT * FROM {maintain}(:batch,false)", {"batch": batch}, superadmin=True, code="22023")
    await denied(f"SELECT * FROM {maintain}(100,NULL)", superadmin=True, code="22023")
    checks.append("batch_input_bounds")

    # Move transport-fault pending fixtures out of maintenance eligibility; they
    # are still live. All following selected pending rows are deliberately expired.
    reserved = await historical(accounting="reserved", age=timedelta(days=120))
    started = await historical(accounting="started")
    legacy = await historical()
    old_month = (await sql(f"SELECT month_key FROM {ledger} WHERE plan_id=:id", {"id": reserved})).scalar_one()
    current_month = (await sql("SELECT to_char(transaction_timestamp() AT TIME ZONE 'UTC','YYYY-MM')")).scalar_one()
    require(old_month != current_month, "historical_month_not_distinct")
    original_before = (await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": old_month})).one()
    current_before = (await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": current_month})).one()
    all_metadata = ("workbench_lesson_correction_plans", "workbench_lesson_correction_accounting", "workbench_lesson_correction_applications", "tenant_llm_usage")
    before = await state(all_metadata)
    dry = await maintenance()
    require(await state(all_metadata) == before and any(p == reserved and a == "reconcile_refund" for p, a in dry), "dry_run_mutated")
    checks.append("dry_run_read_only")
    require((await maintenance(limit=1))[0][0] == reserved, "oldest_batch_wrong")
    checks.append("bounded_ordering")
    await maintenance(apply=True, commit=False)
    require(await state(all_metadata) == before, "maintenance_rollback_mutated")
    checks.append("rollback_and_repeat")
    await maintenance(apply=True)
    require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": reserved})).scalar_one() == "refunded", "reserved_not_refunded")
    require((await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": old_month})).one() == (original_before[0] - 10, original_before[1] - 1), "original_month_not_refunded")
    require((await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": current_month})).one() == current_before, "wrong_month_changed")
    checks.append("original_month_refund")
    require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": started})).scalar_one() == "retained", "started_not_retained")
    checks.append("started_retained")
    require((await sql(f"SELECT status,error_code FROM {plans} WHERE id=:id", {"id": legacy})).one() == ("failed", "proposal_interrupted"), "legacy_not_closed")
    checks.append("legacy_retained")
    # Expired pending was reconciled, not deleted in that same call.
    require((await sql(f"SELECT count(*) FROM {plans} WHERE id=:id", {"id": reserved})).scalar_one() == 1, "reconciled_deleted_same_call")
    await denied(f"UPDATE {plans} SET status='ready',error_code=NULL WHERE id=:id", {"id": started})

    bad = await historical(accounting="reserved", age=timedelta(days=60))
    bad_month = (await sql(f"SELECT month_key FROM {ledger} WHERE plan_id=:id", {"id": bad})).scalar_one()
    await sql(f"UPDATE {q}.tenant_llm_usage SET cost_cents=0,request_count=0 WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": bad_month})
    before = await state(all_metadata)
    await denied(f"SELECT * FROM {maintain}(500,true)", superadmin=True, code="23514")
    require(await state(all_metadata) == before, "insufficient_refund_partially_mutated")
    checks.append("insufficient_aggregate_atomic")
    await sql(f"UPDATE {q}.tenant_llm_usage SET cost_cents=10,request_count=1 WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": bad_month})
    await maintenance(apply=True)

    malformed = await historical(accounting="charged")
    before = await state(all_metadata)
    await denied(f"SELECT * FROM {maintain}(500,true)", superadmin=True, code="23514")
    require(await state(all_metadata) == before, "malformed_accounting_partially_mutated")
    await sql(f"DELETE FROM {plans} WHERE id=:id", {"id": malformed})
    checks.append("malformed_accounting_atomic")

    async def interrupt_provider(body):
        async with owner_engine.begin() as db:
            await set_context(db, schema)
            row = (await db.execute(text(f"SELECT id,snapshot FROM {plans} WHERE request_key=:key"), {"key": body.request_key})).mappings().one()
            now = (await db.execute(text("SELECT clock_timestamp()"))).scalar_one()
            expiry = now - timedelta(minutes=1)
            created = expiry - timedelta(minutes=15) + timedelta(microseconds=1)
            snapshot = copy.deepcopy(row["snapshot"])
            snapshot.update(created_at=created.isoformat(), expires_at=expiry.isoformat())
            await db.execute(text(f"ALTER TABLE {plans} DISABLE TRIGGER lesson_correction_guard"))
            await db.execute(text(f"UPDATE {plans} SET created_at=:c,expires_at=:e,snapshot=CAST(:s AS jsonb) WHERE id=:id"), {"c": created, "e": expiry, "s": json.dumps(snapshot), "id": row["id"]})
            await db.execute(text(f"ALTER TABLE {plans} ENABLE TRIGGER lesson_correction_guard"))
        require(any(p == row["id"] and a == "reconcile_retain" for p, a in await maintenance(apply=True)), "live_pending_not_closed")

    before_usage = (await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": current_month})).one()
    late = await create(callback=interrupt_provider, proposal_content=content + "\n")
    require(late.preview.state == "failed" and late.preview.error_code == "proposal_interrupted" and late.llm.calls == 1 and late.llm.validated_responses == 1, "late_completion_revived")
    require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": late.id})).scalar_one() == "retained", "late_completion_refunded")
    require((await sql(f"SELECT cost_cents,request_count FROM {q}.tenant_llm_usage WHERE tenant_id=:t AND month_key=:m", {"t": tenant, "m": current_month})).one() == (before_usage[0] + 10, before_usage[1] + 1), "late_completion_wrong_aggregate")
    checks.append("late_completion_no_revival")

    # The candidate cursor materializes joined ledger state before parent locks.
    # Hold a legitimate T2 marker until after expiry; pause an earlier parent's
    # UPDATE so the candidate snapshot is old, then commit T2 before its parent
    # is visited. SKIP LOCKED never waits: the target is unlocked by visitation.
    barrier_parent = await historical(age=timedelta(days=1))
    # PL/pgSQL prefetches a cursor batch before entering the loop body. Put the
    # target beyond the first 50 rows; otherwise it is legitimately SKIP LOCKED
    # before the earlier parent's trigger can establish the barrier.
    async with owner_engine.begin() as db:
        await set_context(db, schema)
        now = (await db.execute(text("SELECT clock_timestamp()"))).scalar_one()
        expiry = now - timedelta(minutes=1)
        created = expiry - timedelta(minutes=15) + timedelta(microseconds=1)
        await db.execute(text(f"ALTER TABLE {plans} DISABLE TRIGGER lesson_correction_guard"))
        await db.execute(text(f"""WITH fixtures AS(
            SELECT gen_random_uuid() AS id,gen_random_uuid() AS request_key FROM generate_series(1,50))
            INSERT INTO {plans}(id,tenant_id,actor_id,request_key,request_digest,snapshot,status,created_at,expires_at)
            SELECT f.id,p.tenant_id,p.actor_id,f.request_key,p.request_digest,
                jsonb_set(jsonb_set(jsonb_set(p.snapshot,'{{plan_id}}',to_jsonb(f.id::text)),
                    '{{created_at}}',to_jsonb(CAST(:created_text AS text))),
                    '{{expires_at}}',to_jsonb(CAST(:expiry_text AS text))),
                'pending',:created,:expiry FROM fixtures f CROSS JOIN {plans} p WHERE p.id=:id"""),
            {"id": barrier_parent, "created": created, "expiry": expiry, "created_text": created.isoformat(), "expiry_text": expiry.isoformat()})
        await db.execute(text(f"ALTER TABLE {plans} ENABLE TRIGGER lesson_correction_guard"))
    marker_parent = await historical(accounting="reserved", age=timedelta(seconds=-10))
    unlock_key, ready_key = (int(uuid4().hex[:7], 16) for _ in range(2))
    await sql(f"""CREATE FUNCTION {q}.gate_lifecycle_action_pause() RETURNS trigger
        LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$ BEGIN
        IF NEW.id='{barrier_parent}'::uuid AND NEW.status='failed' THEN
            PERFORM pg_advisory_xact_lock({ready_key});
            WHILE NOT pg_try_advisory_xact_lock({unlock_key}) LOOP
                PERFORM pg_sleep(0.025);
            END LOOP;
        END IF; RETURN NEW; END $$""")
    await sql(f"CREATE TRIGGER gate_lifecycle_action_pause BEFORE UPDATE ON {plans} FOR EACH ROW EXECUTE FUNCTION {q}.gate_lifecycle_action_pause()")
    maintenance_task = None
    primary_error = None
    async with owner_engine.connect() as barrier, AsyncSession(runtime_engine, expire_on_commit=False) as marker:
        try:
            await set_context(barrier, schema)
            await barrier.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": unlock_key})
            await context(marker)
            await marker.execute(text(f"SELECT id FROM {plans} WHERE id=:id FOR UPDATE"), {"id": marker_parent})
            await marker.execute(text(f"UPDATE {ledger} SET state='started' WHERE plan_id=:id"), {"id": marker_parent})
            async with asyncio.timeout(20):
                while not (await barrier.execute(text(f"SELECT clock_timestamp() >= expires_at FROM {plans} WHERE id=:id"), {"id": marker_parent})).scalar_one():
                    await asyncio.sleep(0.025)
            maintenance_task = asyncio.create_task(maintenance(apply=True, limit=500))
            async with asyncio.timeout(20):
                while not (await barrier.execute(text("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND classid=0 AND objid=:key AND granted)"), {"key": ready_key})).scalar_one():
                    await asyncio.sleep(0.025)
            await marker.commit()  # started is current; candidate joined reserved
        except BaseException as exc:
            primary_error = exc
        finally:
            await marker.rollback()
            await barrier.rollback()
            if maintenance_task is not None:
                outcome = (await asyncio.gather(maintenance_task, return_exceptions=True))[0]
                if primary_error is None and isinstance(outcome, BaseException):
                    primary_error = outcome
        if primary_error is not None:
            raise primary_error
    require((await sql(f"SELECT state FROM {ledger} WHERE plan_id=:id", {"id": marker_parent})).scalar_one() == "retained", "marker_interleaving_wrong_state")
    require(dict(outcome).get(marker_parent) == "reconcile_retain", "marker_interleaving_wrong_action")
    await sql(f"DROP TRIGGER gate_lifecycle_action_pause ON {plans}")
    await sql(f"DROP FUNCTION {q}.gate_lifecycle_action_pause()")
    checks.append("locked_state_action_provenance")

    locked = await historical(accounting="started")
    async with runtime_engine.connect() as holder:
        await context(holder, superadmin=True)
        await holder.execute(text(f"SELECT id FROM {plans} WHERE id=:id FOR UPDATE"), {"id": locked})
        skipped = await maintenance(apply=True)
        require(all(p != locked for p, _ in skipped), "locked_parent_not_skipped")
        await holder.rollback()
    require(any(p == locked for p, _ in await maintenance(apply=True)), "unlocked_parent_not_reconciled")
    checks.append("skip_locked_parent")

    # Boundary fixtures are then aligned to the SAME frozen runtime transaction
    # clock, avoiding host-clock or elapsed-network approximations.
    preview_old = await historical(status="failed", age=timedelta(days=1))
    preview_young = await historical(status="failed", age=timedelta(days=1))
    receipt_old = await historical(status="ready", accounting="charged", age=timedelta(days=100), applied_age=timedelta(days=90))
    receipt_young = await historical(status="ready", accounting="charged", age=timedelta(days=100), applied_age=timedelta(days=90))
    receipt_recent = await historical(status="ready", accounting="charged", age=timedelta(days=100), applied_age=timedelta(days=1))
    async with runtime_engine.connect() as db:
        await context(db, superadmin=True)
        frozen = (await db.execute(text("SELECT transaction_timestamp()"))).scalar_one()
        async with owner_engine.begin() as owner_db:
            await set_context(owner_db, schema)
            await owner_db.execute(text(f"ALTER TABLE {plans} DISABLE TRIGGER lesson_correction_guard"))
            await owner_db.execute(text(f"ALTER TABLE {receipts} DISABLE TRIGGER lesson_correction_application_guard"))
            for ident, delta in ((preview_old, timedelta(0)), (preview_young, timedelta(microseconds=1))):
                expiry = frozen - timedelta(days=1) + delta
                created = expiry - timedelta(minutes=15) + timedelta(microseconds=1)
                await owner_db.execute(text(f"UPDATE {plans} SET expires_at=:e,created_at=:c,snapshot=jsonb_set(jsonb_set(snapshot,'{{expires_at}}',to_jsonb(CAST(:expiry_text AS text))),'{{created_at}}',to_jsonb(CAST(:created_text AS text))) WHERE id=:id"), {"e": expiry, "c": created, "id": ident, "expiry_text": expiry.isoformat(), "created_text": created.isoformat()})
            for ident, delta in ((receipt_old, timedelta(0)), (receipt_young, timedelta(microseconds=1))):
                await owner_db.execute(text(f"UPDATE {receipts} SET applied_at=:at WHERE plan_id=:id"), {"at": frozen - timedelta(days=90) + delta, "id": ident})
            await owner_db.execute(text(f"ALTER TABLE {plans} ENABLE TRIGGER lesson_correction_guard"))
            await owner_db.execute(text(f"ALTER TABLE {receipts} ENABLE TRIGGER lesson_correction_application_guard"))
        visible = (await db.execute(text(f"SELECT count(*) FROM {receipts} WHERE plan_id=:id"), {"id": receipt_recent})).scalar_one()
        require(visible == 1, "maintenance_receipt_hidden")
        selected = dict((await db.execute(text(f"SELECT * FROM {maintain}(500,false)"))).all())
        require(selected.get(preview_old) == "delete_preview" and preview_young not in selected, "preview_boundary_wrong")
        checks.append("preview_24h_boundary")
        require(selected.get(receipt_old) == "delete_application" and receipt_young not in selected, "receipt_boundary_wrong")
        checks.append("receipt_90d_boundary")
        require(receipt_recent not in selected, "recent_receipt_misclassified")
        checks.append("receipt_visibility_protection")
        await db.execute(text(f"SELECT * FROM {maintain}(500,true)"))
        await db.commit()
    require((await sql(f"SELECT count(*) FROM {ledger} WHERE plan_id=:id", {"id": receipt_old})).scalar_one() == 0, "metadata_cascade_missing")
    for operation in ("get", "apply"):
        async with AsyncSession(runtime_engine, expire_on_commit=False) as db:
            await context(db)
            try:
                if operation == "get":
                    await service.get_correction_preview(db, actor, receipt_old)
                else:
                    await application.apply_correction_preview(db, actor, ConfirmationRequest(plan_id=receipt_old, revision=1, fingerprint=ready.preview.fingerprint))
            except WorkbenchNotFound:
                pass
            else:
                require(False, "removed_plan_reconstructed")
    checks.append("removed_id_refused")
    require(await state() == domain_before, "maintenance_changed_domain")
    checks.append("metadata_only_neighbor_invariant")
    foreign_before = (await sql(f"SELECT to_jsonb(p) FROM {plans} p WHERE id=:id", {"id": foreign_plan})).scalar_one()
    async with runtime_engine.begin() as db:
        await context(db, superadmin=True)
        for table in (ledger, receipts, plans):
            await db.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})
    require((await sql(f"SELECT to_jsonb(p) FROM {plans} p WHERE id=:id", {"id": foreign_plan})).scalar_one() == foreign_before and await state() == domain_before, "purge_changed_neighbor")
    checks.append("exact_tenant_purge")
    async with owner_engine.connect() as db:
        await set_context(db, schema)
        try:
            await apply_0178(db, schema, "downgrade")
        except RuntimeError:
            await db.rollback()
        else:
            require(False, "populated_downgrade_allowed")
    checks.append("populated_downgrade_refused")
    await sql(f"DELETE FROM {plans}")
    async with owner_engine.begin() as db:
        await set_context(db, schema)
        await apply_0178(db, schema, "downgrade")
        await apply_0178(db, schema)
    checks.append("empty_down_up")
    legacy_upgrade = await historical()
    # Empty new ledger with existing legacy parent: additive upgrade must preserve
    # the parent and must not fabricate per-plan accounting.
    async with owner_engine.begin() as db:
        await set_context(db, schema)
        await db.execute(text(f"DELETE FROM {plans} WHERE id=:id"), {"id": legacy_upgrade})
        await apply_0178(db, schema, "downgrade")
        # Insert a pending legacy record through its actual 0176 admission path.
        now = (await db.execute(text("SELECT clock_timestamp()"))).scalar_one()
        snapshot = copy.deepcopy(template["snapshot"])
        snapshot.update(plan_id=str(legacy_upgrade), created_at=now.isoformat(), expires_at=(now + timedelta(minutes=15)).isoformat())
        await db.execute(text(f"INSERT INTO {plans}(id,tenant_id,actor_id,request_key,request_digest,snapshot,status,expires_at) VALUES(:id,:t,:u,:key,:digest,CAST(:s AS jsonb),'pending',:e)"), {"id": legacy_upgrade, "t": tenant, "u": user, "key": uuid4(), "digest": template["request_digest"], "s": json.dumps(snapshot), "e": now + timedelta(minutes=15)})
        await apply_0178(db, schema)
    require((await sql(f"SELECT count(*) FROM {plans} WHERE id=:id", {"id": legacy_upgrade})).scalar_one() == 1 and (await sql(f"SELECT count(*) FROM {ledger}")).scalar_one() == 0, "upgrade_fabricated_ledger")
    checks.append("populated_upgrade_no_backfill")
