"""Isolated DEV source-preparation lifecycle and RLS gate; never migrates public."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dev_public_schema_gate import load_dev_environment, resolve_env_file
from kb_rag_isolated_dev_gate import GateBlocked, normalize_database_url, same_supabase_project
from source_actuality_dev_gate import public_snapshot, verify_runtime_role

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))
MIGRATION = ROOT / "apps/api/alembic/versions/0185_source_editorial_events.py"
SCHEMA = re.compile(r"preparation_review_dev_[0-9a-f]{12}\Z")
KNOWN_CONSTRAINTS = frozenset({"uq_documents_active_tenant_content_sha256"})
RECOVERY_CHECKS = frozenset({"unknown_retry_ack_exact_and_replay", "unknown_retry_concurrent_one_winner",
                             "continuation_cross_actor_exact_event", "recovery_stale_source_and_tenant_denied"})
RECOVERY_DIAGNOSTICS = frozenset({
    "ack_required", "ack_stale_revision", "ack_first_dispatch", "ack_duplicate_replay", "ack_foreign_actor",
    "ack_failure_preserved", "ack_receipt_binding", "ack_race_one_winner", "ack_race_history",
    "continuation_dispatch", "continuation_replay", "continuation_history", "continuation_binding",
    "continuation_stale_revision", "continuation_foreign_tenant", "continuation_changed_source",
    "non_boolean_ack_accepted", "foreign_continuation_visible",
})


def recovery_coverage(checks: list[str]) -> bool:
    return RECOVERY_CHECKS <= set(checks)


def safe_schema(schema: str) -> str:
    if not SCHEMA.fullmatch(schema):
        raise ValueError("invalid_owned_schema")
    return f'"{schema}"'


def safe_db_diagnostic(exc: DBAPIError) -> dict[str, str | None]:
    """Expose only a SQLSTATE and known fixed constraint identifier, never DB values."""
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    state = getattr(orig, "sqlstate", None) or getattr(cause, "sqlstate", None)
    constraint = getattr(orig, "constraint_name", None) or getattr(cause, "constraint_name", None)
    return {"sqlstate": state if isinstance(state, str) and re.fullmatch(r"[0-9A-Z]{5}", state) else None,
            "constraint": constraint if isinstance(constraint, str) and constraint in KNOWN_CONSTRAINTS else None}


def migrate(connection, schema: str, direction: str) -> None:
    safe_schema(schema)
    if direction not in {"upgrade", "downgrade"}:
        raise ValueError("invalid_migration_direction")
    from ai_generation_checkpoint_dev_check import load_module
    migration = load_module("isolated_preparation_review_0185", MIGRATION)
    with Operations.context(MigrationContext.configure(connection, opts={"version_table_schema": schema})):
        getattr(migration, direction)()


def synthetic_manifest(tenant: UUID, document: UUID):
    from app.modules.source_preparation.domain import PreparedSource, digest
    original_sha = hashlib.sha256(("source-preparation-gate:" + str(document)).encode()).hexdigest()
    image_sha = hashlib.sha256(b"synthetic image bytes, not stored").hexdigest()
    image_id = "asset-" + image_sha
    blocks = [
        {"id": "block-" + "1" * 24, "text": "Learning: perform the documented procedure.",
         "kind": "text", "page": 1, "asset_ids": [image_id]},
        {"id": "block-" + "2" * 24, "text": "Administrative: acknowledgement register.",
         "kind": "text", "page": 2},
    ]
    parts = [{"id": "part-" + digest(original_sha + b["id"] + b["id"])[:24], "title": title,
              "role": role, "reason": "Synthetic fixture", "first_block": b["id"], "last_block": b["id"]}
             for b, title, role in zip(blocks, ("Learning", "Register"), ("learning", "administrative"), strict=True)]
    asset = {"id": image_id, "sha256": image_sha, "mime_type": "image/png", "width": 1, "height": 1,
             "storage_key": f"source-assets/{tenant}/{document}/{image_sha}.png", "caption": "Synthetic image",
             "kind": "figure", "text": "", "description": "Synthetic image", "uncertainties": [], "locator": {}}
    return PreparedSource.model_validate({"original_blob_sha256": original_sha, "blocks": blocks,
                                          "parts": parts, "assets": [asset]})


def selected_binding_text(binding: dict, original_sha: str) -> str:
    from app.modules.source_preparation.domain import validate_binding
    manifest, ids = validate_binding(binding, original_sha)
    return manifest.selected(ids)[0]


async def run() -> dict[str, object]:
    values, owner_url, _ = load_dev_environment(resolve_env_file(None))
    os.environ.update(values)
    from app.models.document import Document
    from app.modules.source_editorial_review.domain import POLICY, ReviewCommand, ReviewConflictError
    from app.modules.source_editorial_review.service import (
        add_event, apply_command, continuation_pending, history, owned_document, pin_reviews, read_state, resolve_pins,
    )
    from app.modules.source_preparation.domain import PreparedSource, digest
    from app.modules.source_preparation.lesson_assets import approved_asset_inventory, bind_lesson_assets
    from app.modules.source_preparation.preparation import _VISUAL_REVIEW_POLICY

    runtime_url = normalize_database_url(values["DATABASE_URL"])
    if ((make_url(runtime_url).username or "").split(".")[0] != "lms_app"
            or not all(same_supabase_project(url, values["SUPABASE_URL"]) for url in (owner_url, runtime_url))):
        raise GateBlocked("unexpected_DEV_identity")
    schema = "preparation_review_dev_" + uuid4().hex[:12]
    qualified = safe_schema(schema)
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    (tenant, other, doc_id, race_resolve, race_approve, foreign_doc, actor, legacy_doc,
     recovery_doc, recovery_race_doc, continuation_doc, actor_two) = (uuid4() for _ in range(12))
    package = synthetic_manifest(tenant, doc_id)
    packages = {doc_id: package, race_resolve: synthetic_manifest(tenant, race_resolve),
                race_approve: synthetic_manifest(tenant, race_approve), foreign_doc: synthetic_manifest(other, foreign_doc),
                legacy_doc: synthetic_manifest(tenant, legacy_doc), recovery_doc: synthetic_manifest(tenant, recovery_doc),
                recovery_race_doc: synthetic_manifest(tenant, recovery_race_doc),
                continuation_doc: synthetic_manifest(tenant, continuation_doc)}
    learning, administrative = (p.id for p in package.parts)
    checks: list[str] = []
    source_sha = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    before = None
    created = cleanup = neutral = False
    failure = None
    db_diagnostic = None
    stage = "preflight"

    async def scope(db, tenant_id: UUID):
        await db.execute(text(f"SET LOCAL search_path={qualified},pg_catalog"))
        await db.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})
        for table in ("documents", "document_editorial_events"):
            actual = await db.scalar(text("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(:table)"), {"table": table})
            if actual != schema:
                raise GateBlocked("unsafe_public_table_resolution")

    async def command(document: UUID, request: ReviewCommand) -> str:
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, document, lock=True)
            try:
                await apply_command(db, doc, actor, request)
                await db.commit()
                return "applied"
            except ReviewConflictError as exc:
                await db.rollback()
                return str(exc)

    async def recovery_command(document: UUID, request: ReviewCommand, command_actor: UUID):
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, document, lock=True)
            try:
                _, _, receipt, dispatch = await apply_command(db, doc, command_actor, request)
                await db.commit()
                return "applied", receipt.id, dispatch
            except ReviewConflictError as exc:
                await db.rollback()
                return str(exc), None, False

    async def seed_unknown(document: UUID) -> UUID:
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, document, lock=True)
            initial = add_event(db, doc, actor_id=actor, sequence=1, kind="queued", payload={})
            add_event(db, doc, actor_id=actor, sequence=2, kind="running", payload={"queued_event_id": str(initial.id)})
            failed = add_event(db, doc, actor_id=actor, sequence=3, kind="failed", payload={
                "code": "source_review_timeout", "phase": "editor_request", "usage_complete": False,
                "unknown_request_key": "c" * 64})
            await db.commit()
            return failed.id

    async def mock_complete(document: UUID, binding: dict, *, issues: list | None = None, seed_manifest: bool = False):
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, document, lock=True)
            rows = await history(db, tenant, document)
            assert rows[-1].kind == "queued"
            state = read_state(rows, doc.content_sha256)
            add_event(db, doc, actor_id=actor, sequence=state.revision + 1, kind="running", payload={})
            if seed_manifest:
                add_event(db, doc, actor_id=actor, sequence=state.revision + 2, kind="analysis_block", payload={
                    "key": "source-preparation-v1:manifest:" + doc.content_sha256,
                    "result": {"manifest": packages[document].model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}})
            source = selected_binding_text(binding, doc.content_sha256)
            add_event(db, doc, actor_id=actor, sequence=state.revision + 2 + int(seed_manifest), kind="analyzed", payload={
                "policy": POLICY, "original": source, "preparation": binding, "issues": issues or [], "automatic": [],
                "fidelity": {}})
            await db.commit()

    try:
        async with runtime.connect() as db:
            await verify_runtime_role(db)
        async with owner.begin() as db:
            before = await public_snapshot(db)
            if before[0] not in {"0185", "0186"}:
                raise GateBlocked("unexpected_public_baseline")
            stage = "owned_schema_setup"
            await db.execute(text(f"CREATE SCHEMA {qualified}"))
            created = True
            await db.execute(text(f"REVOKE ALL ON SCHEMA {qualified} FROM PUBLIC"))
            await db.execute(text(f"GRANT USAGE ON SCHEMA {qualified} TO lms_app"))
            await db.execute(text(f"CREATE TABLE {qualified}.tenants(id uuid PRIMARY KEY)"))
            await db.execute(text(f"INSERT INTO {qualified}.tenants VALUES(:tenant),(:other)"), {"tenant": tenant, "other": other})
            await db.execute(text(f"SET LOCAL search_path={qualified},pg_catalog"))
            await db.run_sync(lambda con: Document.__table__.create(con, checkfirst=False))
            for did, tid in ((doc_id, tenant), (race_resolve, tenant), (race_approve, tenant),
                             (foreign_doc, other), (legacy_doc, tenant), (recovery_doc, tenant),
                             (recovery_race_doc, tenant), (continuation_doc, tenant)):
                await db.execute(text(f"""INSERT INTO {qualified}.documents(id,tenant_id,uploaded_by,title,content_type,content_sha256,file_size)
                    VALUES(:doc,:tenant,:actor,'Synthetic preparation gate','text/plain',:sha,100)"""),
                    {"doc": did, "tenant": tid, "actor": actor, "sha": packages[did].original_blob_sha256})
            await db.execute(text(f"ALTER TABLE {qualified}.documents ENABLE ROW LEVEL SECURITY"))
            await db.execute(text(f"ALTER TABLE {qualified}.documents FORCE ROW LEVEL SECURITY"))
            await db.execute(text(f"""CREATE POLICY owned ON {qualified}.documents FOR ALL TO lms_app
                USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)"""))
            await db.execute(text(f"GRANT SELECT,UPDATE ON {qualified}.documents TO lms_app"))
            await db.run_sync(migrate, schema, "upgrade")
        stage = "runtime_lifecycle"
        async with sessions() as db:
            await scope(db, tenant)
            flags = (await db.execute(text("""SELECT current_user,r.rolsuper,r.rolbypassrls,c.relrowsecurity,c.relforcerowsecurity
                FROM pg_roles r,pg_class c WHERE r.rolname=current_user AND c.oid=to_regclass(:table)"""),
                {"table": f"{schema}.document_editorial_events"})).one()
            assert tuple(flags) == ("lms_app", False, False, True, True)
            doc = await owned_document(db, tenant, doc_id, lock=True)
            for sequence, kind, payload in [(1, "queued", {}), (2, "running", {}), (3, "analysis_block", {
                "key": "source-preparation-v1:manifest:" + package.original_blob_sha256,
                "result": {"manifest": package.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}}),
                (4, "failed", {"code": "synthetic_failure"})]:
                add_event(db, doc, actor_id=actor, sequence=sequence, kind=kind, payload=payload)
            await db.commit()
        async with sessions() as db:
            await scope(db, tenant)
            state = read_state(await history(db, tenant, doc_id), package.original_blob_sha256)
            assert state.status == "failed" and state.preparation["selected_part_ids"] == [learning]
        both = package.binding([learning, administrative])
        chosen = ReviewCommand(action="select_parts", expected_revision=4, request_id=uuid4(),
                               selected_part_ids=[learning, administrative], preparation_sha256=package.sha256)
        assert await command(doc_id, chosen) == "applied"
        await mock_complete(doc_id, both)
        assert await command(doc_id, ReviewCommand(action="select_parts", expected_revision=7, request_id=uuid4(),
            selected_part_ids=[learning], preparation_sha256=package.sha256)) == "applied"
        await mock_complete(doc_id, package.binding([learning]))
        assert await command(doc_id, ReviewCommand(action="approve", expected_revision=10, request_id=uuid4())) == "applied"
        async with sessions() as db:
            await scope(db, tenant)
            pins = await pin_reviews(db, tenant, [doc_id])
            approved = await resolve_pins(db, tenant, [str(doc_id)], pins)
            frozen = approved[str(doc_id)]
            assert frozen.working_text == package.blocks[0].text and package.blocks[1].text not in frozen.working_text
            inventory = approved_asset_inventory(approved)
            assert set(inventory) == {package.assets[0].id}
            content, descriptors = bind_lesson_assets(f"![Synthetic](source-asset:{package.assets[0].id})", inventory,
                                                      course_id=uuid4(), lesson_id=uuid4())
            assert len(descriptors) == 1 and descriptors[0]["document_id"] == str(doc_id) and "source-asset:" not in content
        assert await command(doc_id, ReviewCommand(action="reopen", expected_revision=11, request_id=uuid4())) == "applied"
        assert await command(doc_id, ReviewCommand(action="select_parts", expected_revision=12, request_id=uuid4(),
            selected_part_ids=[learning, administrative], preparation_sha256=package.sha256)) == "applied"
        await mock_complete(doc_id, both)
        async with sessions() as db:
            await scope(db, tenant)
            assert (await resolve_pins(db, tenant, [str(doc_id)], pins))[str(doc_id)].working_text == package.blocks[0].text
        checks += ["manifest_failed_selection_reanalysis", "exact_approval_pin_and_asset_binding", "historical_pin_after_reselection"]

        stage = "concurrency_and_isolation"
        for did, issue in ((race_resolve, True), (race_approve, False)):
            race_package = packages[did]
            race_learning, race_administrative = (part.id for part in race_package.parts)
            binding = race_package.binding([race_learning])
            async with sessions() as db:
                await scope(db, tenant)
                doc = await owned_document(db, tenant, did, lock=True)
                add_event(db, doc, actor_id=actor, sequence=1, kind="queued", payload={})
                await db.commit()
            issues = [{"id": "q", "start": 0, "end": 8, "quote": "Learning", "reason": "Synthetic question"}] if issue else []
            await mock_complete(did, binding, issues=issues, seed_manifest=True)
            selection = ReviewCommand(action="select_parts", expected_revision=4, request_id=uuid4(),
                selected_part_ids=[race_learning, race_administrative], preparation_sha256=race_package.sha256)
            competing = (ReviewCommand(action="resolve", expected_revision=4, request_id=uuid4(), item_id="q",
                decision="keep", reason="Synthetic resolution") if issue else
                ReviewCommand(action="approve", expected_revision=4, request_id=uuid4()))
            race = await asyncio.gather(command(did, selection), command(did, competing))
            assert sorted(race) == ["applied", "source_review_revision_conflict"]
        checks.append("selection_vs_decision_row_lock_one_winner")
        legacy_package = packages[legacy_doc]
        legacy_binding = legacy_package.binding([legacy_package.parts[0].id])
        async with sessions() as db:
            await scope(db, tenant)
            legacy = await owned_document(db, tenant, legacy_doc, lock=True)
            for sequence, kind, payload in [(1, "queued", {"preparation": legacy_binding}), (2, "running", {}),
                (3, "analysis_block", {"key": "source-preparation-v1:manifest:" + legacy_package.original_blob_sha256,
                                       "result": {"manifest": legacy_package.model_dump()}}),
                (4, "failed", {"code": "source_review_preparation_stale"})]:
                add_event(db, legacy, actor_id=actor, sequence=sequence, kind=kind, payload=payload)
            await db.commit()
        assert await command(legacy_doc, ReviewCommand(action="start", expected_revision=4, request_id=uuid4())) == "applied"
        async with sessions() as db:
            await scope(db, tenant)
            legacy_rows = await history(db, tenant, legacy_doc)
            assert legacy_rows[-1].kind == "queued" and legacy_rows[-1].payload == {}
            legacy_state = read_state(legacy_rows, legacy_package.original_blob_sha256)
            assert legacy_state.pending_preparation is None and legacy_state.preparation is None
        checks.append("legacy_unverified_retry_is_unbound")
        stage = "recovery_contract"
        for invalid_ack in ("true", 1):
            try:
                ReviewCommand(action="start", expected_revision=3, request_id=uuid4(),
                              acknowledge_outcome_and_cost_unknown=invalid_ack)
            except ValidationError:
                pass
            else:
                raise AssertionError("non_boolean_ack_accepted")
        failed_id = await seed_unknown(recovery_doc)
        for ack in (None, False):
            denied = ReviewCommand(action="start", expected_revision=3, request_id=uuid4(),
                                   acknowledge_outcome_and_cost_unknown=ack)
            assert (await recovery_command(recovery_doc, denied, actor))[0] == "source_review_retry_ack_required", "ack_required"
        stale_ack = ReviewCommand(action="start", expected_revision=2, request_id=uuid4(),
                                  acknowledge_outcome_and_cost_unknown=True)
        assert (await recovery_command(recovery_doc, stale_ack, actor))[0] == "source_review_revision_conflict", "ack_stale_revision"
        accepted = ReviewCommand(action="start", expected_revision=3, request_id=uuid4(),
                                 acknowledge_outcome_and_cost_unknown=True)
        first = await recovery_command(recovery_doc, accepted, actor)
        assert first[0] == "applied" and first[2], "ack_first_dispatch"
        assert await recovery_command(recovery_doc, accepted, actor) == first, "ack_duplicate_replay"
        assert (await recovery_command(recovery_doc, accepted, actor_two))[0] == "source_review_request_id_conflict", "ack_foreign_actor"
        async with sessions() as db:
            await scope(db, tenant)
            rows = await history(db, tenant, recovery_doc)
            assert len(rows) == 4 and rows[2].id == failed_id and rows[2].payload["usage_complete"] is False, "ack_failure_preserved"
            assert rows[3].id == first[1] and rows[3].payload["acknowledged_unknown"] == {
                "failure_event_id": str(failed_id), "request_id": str(accepted.request_id), "actor_id": str(actor)}, "ack_receipt_binding"
        checks.append("unknown_retry_ack_exact_and_replay")

        await seed_unknown(recovery_race_doc)
        race_requests = [ReviewCommand(action="start", expected_revision=3, request_id=uuid4(),
                                      acknowledge_outcome_and_cost_unknown=True) for _ in range(2)]
        race_results = await asyncio.gather(*(recovery_command(recovery_race_doc, req, actor) for req in race_requests))
        assert sorted(item[0] for item in race_results) == ["applied", "source_review_revision_conflict"], "ack_race_one_winner"
        async with sessions() as db:
            await scope(db, tenant)
            rows = await history(db, tenant, recovery_race_doc)
            assert len(rows) == 4 and rows[-2].kind == "failed" and rows[-1].kind == "queued", "ack_race_history"
        checks.append("unknown_retry_concurrent_one_winner")

        p = packages[continuation_doc]
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, continuation_doc, lock=True)
            parent = add_event(db, doc, actor_id=actor, sequence=1, kind="queued", payload={})
            claim = add_event(db, doc, actor_id=actor, sequence=2, kind="running",
                              payload={"queued_event_id": str(parent.id)})
            add_event(db, doc, actor_id=actor, sequence=3, kind="analysis_block", payload={
                "claim_id": str(claim.id), "key": "source-preparation-v1:manifest:" + p.original_blob_sha256,
                "result": {"manifest": p.model_dump(), "visual_review_policy": _VISUAL_REVIEW_POLICY}})
            queued = add_event(db, doc, actor_id=actor, sequence=4, kind="queued", payload={
                "continuation_from": str(claim.id), "preparation": p.binding([p.parts[0].id])})
            await db.commit()
            queued_id = queued.id
        redispatch = ReviewCommand(action="start", expected_revision=4, request_id=uuid4())
        assert await recovery_command(continuation_doc, redispatch, actor_two) == ("applied", queued_id, True), "continuation_dispatch"
        assert await recovery_command(continuation_doc, redispatch, actor_two) == ("applied", queued_id, True), "continuation_replay"
        async with sessions() as db:
            await scope(db, tenant)
            rows = await history(db, tenant, continuation_doc)
            assert len(rows) == 4 and rows[-1].id == queued_id and rows[-1].actor_id == actor, "continuation_history"
            assert continuation_pending(rows, p.original_blob_sha256), "continuation_binding"
        checks.append("continuation_cross_actor_exact_event")
        stale_continue = ReviewCommand(action="start", expected_revision=3, request_id=uuid4())
        assert (await recovery_command(continuation_doc, stale_continue, actor_two))[0] == "source_review_revision_conflict", "continuation_stale_revision"
        async with sessions() as db:
            await scope(db, other)
            try:
                await owned_document(db, other, continuation_doc, lock=True)
            except HTTPException as exc:
                assert exc.status_code == 404, "continuation_foreign_tenant"
            else:
                raise AssertionError("foreign_continuation_visible")
        async with sessions() as db:
            await scope(db, tenant)
            doc = await owned_document(db, tenant, continuation_doc, lock=True)
            doc.content_sha256 = hashlib.sha256(b"changed disposable gate source").hexdigest()
            await db.commit()
        assert (await recovery_command(continuation_doc, redispatch, actor_two))[0] == "source_review_original_changed", "continuation_changed_source"
        checks.append("recovery_stale_source_and_tenant_denied")
        stale = ReviewCommand(action="select_parts", expected_revision=3, request_id=uuid4(),
            selected_part_ids=[learning], preparation_sha256=package.sha256)
        assert await command(doc_id, stale) == "source_review_revision_conflict"
        foreign_data = packages[foreign_doc].model_dump()
        first, last = foreign_data["blocks"][0]["id"], foreign_data["blocks"][-1]["id"]
        foreign_data["parts"] = [{"id": "part-" + digest(foreign_data["original_blob_sha256"] + first + last)[:24],
            "title": "Foreign", "role": "learning", "reason": "Foreign fixture", "first_block": first, "last_block": last}]
        foreign_package = PreparedSource.model_validate(foreign_data)
        async with sessions() as db:
            await scope(db, other)
            owned_foreign = await owned_document(db, other, foreign_doc, lock=True)
            add_event(db, owned_foreign, actor_id=actor, sequence=1, kind="queued", payload={})
            add_event(db, owned_foreign, actor_id=actor, sequence=2, kind="analyzed", payload={"policy": POLICY,
                "original": foreign_package.selected([foreign_package.parts[0].id])[0],
                "preparation": foreign_package.binding([foreign_package.parts[0].id]), "issues": [], "automatic": []})
            await db.commit()
        foreign = ReviewCommand(action="select_parts", expected_revision=15, request_id=uuid4(),
            selected_part_ids=[foreign_package.parts[0].id], preparation_sha256=package.sha256)
        assert await command(doc_id, foreign) == "source_review_preparation_invalid"
        async with sessions() as db:
            await scope(db, other)
            assert not await history(db, other, doc_id)
            try:
                await owned_document(db, other, doc_id)
            except HTTPException as exc:
                assert exc.status_code == 404
            else:
                raise AssertionError("foreign_document_visible")
            try:
                await resolve_pins(db, other, [str(doc_id)], pins)
            except ReviewConflictError:
                pass
            else:
                raise AssertionError("foreign_snapshot_visible")
        async with sessions() as db:
            await scope(db, tenant)
            try:
                await db.execute(text("""INSERT INTO document_editorial_events
                    (id,tenant_id,document_id,actor_id,sequence,kind,original_blob_sha256,payload)
                    VALUES(:id,:tenant,:doc,:actor,99,'queued',:sha,'{}')"""),
                    {"id": uuid4(), "tenant": tenant, "doc": foreign_doc, "actor": actor,
                     "sha": foreign_package.original_blob_sha256})
            except DBAPIError as exc:
                assert getattr(exc.orig, "sqlstate", None) == "42501"
            else:
                raise AssertionError("foreign_document_insert_allowed")
        checks += ["stale_and_foreign_part_rejected", "foreign_tenant_read_pin_and_insert_denied"]
    except Exception as exc:
        failure = str(exc) if isinstance(exc, GateBlocked) else type(exc).__name__
        if (isinstance(exc, AssertionError) and len(exc.args) == 1 and isinstance(exc.args[0], str)
                and exc.args[0] in RECOVERY_DIAGNOSTICS):
            failure = exc.args[0]
        if isinstance(exc, DBAPIError):
            db_diagnostic = safe_db_diagnostic(exc)
    finally:
        if created:
            try:
                async with owner.begin() as db:
                    await db.execute(text(f"DROP SCHEMA IF EXISTS {safe_schema(schema)} CASCADE"))
                async with owner.connect() as db:
                    cleanup = not await db.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname=:s)"), {"s": schema})
                    neutral = before is not None and await public_snapshot(db) == before
            except Exception:
                cleanup = False
        await runtime.dispose()
        await owner.dispose()
    if hashlib.sha256(MIGRATION.read_bytes()).hexdigest() != source_sha:
        failure = "migration_source_changed_during_gate"
    if failure is None and not recovery_coverage(checks):
        failure = "recovery_checks_incomplete"
    return {"status": "PASS" if failure is None and cleanup and neutral else "BLOCKED", "failure": failure,
            "database_diagnostic": db_diagnostic,
            "stage": stage, "checks": checks, "cleanup": cleanup, "public_schema_neutral": neutral,
            "public_revision": before[0] if before else None, "public_business_row_equivalence": "NOT_VERIFIED_NOT_WRITTEN",
            "public_migration": "NOT_RUN", "historical_release_retention": "NOT_VERIFIED", "production_actions": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "reason": "execute_required"}))
        return 2
    try:
        result = asyncio.run(run())
    except Exception as exc:
        result = {"status": "BLOCKED", "failure": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
