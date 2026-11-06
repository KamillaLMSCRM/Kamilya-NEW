"""Exercise 0185 and concurrent decisions under lms_app in one disposable DEV schema."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dev_public_schema_gate import database_revision, load_dev_environment, resolve_env_file
from kb_rag_isolated_dev_gate import normalize_database_url, same_supabase_project

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "api"))


def migrate(connection, schema: str, direction: str) -> None:
    if not re.fullmatch(r"editorial_dev_[0-9a-f]{12}", schema):
        raise ValueError("invalid_isolated_schema")
    from ai_generation_checkpoint_dev_check import load_module

    migration = load_module("isolated_editorial_0185", ROOT / "apps/api/alembic/versions/0185_source_editorial_events.py")
    with Operations.context(MigrationContext.configure(connection, opts={"version_table_schema": schema})):
        getattr(migration, direction)()


async def run() -> dict[str, object]:
    values, owner_url, _ = load_dev_environment(resolve_env_file(None))
    os.environ.update(values)
    from app.models.document import Document
    from app.modules.source_editorial_review.domain import POLICY, ReviewCommand, ReviewConflictError
    from app.modules.source_editorial_review.service import (
        add_event, apply_command, history, owned_document, pin_reviews, resolve_pins,
    )

    runtime_url = normalize_database_url(values["DATABASE_URL"])
    if make_url(runtime_url).username.split(".")[0] != "lms_app" or not same_supabase_project(
        runtime_url, values["SUPABASE_URL"]
    ):
        raise ValueError("unexpected_DEV_runtime_identity")
    before = await database_revision(owner_url)
    if before != "0184":
        raise ValueError("unexpected_public_baseline")
    schema = "editorial_dev_" + uuid4().hex[:12]
    s = f'"{schema}"'
    owner = create_async_engine(owner_url, poolclass=NullPool, hide_parameters=True)
    runtime = create_async_engine(runtime_url, poolclass=NullPool, hide_parameters=True)
    sessions = async_sessionmaker(runtime, expire_on_commit=False)
    tenant, other_tenant, document, foreign_doc, actor = (uuid4() for _ in range(5))
    original = "До 45 МРП применяется порядок А. Свыше 45 МРП применяется порядок Б."
    quote = "До 45 МРП применяется порядок А."
    replacement = "До 45 МРП включительно применяется порядок А."
    sha = "d" * 64
    checks: list[str] = []

    async def scope(db, tenant_id: UUID) -> None:
        await db.execute(text(f"SET LOCAL search_path={s},public"))
        await db.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)})

    created = False
    try:
        async with owner.begin() as con:
            await con.execute(text(f"CREATE SCHEMA {s}"))
            await con.execute(text(f"REVOKE ALL ON SCHEMA {s} FROM PUBLIC"))
            await con.execute(text(f"GRANT USAGE ON SCHEMA {s} TO lms_app"))
            await con.execute(text(f"CREATE TABLE {s}.tenants(id uuid PRIMARY KEY)"))
            await con.execute(text(f"INSERT INTO {s}.tenants VALUES(:tenant),(:other)"), {"tenant": tenant, "other": other_tenant})
            await con.execute(text(f"SET LOCAL search_path={s},public"))
            await con.run_sync(lambda c: Document.__table__.create(c, checkfirst=False))
            for doc_id, owner_id in [(document, tenant), (foreign_doc, other_tenant)]:
                await con.execute(text(f"""INSERT INTO {s}.documents(id,tenant_id,uploaded_by,title,content_type,content_sha256,file_size)
                    VALUES(:doc,:tenant,:actor,'Synthetic editorial QA','text/plain',:sha,100)"""),
                    {"doc": doc_id, "tenant": owner_id, "actor": actor, "sha": sha})
            await con.execute(text(f"ALTER TABLE {s}.documents ENABLE ROW LEVEL SECURITY"))
            await con.execute(text(f"ALTER TABLE {s}.documents FORCE ROW LEVEL SECURITY"))
            await con.execute(text(f"""CREATE POLICY owned ON {s}.documents FOR ALL TO lms_app
                USING(tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid)"""))
            await con.execute(text(f"GRANT SELECT,UPDATE ON {s}.documents TO lms_app"))
            await con.run_sync(migrate, schema, "upgrade")
            await con.run_sync(migrate, schema, "downgrade")
            assert await con.scalar(text("SELECT to_regclass(:table)"), {"table": f"{schema}.document_editorial_events"}) is None
            await con.run_sync(migrate, schema, "upgrade")
        created = True
        checks.append("upgrade_downgrade_reupgrade")
        async with sessions() as db:
            await scope(db, tenant)
            flags = (await db.execute(text("""SELECT current_user, r.rolbypassrls, c.relrowsecurity, c.relforcerowsecurity
              FROM pg_roles r, pg_class c WHERE r.rolname=current_user
              AND c.oid=to_regclass(:relation)"""), {"relation": f"{schema}.document_editorial_events"})).one()
            assert tuple(flags) == ("lms_app", False, True, True)
            doc = await owned_document(db, tenant, document, lock=True)
            for seq, kind, payload in [(1, "queued", {}), (2, "running", {}), (3, "analyzed", {
                "policy": POLICY, "original": original, "automatic": [], "issues": [
                    {"id": "boundary", "start": 0, "end": len(quote), "quote": quote, "reason": "Как учитывать 45 МРП?"}
                ],
            })]:
                add_event(db, doc, actor_id=actor, sequence=seq, kind=kind, payload=payload)
            await db.commit()
        checks.append("lms_app_non_bypass_force_rls")

        async def decision(request: ReviewCommand) -> str:
            async with sessions() as db:
                await scope(db, tenant)
                doc = await owned_document(db, tenant, document, lock=True)
                try:
                    await apply_command(db, doc, actor, request)
                    await db.commit()
                    return "applied"
                except ReviewConflictError as error:
                    return str(error)

        request = ReviewCommand(action="resolve", expected_revision=3, request_id=uuid4(), item_id="boundary",
                                decision="replace", replacement=replacement, reason="Owner confirmed the boundary.")
        race = await asyncio.gather(decision(request), decision(request.model_copy(update={"request_id": uuid4()})))
        assert sorted(race) == ["applied", "source_review_revision_conflict"]
        assert await decision(ReviewCommand(action="approve", expected_revision=4, request_id=uuid4())) == "applied"
        async with sessions() as db:
            await scope(db, tenant)
            pins = await pin_reviews(db, tenant, [document])
            approved = await resolve_pins(db, tenant, [str(document)], pins)
            assert approved[str(document)].working_text == original.replace(quote, replacement)
        assert await decision(ReviewCommand(action="reopen", expected_revision=5, request_id=uuid4())) == "applied"
        async with sessions() as db:
            await scope(db, tenant)
            assert len(await history(db, tenant, document)) == 6
            approved = await resolve_pins(db, tenant, [str(document)], pins)
            assert approved[str(document)].working_text == original.replace(quote, replacement)
        checks.extend(["one_winner_revision_cas", "historical_approval_pins_exact_working_text"])

        async with sessions() as db:
            await scope(db, other_tenant)
            assert not await history(db, other_tenant, document)
        for sql, scoped in [
            ("DELETE FROM document_editorial_events", tenant),
            ("UPDATE document_editorial_events SET payload='{}'", tenant),
            ("""INSERT INTO document_editorial_events
              (id,tenant_id,document_id,actor_id,sequence,kind,original_blob_sha256,payload)
              VALUES(:id,:tenant,:foreign_doc,:actor,1,'queued',:sha,'{}')""", tenant),
        ]:
            async with sessions() as db:
                await scope(db, scoped)
                try:
                    await db.execute(text(sql), {"id": uuid4(), "tenant": tenant, "foreign_doc": foreign_doc,
                                                 "actor": actor, "sha": sha})
                except DBAPIError as error:
                    assert getattr(error.orig, "sqlstate", None) == "42501"
                else:
                    raise AssertionError("unapproved_runtime_mutation_allowed")
        checks.extend(["other_tenant_no_read_or_write", "runtime_cannot_update_or_delete_history"])
    finally:
        if created:
            async with owner.begin() as con:
                if not re.fullmatch(r"editorial_dev_[0-9a-f]{12}", schema):
                    raise ValueError("unsafe_cleanup")
                await con.execute(text(f"DROP SCHEMA {s} CASCADE"))
                assert await con.scalar(text("SELECT to_regnamespace(:schema)"), {"schema": schema}) is None
        await runtime.dispose()
        await owner.dispose()
    assert await database_revision(owner_url) == before
    return {"status": "PASS", "checks": checks, "public_revision": before, "cleanup": created}


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(run())))
    except Exception as error:
        print(json.dumps({"status": "FAIL", "error_type": type(error).__name__}))
        raise SystemExit(1) from None
