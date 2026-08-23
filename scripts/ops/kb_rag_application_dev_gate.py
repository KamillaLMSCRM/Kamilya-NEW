#!/usr/bin/env python3
"""Run HBR-DEV-APP-02 inside one disposable Supabase dev schema.

This runner is inert without both ``--execute`` and the exact non-secret
approval identifier. It uses synthetic data only, never calls an AI provider,
emits sanitized aggregate evidence, and always attempts exact schema cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
for import_root in (REPO_ROOT, API_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from scripts.ops.kb_rag_isolated_dev_gate import (  # noqa: E402
    GateBlocked,
    alembic,
    assert_sanitized_evidence,
    digest_json,
    file_sha256,
    normalize_database_url,
    public_metadata_fingerprint,
    public_revision,
    same_supabase_project,
    scalar,
    supabase_project_ref,
)


APPROVAL_ID = "HBR-DEV-APP-02"
SCHEMA_RE = re.compile(r"^hbr_kb_app_[0-9a-f]{12}$")
SQLSTATE_RE = re.compile(r"^[0-9A-Z]{5}$")
SAFE_ERROR_DETAIL_RE = re.compile(r"^[a-z0-9_:-]{1,96}$")
SAFE_DOMAIN_ERROR_CLASSES = {
    "EmbeddingReindexPersistenceError",
    "ReindexLifecycleError",
}
MIGRATIONS = tuple(
    API_ROOT / "alembic" / "versions" / name
    for name in (
        "0128_add_embedding_provenance.py",
        "0129_add_embedding_chunk_index.py",
        "0130_add_document_embedding_fts.py",
        "0131_add_embedding_reindex_lifecycle.py",
    )
)


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_application_schema_name")
    return value


async def set_search_path(connection, schema: str) -> None:
    safe_schema_name(schema)
    await connection.execute(
        text(f'SET search_path TO "{schema}", extensions, public, pg_catalog')
    )


def assert_migration_sources_are_schema_neutral() -> None:
    for path in MIGRATIONS:
        source = path.read_text(encoding="utf-8").lower()
        if "public." in source or 'schema="public"' in source or "schema='public'" in source:
            raise GateBlocked(f"hard_coded_public_schema:{path.name}")


def _sanitized_exception(exc: Exception) -> str:
    """Return an operation-safe exception token without database messages."""
    if isinstance(exc, GateBlocked) and exc.args:
        return str(exc.args[0])
    token = type(exc).__name__
    if (
        token in SAFE_DOMAIN_ERROR_CLASSES
        and exc.args
        and isinstance(exc.args[0], str)
        and SAFE_ERROR_DETAIL_RE.fullmatch(exc.args[0])
    ):
        return f"{token}:{exc.args[0]}"
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(exc, "sqlstate", None)
    if isinstance(sqlstate, str) and SQLSTATE_RE.fullmatch(sqlstate.upper()):
        token = f"{token}:sqlstate={sqlstate.upper()}"
    return token


async def cleanup(engine: Any, schema: str) -> bool:
    safe_schema_name(schema)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await connection.commit()
            exists = await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            )
            return not bool(exists)
    except Exception:
        return False


def _content_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _target_fingerprint(
    *, project_ref: str, database: str, postgresql_major: int, pgvector_version: str
) -> str:
    return digest_json(
        {
            "project_ref_sha256": hashlib.sha256(project_ref.encode("ascii")).hexdigest(),
            "database": database,
            "postgresql_major": postgresql_major,
            "pgvector_version": pgvector_version,
        }
    )


def _restore_application_overrides(
    db_module, config_module, original_factory, original_get_settings
) -> None:
    db_module.async_session_factory = original_factory
    config_module.get_settings = original_get_settings


def _embedding_batch(vectors: tuple[tuple[float, ...], ...]):
    from app.modules.ai.embedding_space import EmbeddingSpace
    from app.modules.ai.llm_client import EmbeddingBatchResult

    return EmbeddingBatchResult(
        space=EmbeddingSpace(
            provider="synthetic-provider",
            model="synthetic-model",
            revision="synthetic-r1",
            dimensions=4,
        ),
        native_dimensions=4,
        storage_dimensions=4,
        vectors=vectors,
    )


def _candidate_chunks(document_id: str, source_revision: str) -> list[dict[str, Any]]:
    texts = (
        "Синтетический вводный раздел по безопасной работе.",
        "Синтетический основной раздел с проверяемым правилом.",
        "Синтетический итоговый раздел для контекстного окна.",
    )
    return [
        {
            "text": value,
            "metadata": {
                "doc_id": document_id,
                "doc_name": "synthetic-source.md",
                "headings": json.dumps(["Synthetic heading"], ensure_ascii=True),
                "source_revision": source_revision,
                "chunk_index": index,
            },
        }
        for index, value in enumerate(texts)
    ]


def _manifest(chunks: list[dict[str, Any]]):
    from app.modules.ai.embedding_reindex_lifecycle import ChunkManifestEntry

    return tuple(
        ChunkManifestEntry(
            chunk_id=f"candidate-{item['metadata']['chunk_index']}",
            chunk_index=item["metadata"]["chunk_index"],
            content_sha256=_content_sha(item["text"]),
        )
        for item in chunks
    )


def _evidence_for(manifest_item, run):
    from app.modules.ai.embedding_reindex_lifecycle import IndexedChunkEvidence

    return IndexedChunkEvidence(
        chunk_id=manifest_item.chunk_id,
        chunk_index=manifest_item.chunk_index,
        content_sha256=manifest_item.content_sha256,
        source_revision=run.candidate.source_revision,
        space=run.candidate.space,
    )


async def _bootstrap_schema(connection, schema: str) -> None:
    operations = (
        ("create_schema", text(f'CREATE SCHEMA "{schema}"')),
        (
            "create_documents",
            text(
                f'CREATE TABLE "{schema}".documents ('
                "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, content_sha256 text NOT NULL)"
            ),
        ),
        (
            "create_document_embeddings",
            text(
                f'CREATE TABLE "{schema}".document_embeddings ('
                "id text PRIMARY KEY, tenant_id uuid NOT NULL, doc_id text NOT NULL, "
                "doc_name text, text text NOT NULL, headings jsonb, embedding vector(4) NOT NULL)"
            ),
        ),
        (
            "create_alembic_version",
            text(f'CREATE TABLE "{schema}".alembic_version (version_num varchar(32) PRIMARY KEY)'),
        ),
        (
            "seed_alembic_version",
            text(f'INSERT INTO "{schema}".alembic_version(version_num) VALUES (\'0127\')'),
        ),
    )
    try:
        await connection.execute(operations[0][1])
        await set_search_path(connection, schema)
        for operation, statement in operations[1:]:
            try:
                await connection.execute(statement)
            except Exception as exc:
                raise GateBlocked(
                    f"bootstrap_{operation}:{_sanitized_exception(exc)}"
                ) from None
        await connection.commit()
    except GateBlocked:
        raise
    except Exception as exc:
        raise GateBlocked(
            f"bootstrap_{operations[0][0]}:{_sanitized_exception(exc)}"
        ) from None


async def _seed_synthetic_active(
    connection,
    schema: str,
    *,
    tenant_a: uuid.UUID,
    tenant_b: uuid.UUID,
    doc_a: uuid.UUID,
    doc_b: uuid.UUID,
) -> None:
    await set_search_path(connection, schema)
    await connection.execute(
        text(
            f'INSERT INTO "{schema}".documents(id, tenant_id, content_sha256) '
            "VALUES (:doc_a, :tenant_a, :sha_a), (:doc_b, :tenant_b, :sha_b)"
        ),
        {
            "doc_a": doc_a,
            "tenant_a": tenant_a,
            "sha_a": "a" * 64,
            "doc_b": doc_b,
            "tenant_b": tenant_b,
            "sha_b": "b" * 64,
        },
    )
    for index, value in enumerate(("Старый активный раздел один.", "Старый активный раздел два.")):
        await connection.execute(
            text(
                f'INSERT INTO "{schema}".document_embeddings ('
                "id, tenant_id, doc_id, doc_name, text, headings, embedding, "
                "embedding_provider, embedding_model, embedding_revision, "
                "embedding_native_dimensions, embedding_storage_dimensions, "
                "embedding_content_sha256, embedding_source_revision, "
                "embedding_indexed_at, embedding_provenance_state, chunk_index) "
                "VALUES (:id, :tenant, :doc, 'synthetic-source.md', :body, "
                "'[\"Synthetic heading\"]'::jsonb, '[0,1,0,0]', "
                "'synthetic-provider', 'synthetic-model', 'synthetic-r1', 4, 4, "
                ":content_sha, :source_revision, NOW(), 'verified', :chunk_index)"
            ),
            {
                "id": f"old-{index}",
                "tenant": tenant_a,
                "doc": doc_a,
                "body": value,
                "content_sha": _content_sha(value),
                "source_revision": f"document:{'a' * 64}",
                "chunk_index": index,
            },
        )
    tenant_b_text = "Синтетический изолированный раздел tenant B."
    await connection.execute(
        text(
            f'INSERT INTO "{schema}".document_embeddings ('
            "id, tenant_id, doc_id, doc_name, text, headings, embedding, "
            "embedding_provider, embedding_model, embedding_revision, "
            "embedding_native_dimensions, embedding_storage_dimensions, "
            "embedding_content_sha256, embedding_source_revision, "
            "embedding_indexed_at, embedding_provenance_state, chunk_index) "
            "VALUES ('tenant-b-old', :tenant, :doc, 'synthetic-b.md', :body, "
            "'[\"Synthetic B\"]'::jsonb, '[0,0,1,0]', "
            "'synthetic-provider', 'synthetic-model', 'synthetic-r1', 4, 4, "
            ":content_sha, :source_revision, NOW(), 'verified', 0)"
        ),
        {
            "tenant": tenant_b,
            "doc": doc_b,
            "body": tenant_b_text,
            "content_sha": _content_sha(tenant_b_text),
            "source_revision": f"document:{'b' * 64}",
        },
    )
    # PostgreSQL refuses ALTER TABLE while deferred FK trigger events from the
    # synthetic seed are still pending in the current transaction.
    await connection.commit()
    await set_search_path(connection, schema)
    await connection.execute(text(f'ALTER TABLE "{schema}".document_embeddings ENABLE ROW LEVEL SECURITY'))
    await connection.execute(text(f'ALTER TABLE "{schema}".document_embeddings FORCE ROW LEVEL SECURITY'))
    await connection.execute(
        text(
            f'CREATE POLICY hbr_app_embedding_tenant ON "{schema}".document_embeddings '
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
    )
    await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO authenticated'))
    await connection.execute(text(f'GRANT SELECT ON "{schema}".documents TO authenticated'))
    for table_name in (
        "document_embeddings",
        "embedding_active_revisions",
        "embedding_reindex_runs",
        "embedding_reindex_events",
    ):
        await connection.execute(
            text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".{table_name} TO authenticated')
        )
    await connection.commit()


def _make_application_session_factory(engine, schema: str):
    safe_schema_name(schema)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def factory():
        async with maker() as session:
            await session.execute(
                text(
                    f'SET LOCAL search_path TO "{schema}", extensions, public, pg_catalog'
                )
            )
            await session.execute(text("SET LOCAL ROLE authenticated"))
            try:
                yield session
            finally:
                if session.in_transaction():
                    await session.rollback()

    return factory


async def _persist(repository, session_factory, *, before, after) -> None:
    async with session_factory() as session:
        await repository.persist_transition(session, before=before, after=after)
        await session.commit()


async def _load(repository, session_factory, run):
    async with session_factory() as session:
        return await repository.load(
            session,
            tenant_id=run.tenant_id,
            document_id=run.document_id,
            run_id=run.run_id,
        )


async def _competing_transition(repository, session_factory, *, before, after):
    from app.modules.ai.embedding_reindex_store import EmbeddingReindexPersistenceError

    try:
        await _persist(repository, session_factory, before=before, after=after)
        return "won"
    except (EmbeddingReindexPersistenceError, IntegrityError):
        return "rejected"


async def _assert_writer_path(store, active_rows, *, tenant_id: str, document_id: str) -> bool:
    from app.modules.ai import writer as writer_module
    from app.modules.ai.writer import RetrievedChunk, write_lesson

    anchor_text, anchor_meta = active_rows[1]
    hit = RetrievedChunk(
        chunk_id=anchor_meta["chunk_id"],
        doc_id=document_id,
        tenant_id=tenant_id,
        doc_name=anchor_meta["doc_name"],
        headings=["Synthetic heading"],
        text=anchor_text,
        query="synthetic query",
        distance=0.1,
        embedding_provider=anchor_meta["embedding_provider"],
        embedding_model=anchor_meta["embedding_model"],
        embedding_revision=anchor_meta["embedding_revision"],
        embedding_native_dimensions=anchor_meta["embedding_native_dimensions"],
        embedding_storage_dimensions=anchor_meta["embedding_storage_dimensions"],
        content_sha256=anchor_meta["embedding_content_sha256"],
        source_revision=anchor_meta["embedding_source_revision"],
        indexed_at=anchor_meta["embedding_indexed_at"],
        chunk_index=anchor_meta["chunk_index"],
    )

    async def synthetic_retrieval(*_args, **_kwargs):
        return [hit]

    class SyntheticLLM:
        def __init__(self):
            self.messages = None

        async def ainvoke(self, messages):
            self.messages = messages
            return type("SyntheticResponse", (), {"content": "# Synthetic lesson"})()

    original_retrieval = writer_module._retrieve_and_rerank
    llm = SyntheticLLM()
    try:
        writer_module._retrieve_and_rerank = synthetic_retrieval
        lesson = await write_lesson(
            llm=llm,
            store=store,
            lesson_title="Synthetic lesson",
            objectives=["Synthetic objective"],
            module_title="Synthetic module",
            course_title="Synthetic course",
            doc_ids=[document_id],
            tenant_id=tenant_id,
            language="ru",
            require_sources=True,
        )
    finally:
        writer_module._retrieve_and_rerank = original_retrieval

    prompt = llm.messages[0]["content"]
    if len(prompt) > writer_module.MAX_WRITER_PROMPT_CHARS:
        raise GateBlocked("writer_prompt_budget_failed")
    references = lesson.source_references
    rendered = json.dumps(references, ensure_ascii=True, sort_keys=True).lower()
    forbidden = (
        "tenant_id",
        "chunk_id",
        "source_revision",
        "embedding_provider",
        "embedding_model",
        "embedding_revision",
        "content_sha256",
        "indexed_at",
    )
    if any(value in rendered for value in forbidden):
        raise GateBlocked("writer_reference_projection_failed")
    if not references or set(references[0]) != {"document", "headings", "context_sections"}:
        raise GateBlocked("writer_reference_shape_failed")
    return True


async def run_gate(database_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    safe_schema_name(schema)
    assert_migration_sources_are_schema_neutral()
    if not same_supabase_project(database_url, supabase_url):
        raise GateBlocked("database_and_supabase_project_mismatch")
    project_ref = supabase_project_ref(supabase_url)

    from app.modules.ai.embedding_reindex_lifecycle import (
        ReindexLifecycleError,
        RevisionBinding,
        activate_candidate,
        finalize_cleanup,
        record_indexed_batch,
        rollback_cutover,
        stage_reindex,
    )
    from app.modules.ai.embedding_reindex_store import (
        EmbeddingReindexPersistenceError,
        EmbeddingReindexRepository,
    )
    from app.modules.ai.embedding_space import EmbeddingSpace
    from app.modules.ai.ingestion import VectorStore
    import app.core.config as config_module
    import app.core.db as db_module

    engine = create_async_engine(database_url, pool_pre_ping=True)
    started_at = datetime.now(UTC)
    checks: dict[str, Any] = {}
    stage = "preflight"
    cleanup_ok = False
    public_before = ""
    public_after = ""
    public_cleanup_readback = "not_verified"
    failure_detail: str | None = None
    target_fingerprint = ""
    original_factory = db_module.async_session_factory
    original_get_settings = config_module.get_settings
    session_factory = None
    try:
        async with engine.connect() as connection:
            database_name = str(await scalar(connection, "SELECT current_database()"))
            server_major = int(await scalar(connection, "SHOW server_version_num")) // 10000
            vector_version = str(
                await scalar(
                    connection,
                    "SELECT extversion FROM pg_extension WHERE extname='vector'",
                )
            )
            revision_before = await public_revision(connection)
            public_before = await public_metadata_fingerprint(connection)
            roles_ready = bool(
                await scalar(
                    connection,
                    "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated')",
                )
            )
            residual = int(
                await scalar(
                    connection,
                    "SELECT count(*) FROM pg_namespace "
                    "WHERE nspname LIKE 'hbr\\_kb\\_app\\_%' ESCAPE '\\'",
                )
            )
            if database_name != "postgres":
                raise GateBlocked("unexpected_database_name")
            if server_major != 17:
                raise GateBlocked("unexpected_postgresql_major")
            if revision_before != "0127":
                raise GateBlocked("unexpected_public_alembic_revision")
            if not vector_version or not roles_ready:
                raise GateBlocked("required_dev_runtime_identity_missing")
            if residual:
                raise GateBlocked("residual_application_schema_present")
            target_fingerprint = _target_fingerprint(
                project_ref=project_ref,
                database=database_name,
                postgresql_major=server_major,
                pgvector_version=vector_version,
            )
            checks.update(
                {
                    "target_supabase_dev_identity": True,
                    "postgresql_major": server_major,
                    "pgvector_present": True,
                    "public_revision_before": revision_before,
                    "migration_sources_schema_neutral": True,
                    "residual_application_schema_absent": True,
                }
            )

            stage = "bootstrap_disposable_schema"
            await _bootstrap_schema(connection, schema)
            await set_search_path(connection, schema)
            stage = "upgrade_0127_to_0131"
            await alembic(connection, "upgrade", "0131")
            await connection.commit()
            revision_0131 = str(
                await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')
            )
            if revision_0131 != "0131":
                raise GateBlocked("disposable_upgrade_0131_failed")

            tenant_a = uuid.uuid4()
            tenant_b = uuid.uuid4()
            doc_a = uuid.uuid4()
            doc_b = uuid.uuid4()
            stage = "seed_synthetic_active"
            await _seed_synthetic_active(
                connection,
                schema,
                tenant_a=tenant_a,
                tenant_b=tenant_b,
                doc_a=doc_a,
                doc_b=doc_b,
            )
            rls_rows = (
                await connection.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname IN "
                        "('embedding_active_revisions','embedding_reindex_runs','embedding_reindex_events')"
                    ),
                    {"schema": schema},
                )
            ).all()
            if len(rls_rows) != 3 or any(not bool(row[1]) or not bool(row[2]) for row in rls_rows):
                raise GateBlocked("lifecycle_force_rls_missing")
            checks["migration_0131_and_force_rls"] = True

        session_factory = _make_application_session_factory(engine, schema)
        db_module.async_session_factory = session_factory
        config_module.get_settings = lambda: type(
            "SyntheticSettings", (), {"EMBEDDING_DIMENSIONS": 4}
        )()
        repository = EmbeddingReindexRepository()
        store = VectorStore()
        space = EmbeddingSpace(
            provider="synthetic-provider",
            model="synthetic-model",
            revision="synthetic-r1",
            dimensions=4,
        )
        source_a = f"document:{'a' * 64}"
        source_b = f"document:{'b' * 64}"
        chunks = _candidate_chunks(str(doc_a), source_a)
        manifest = _manifest(chunks)
        active_binding = RevisionBinding(
            revision_id="active-r1",
            source_revision=source_a,
            space=space,
            manifest_sha256="f" * 64,
        )
        run = stage_reindex(
            tenant_id=str(tenant_a),
            document_id=str(doc_a),
            run_id="run-a",
            active=active_binding,
            candidate_revision_id="candidate-r2",
            candidate_source_revision=source_a,
            candidate_space=space,
            manifest=manifest,
        )

        stage = "tenant_context_precondition"
        async with session_factory() as session:
            await repository._set_tenant(session, str(tenant_b))
            tenant_context_ready = bool(
                (
                    await session.execute(
                        text(
                            "SELECT current_setting('app.tenant_id', true) "
                            "= CAST(:tenant_id AS text)"
                        ),
                        {"tenant_id": str(tenant_b)},
                    )
                ).scalar_one()
            )
            matching_active_seed = int(
                (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM document_embeddings "
                            "WHERE tenant_id=CAST(:tenant_id AS uuid) "
                            "AND doc_id=CAST(:document_id AS text) "
                            "AND embedding_index_revision_id IS NULL "
                            "AND embedding_reindex_run_id IS NULL "
                            "AND embedding_provenance_state='verified' "
                            "AND embedding_source_revision=:source_revision"
                        ),
                        {
                            "tenant_id": str(tenant_b),
                            "document_id": str(doc_b),
                            "source_revision": source_b,
                        },
                    )
                ).scalar_one()
            )
            await session.rollback()
        if not tenant_context_ready:
            raise GateBlocked("tenant_context_not_set")
        if matching_active_seed != 1:
            raise GateBlocked(f"tenant_active_seed_match_count:{matching_active_seed}")
        checks["authenticated_tenant_context_and_seed_visibility"] = True

        stage = "transaction_rollback_injection"
        run_b = stage_reindex(
            tenant_id=str(tenant_b),
            document_id=str(doc_b),
            run_id="run-b",
            active=RevisionBinding(
                revision_id="active-b1",
                source_revision=source_b,
                space=space,
                manifest_sha256="e" * 64,
            ),
            candidate_revision_id="candidate-b2",
            candidate_source_revision=source_b,
            candidate_space=space,
            manifest=(_manifest(_candidate_chunks(str(doc_b), source_b))[0],),
        )
        async with session_factory() as session:
            try:
                await repository.stage(session, run_b)
                raise GateBlocked("injected_post_stage_failure")
            except GateBlocked as exc:
                if str(exc) != "injected_post_stage_failure":
                    raise
                await session.rollback()
        async with engine.connect() as connection:
            rollback_residue = int(
                await scalar(
                    connection,
                    f"SELECT (SELECT count(*) FROM \"{schema}\".embedding_active_revisions "
                    "WHERE document_id=:doc) + "
                    f"(SELECT count(*) FROM \"{schema}\".embedding_reindex_runs WHERE document_id=:doc) + "
                    f"(SELECT count(*) FROM \"{schema}\".document_embeddings "
                    "WHERE doc_id=:doc AND embedding_index_revision_id IS NOT NULL)",
                    doc=doc_b,
                )
            )
        if rollback_residue != 0:
            raise GateBlocked("stage_transaction_rollback_failed")
        checks["injected_stage_transaction_rollback"] = True

        stage = "stage_active_revision"
        async with session_factory() as session:
            await repository.stage(session, run)
            await session.commit()

        stage = "duplicate_open_run"
        duplicate = stage_reindex(
            tenant_id=str(tenant_a),
            document_id=str(doc_a),
            run_id="run-a-duplicate",
            active=active_binding,
            candidate_revision_id="candidate-r3",
            candidate_source_revision=source_a,
            candidate_space=space,
            manifest=manifest,
        )
        duplicate_rejected = False
        async with session_factory() as session:
            try:
                await repository.stage(session, duplicate)
                await session.commit()
            except IntegrityError:
                duplicate_rejected = True
                await session.rollback()
        if not duplicate_rejected:
            raise GateBlocked("duplicate_open_run_not_rejected")
        checks["single_open_run_enforced"] = True

        stage = "write_partial_candidate"
        await store.add_chunks(
            chunks[:1],
            _embedding_batch(((1.0, 0.0, 0.0, 0.0),)),
            tenant_id=str(tenant_a),
            index_revision_id=run.candidate.revision_id,
            reindex_run_id=run.run_id,
        )
        running_a = record_indexed_batch(
            run,
            (_evidence_for(manifest[0], run),),
            event_id="partial-a",
            expected_generation=0,
        )
        running_b = record_indexed_batch(
            run,
            (_evidence_for(manifest[0], run),),
            event_id="partial-b",
            expected_generation=0,
        )
        race = await asyncio.gather(
            _competing_transition(repository, session_factory, before=run, after=running_a),
            _competing_transition(repository, session_factory, before=run, after=running_b),
        )
        if sorted(race) != ["rejected", "won"]:
            raise GateBlocked("event_generation_or_run_cas_failed")
        running = await _load(repository, session_factory, run)
        visible_before = await store.get_all_chunks(
            doc_ids=[str(doc_a)], tenant_id=str(tenant_a)
        )
        if len(visible_before) != 2 or any(item[0] == chunks[0]["text"] for item in visible_before):
            raise GateBlocked("partial_candidate_visibility_failed")
        try:
            activate_candidate(
                running,
                event_id="early-activation",
                expected_generation=running.generation,
                expected_candidate_revision_id=running.candidate.revision_id,
                expected_manifest_sha256=running.candidate.manifest_sha256,
            )
        except ReindexLifecycleError:
            pass
        else:
            raise GateBlocked("partial_candidate_activated")
        checks["partial_candidate_invisible_and_cannot_activate"] = True
        checks["concurrent_event_generation_cas"] = True

        stage = "complete_candidate"
        await store.add_chunks(
            chunks[1:],
            _embedding_batch(
                (
                    (0.9, 0.1, 0.0, 0.0),
                    (0.8, 0.2, 0.0, 0.0),
                )
            ),
            tenant_id=str(tenant_a),
            index_revision_id=run.candidate.revision_id,
            reindex_run_id=run.run_id,
        )
        ready = record_indexed_batch(
            running,
            tuple(_evidence_for(item, running) for item in manifest[1:]),
            event_id="complete-candidate",
            expected_generation=running.generation,
        )
        await _persist(repository, session_factory, before=running, after=ready)

        active_a = activate_candidate(
            ready,
            event_id="activate-a",
            expected_generation=ready.generation,
            expected_candidate_revision_id=ready.candidate.revision_id,
            expected_manifest_sha256=ready.candidate.manifest_sha256,
        )
        active_b = activate_candidate(
            ready,
            event_id="activate-b",
            expected_generation=ready.generation,
            expected_candidate_revision_id=ready.candidate.revision_id,
            expected_manifest_sha256=ready.candidate.manifest_sha256,
        )
        activation_race = await asyncio.gather(
            _competing_transition(repository, session_factory, before=ready, after=active_a),
            _competing_transition(repository, session_factory, before=ready, after=active_b),
        )
        if sorted(activation_race) != ["rejected", "won"]:
            raise GateBlocked("activation_cas_failed")
        active = await _load(repository, session_factory, run)
        checks["atomic_activation_cas"] = True

        stage = "application_retrieval_readback"
        active_rows = await store.get_all_chunks(
            doc_ids=[str(doc_a)], tenant_id=str(tenant_a)
        )
        active_rows.sort(key=lambda item: item[1]["chunk_index"])
        if [item[0] for item in active_rows] != [item["text"] for item in chunks]:
            raise GateBlocked("active_revision_corpus_readback_failed")
        stage = "semantic_retrieval_readback"
        semantic = await store.query(
            _embedding_batch(((1.0, 0.0, 0.0, 0.0),)),
            where={"doc_id": str(doc_a)},
            tenant_id=str(tenant_a),
        )
        stage = "fts_retrieval_readback"
        lexical = await store.search_full_text(
            query_text="синтетический раздел",
            tenant_id=str(tenant_a),
            doc_ids=[str(doc_a)],
        )
        stage = "context_retrieval_readback"
        context = await store.get_context_window(
            doc_id=str(doc_a),
            source_revision=source_a,
            chunk_index=1,
            radius=1,
            tenant_id=str(tenant_a),
        )
        if (
            len(semantic["documents"][0]) != 3
            or len(lexical) < 1
            or len(context) != 3
            or any(item[1]["tenant_id"] != str(tenant_a) for item in context)
        ):
            raise GateBlocked("application_retrieval_path_failed")
        checks["semantic_fts_corpus_context_active_only"] = True

        stage = "writer_context_and_citations"
        checks["writer_context_budget_and_safe_citations"] = await _assert_writer_path(
            store,
            active_rows,
            tenant_id=str(tenant_a),
            document_id=str(doc_a),
        )

        stage = "tenant_rls_negatives"
        async with session_factory() as session:
            await session.execute(
                text("SELECT set_current_tenant(:tenant_id)"),
                {"tenant_id": str(tenant_b)},
            )
            lifecycle_leak = int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM embedding_reindex_runs")
                    )
                ).scalar_one()
            )
            await session.rollback()
        async with session_factory() as session:
            no_tenant_visible = int(
                (
                    await session.execute(
                        text("SELECT count(*) FROM embedding_reindex_runs")
                    )
                ).scalar_one()
            )
            await session.rollback()
        if lifecycle_leak != 0 or no_tenant_visible != 0:
            raise GateBlocked("lifecycle_rls_read_isolation_failed")
        cross_tenant_write_denied = False
        async with session_factory() as session:
            await session.execute(
                text("SELECT set_current_tenant(:tenant_id)"),
                {"tenant_id": str(tenant_a)},
            )
            try:
                await session.execute(
                    text(
                        "INSERT INTO embedding_reindex_runs ("
                        "tenant_id, document_id, run_id, state, generation, "
                        "active_revision_id, candidate_revision_id, candidate_manifest_sha256, "
                        "expected_chunk_count, completed_chunk_count, lifecycle_payload) "
                        "VALUES (CAST(:tenant_b AS uuid), CAST(:doc_b AS text), 'cross-tenant', "
                        "'staged', 0, 'active-b', 'candidate-b', :manifest_sha, 1, 0, '{}'::jsonb)"
                    ),
                    {
                        "tenant_b": str(tenant_b),
                        "doc_b": str(doc_b),
                        "manifest_sha": "d" * 64,
                    },
                )
                await session.commit()
            except Exception:
                cross_tenant_write_denied = True
                await session.rollback()
        if not cross_tenant_write_denied:
            raise GateBlocked("cross_tenant_lifecycle_write_allowed")
        try:
            async with session_factory() as session:
                await repository.load(
                    session,
                    tenant_id=str(tenant_b),
                    document_id=str(doc_a),
                    run_id=run.run_id,
                )
        except EmbeddingReindexPersistenceError:
            pass
        else:
            raise GateBlocked("cross_tenant_lifecycle_read_allowed")
        checks["lifecycle_force_rls_read_write_and_no_tenant_negatives"] = True

        stage = "rollback_and_cleanup"
        rolled_back = rollback_cutover(
            active,
            event_id="rollback",
            expected_generation=active.generation,
        )
        await _persist(repository, session_factory, before=active, after=rolled_back)
        restored = await store.get_all_chunks(
            doc_ids=[str(doc_a)], tenant_id=str(tenant_a)
        )
        if len(restored) != 2 or any(item[0] in {chunk["text"] for chunk in chunks} for item in restored):
            raise GateBlocked("rollback_visibility_failed")
        cleaned, directive = finalize_cleanup(
            rolled_back,
            event_id="cleanup",
            expected_generation=rolled_back.generation,
        )
        await _persist(repository, session_factory, before=rolled_back, after=cleaned)
        async with session_factory() as session:
            deleted = await repository.cleanup(session, run=cleaned, directive=directive)
            await session.commit()
        if deleted != len(chunks):
            raise GateBlocked("candidate_cleanup_count_failed")
        checks["rollback_restored_old_active"] = True
        checks["exact_nonactive_revision_cleanup"] = True

        _restore_application_overrides(
            db_module,
            config_module,
            original_factory,
            original_get_settings,
        )
        session_factory = None

        stage = "downgrade_reupgrade_and_shared_readback"
        async with engine.connect() as connection:
            await set_search_path(connection, schema)
            await alembic(connection, "downgrade", "0127")
            await connection.commit()
            if str(await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')) != "0127":
                raise GateBlocked("disposable_downgrade_failed")
            await set_search_path(connection, schema)
            await alembic(connection, "upgrade", "0131")
            await connection.commit()
            if str(await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')) != "0131":
                raise GateBlocked("disposable_reupgrade_failed")
            public_after = await public_metadata_fingerprint(connection)
            revision_after = await public_revision(connection)
        if public_after != public_before or revision_after != "0127":
            raise GateBlocked("shared_public_state_changed")
        checks["upgrade_downgrade_reupgrade_0127_0131"] = True
        checks["shared_public_revision_and_metadata_unchanged"] = True
    except Exception as exc:
        failure_detail = f"stage={stage};cause={_sanitized_exception(exc)}"
    finally:
        _restore_application_overrides(
            db_module,
            config_module,
            original_factory,
            original_get_settings,
        )
        cleanup_ok = await cleanup(engine, schema)
        if public_before:
            try:
                async with engine.connect() as connection:
                    cleanup_revision = await public_revision(connection)
                    cleanup_fingerprint = await public_metadata_fingerprint(connection)
                public_cleanup_readback = (
                    "unchanged"
                    if cleanup_revision == "0127" and cleanup_fingerprint == public_before
                    else "changed"
                )
            except Exception:
                public_cleanup_readback = "not_verified"
        await engine.dispose()

    if failure_detail is not None:
        raise GateBlocked(
            f"{failure_detail};cleanup={'passed' if cleanup_ok else 'failed'};"
            f"shared_public={public_cleanup_readback}"
        )
    if not cleanup_ok:
        raise GateBlocked(f"cleanup_failed_at:{stage}")
    checks["disposable_schema_removed"] = True
    finished_at = datetime.now(UTC)
    evidence = {
        "evidence_id": f"HBR-DEV-APP-{started_at.strftime('%Y%m%dT%H%M%SZ')}",
        "gate_id": APPROVAL_ID,
        "status": "READY",
        "evidence_label": "RUNTIME-DERIVED",
        "scope": "isolated_supabase_dev_application_path",
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "finished_at": finished_at.isoformat().replace("+00:00", "Z"),
        "target_fingerprint": target_fingerprint,
        "source_digests": {
            path.name: file_sha256(path) for path in (*MIGRATIONS, Path(__file__))
        },
        "checks": checks,
        "cleanup": "passed",
    }
    assert_sanitized_evidence(evidence)
    return evidence


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-id", default="")
    parser.add_argument("--evidence-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}))
        return 2
    if args.approval_id != APPROVAL_ID:
        print(json.dumps({"status": "BLOCKED", "error_class": "approval_id_required"}))
        return 2
    load_dotenv(args.env_file, override=False)
    database_url = normalize_database_url(
        os.environ.get("MIGRATION_DATABASE_URL", "")
        or os.environ.get("DATABASE_URL", "")
    )
    supabase_url = os.environ.get("SUPABASE_URL", "")
    if not database_url or not supabase_url:
        print(json.dumps({"status": "BLOCKED", "error_class": "required_env_missing"}))
        return 2
    schema = f"hbr_kb_app_{uuid.uuid4().hex[:12]}"
    try:
        evidence = asyncio.run(run_gate(database_url, supabase_url, schema))
    except Exception as exc:
        detail = exc.args[0] if isinstance(exc, GateBlocked) and exc.args else "sanitized"
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "error_class": type(exc).__name__,
                    "stage_detail": detail,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 1
    if args.evidence_file:
        output_path = args.evidence_file.resolve()
        if REPO_ROOT.resolve() not in output_path.parents:
            print(json.dumps({"status": "BLOCKED", "error_class": "unsafe_evidence_path"}))
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
