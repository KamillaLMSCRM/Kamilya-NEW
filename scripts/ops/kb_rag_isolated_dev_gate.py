#!/usr/bin/env python3
"""Run the HBR PostgreSQL gate in a disposable Supabase dev schema.

The command is fail-closed: it never targets ``public``, never copies tenant
data, emits only sanitized aggregate evidence, and always attempts to drop the
schema it created. Database credentials are loaded process-locally and are
never rendered in output or exceptions.
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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

SCHEMA_RE = re.compile(r"^hbr_kb_[0-9a-f]{12}$")
EXPECTED_MIGRATIONS = (
    API_ROOT / "alembic" / "versions" / "0128_add_embedding_provenance.py",
    API_ROOT / "alembic" / "versions" / "0129_add_embedding_chunk_index.py",
    API_ROOT / "alembic" / "versions" / "0130_add_document_embedding_fts.py",
)
PROVENANCE_COLUMNS = {
    "embedding_provider",
    "embedding_model",
    "embedding_revision",
    "embedding_native_dimensions",
    "embedding_storage_dimensions",
    "embedding_content_sha256",
    "embedding_source_revision",
    "embedding_indexed_at",
    "embedding_provenance_state",
}


class GateBlocked(RuntimeError):
    """A fail-closed safety or evidence gate rejected execution."""


def safe_schema_name(value: str) -> str:
    if not SCHEMA_RE.fullmatch(value):
        raise GateBlocked("unsafe_schema_name")
    return value


def assert_migration_sources_are_schema_neutral() -> None:
    for path in EXPECTED_MIGRATIONS:
        source = path.read_text(encoding="utf-8").lower()
        if "public." in source or 'schema="public"' in source or "schema='public'" in source:
            raise GateBlocked(f"hard_coded_public_schema:{path.name}")


def same_supabase_project(database_url: str, supabase_url: str) -> bool:
    """Compare project refs without returning hosts, users, or credentials."""
    try:
        db = make_url(database_url)
        supabase_host = (urlsplit(supabase_url).hostname or "").lower()
        project_ref = supabase_host.split(".", 1)[0]
        db_identity = " ".join(
            str(part or "").lower() for part in (db.host, db.username)
        )
        return (
            len(project_ref) >= 8
            and supabase_host.endswith(".supabase.co")
            and project_ref in db_identity
        )
    except Exception:
        return False


def supabase_project_ref(supabase_url: str) -> str:
    host = (urlsplit(supabase_url).hostname or "").lower()
    project_ref = host.split(".", 1)[0]
    if len(project_ref) < 8 or not host.endswith(".supabase.co"):
        raise GateBlocked("invalid_supabase_project_identity")
    return project_ref


def normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


def summarize_plan(plan: Any) -> tuple[list[str], list[str]]:
    node_types: list[str] = []
    index_names: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            node_type = value.get("Node Type")
            index_name = value.get("Index Name")
            if isinstance(node_type, str):
                node_types.append(node_type)
            if isinstance(index_name, str):
                index_names.append(index_name)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(plan)
    return node_types, index_names


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_sanitized_evidence(value: dict[str, Any]) -> None:
    rendered = json.dumps(value, ensure_ascii=True, sort_keys=True).lower()
    forbidden = ("postgres://", "postgresql://", "password", "secret", "@")
    if any(token in rendered for token in forbidden):
        raise GateBlocked("evidence_contains_forbidden_material")


def make_alembic_config(connection: Connection) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.attributes["connection"] = connection
    return config


async def alembic(connection: AsyncConnection, operation: str, revision: str) -> None:
    def run(sync_connection: Connection) -> None:
        config = make_alembic_config(sync_connection)
        getattr(command, operation)(config, revision)

    await connection.run_sync(run)


async def scalar(connection: AsyncConnection, sql: str, **params: Any) -> Any:
    return (await connection.execute(text(sql), params)).scalar_one()


async def table_columns(connection: AsyncConnection, schema: str) -> set[str]:
    rows = await connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=:schema AND table_name='document_embeddings'"
        ),
        {"schema": schema},
    )
    return {str(row[0]) for row in rows}


async def public_metadata_fingerprint(connection: AsyncConnection) -> str:
    await connection.execute(text("SET LOCAL search_path TO pg_catalog, public"))
    columns = (
        await connection.execute(
            text(
                "SELECT table_name, column_name, data_type, is_nullable, "
                "COALESCE(column_default, '') FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND table_name IN ('documents','document_embeddings') "
                "ORDER BY table_name, ordinal_position"
            )
        )
    ).all()
    indexes = (
        await connection.execute(
            text(
                "SELECT tablename, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname='public' "
                "AND tablename IN ('documents','document_embeddings') "
                "ORDER BY tablename, indexname"
            )
        )
    ).all()
    constraints = (
        await connection.execute(
            text(
                "SELECT t.relname, c.conname, c.contype, c.convalidated, "
                "pg_get_constraintdef(c.oid) FROM pg_constraint c "
                "JOIN pg_class t ON t.oid=c.conrelid "
                "JOIN pg_namespace n ON n.oid=t.relnamespace "
                "WHERE n.nspname='public' "
                "AND t.relname IN ('documents','document_embeddings') "
                "ORDER BY t.relname, c.conname"
            )
        )
    ).all()
    return digest_json(
        {
            "columns": [[str(value) for value in row] for row in columns],
            "indexes": [[str(value) for value in row] for row in indexes],
            "constraints": [[str(value) for value in row] for row in constraints],
        }
    )


async def set_search_path(connection: AsyncConnection, schema: str) -> None:
    safe_schema_name(schema)
    await connection.execute(
        text(f'SET search_path TO "{schema}", extensions, public, pg_catalog')
    )


async def public_revision(connection: AsyncConnection) -> str:
    return str(
        await scalar(connection, "SELECT version_num FROM public.alembic_version")
    )


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


async def run_gate(database_url: str, supabase_url: str, schema: str) -> dict[str, Any]:
    safe_schema_name(schema)
    assert_migration_sources_are_schema_neutral()
    if not same_supabase_project(database_url, supabase_url):
        raise GateBlocked("database_and_supabase_project_mismatch")

    started_at = datetime.now(UTC)
    project_ref = supabase_project_ref(supabase_url)
    source_digests = {
        path.name: file_sha256(path) for path in EXPECTED_MIGRATIONS
    }
    source_digests[Path(__file__).name] = file_sha256(Path(__file__))

    engine = create_async_engine(database_url, pool_pre_ping=True)
    checks: dict[str, Any] = {}
    stage = "preflight"
    cleanup_ok = False
    failure: Exception | None = None
    try:
        async with engine.connect() as connection:
            db_name = str(await scalar(connection, "SELECT current_database()"))
            server_major = int(await scalar(connection, "SHOW server_version_num")) // 10000
            vector_version = str(
                await scalar(
                    connection,
                    "SELECT extversion FROM pg_extension WHERE extname='vector'",
                )
            )
            before_revision = await public_revision(connection)
            stage = "public_metadata_fingerprint_before"
            public_metadata_before = await public_metadata_fingerprint(connection)
            supabase_roles = bool(
                await scalar(
                    connection,
                    "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') "
                    "AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='supabase_admin')",
                )
            )
            if db_name != "postgres":
                raise GateBlocked("unexpected_database_name")
            if server_major != 17:
                raise GateBlocked("unexpected_postgresql_major")
            if before_revision != "0127":
                raise GateBlocked("unexpected_public_alembic_revision")
            if not supabase_roles:
                raise GateBlocked("supabase_role_identity_missing")
            if await scalar(
                connection,
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname=:schema)",
                schema=schema,
            ):
                raise GateBlocked("disposable_schema_already_exists")
            residual_count = int(
                await scalar(
                    connection,
                    "SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'hbr\\_kb\\_%' ESCAPE '\\'",
                )
            )
            if residual_count:
                raise GateBlocked("residual_disposable_schema_present")

            checks.update(
                {
                    "target_supabase_dev_identity": True,
                    "database_name_expected": True,
                    "postgresql_major": server_major,
                    "pgvector_version_present": bool(vector_version),
                    "public_revision_before": before_revision,
                    "migration_sources_schema_neutral": True,
                }
            )
            target_fingerprint = digest_json(
                {
                    "supabase_project_ref": project_ref,
                    "database": db_name,
                    "postgresql_major": server_major,
                    "pgvector_version": vector_version,
                }
            )

            stage = "create_disposable_schema"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            stage = "set_disposable_search_path"
            await set_search_path(connection, schema)
            stage = "create_synthetic_documents_table"
            await connection.execute(
                text(
                    f'CREATE TABLE "{schema}".documents ('
                    "id uuid PRIMARY KEY, tenant_id uuid NOT NULL, "
                    "content_sha256 text NOT NULL)"
                )
            )
            stage = "create_synthetic_embeddings_table"
            await connection.execute(
                text(
                    f'CREATE TABLE "{schema}".document_embeddings ('
                    "id text PRIMARY KEY, tenant_id uuid NOT NULL, doc_id uuid NOT NULL, "
                    "doc_name text, text text NOT NULL, headings jsonb, "
                    "embedding vector(4) NOT NULL)"
                )
            )
            stage = "create_disposable_alembic_table"
            await connection.execute(
                text(f'CREATE TABLE "{schema}".alembic_version (version_num varchar(32) PRIMARY KEY)')
            )
            stage = "stamp_disposable_0127"
            await connection.execute(
                text(f'INSERT INTO "{schema}".alembic_version(version_num) VALUES (\'0127\')')
            )
            stage = "seed_synthetic_documents"
            tenant_a = uuid.uuid4()
            tenant_b = uuid.uuid4()
            doc_a = uuid.uuid4()
            doc_b = uuid.uuid4()
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
                    "sha_b": "d" * 64,
                },
            )
            stage = "seed_legacy_embedding"
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".document_embeddings '
                    "(id, tenant_id, doc_id, doc_name, text, headings, embedding) "
                    "VALUES ('legacy', :tenant, :doc, 'Synthetic legacy', "
                    "'legacy synthetic content', '{}'::jsonb, '[0,0,0,0]')"
                ),
                {"tenant": tenant_a, "doc": doc_a},
            )
            stage = "commit_disposable_bootstrap"
            await connection.commit()

            stage = "upgrade_0128"
            await set_search_path(connection, schema)
            await alembic(connection, "upgrade", "0128")
            columns_0128 = await table_columns(connection, schema)
            if not PROVENANCE_COLUMNS.issubset(columns_0128):
                raise GateBlocked("provenance_columns_missing")
            legacy_state = str(
                await scalar(
                    connection,
                    f'SELECT embedding_provenance_state FROM "{schema}".document_embeddings '
                    "WHERE id='legacy'",
                )
            )
            if legacy_state == "verified":
                raise GateBlocked("legacy_row_misclassified")

            provenance_values = {
                "provider": "synthetic-provider",
                "model": "synthetic-model",
                "revision": "synthetic-r1",
                "native_dimensions": 4,
                "storage_dimensions": 4,
                "content_sha": "c" * 64,
                "source_revision": f"document:{'a' * 64}",
            }
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".document_embeddings ('
                    "id, tenant_id, doc_id, doc_name, text, headings, embedding, "
                    "embedding_provider, embedding_model, embedding_revision, "
                    "embedding_native_dimensions, embedding_storage_dimensions, "
                    "embedding_content_sha256, embedding_source_revision, "
                    "embedding_indexed_at, embedding_provenance_state) VALUES ("
                    "'pre0129', :tenant, :doc, 'Охрана труда', "
                    "'Синтетический вводный инструктаж по охране труда', '{}'::jsonb, "
                    "'[1,0,0,0]', :provider, :model, :revision, :native_dimensions, "
                    ":storage_dimensions, :content_sha, :source_revision, now(), 'verified')"
                ),
                {"tenant": tenant_a, "doc": doc_a, **provenance_values},
            )
            await connection.commit()

            stage = "upgrade_0129"
            await set_search_path(connection, schema)
            await alembic(connection, "upgrade", "0129")
            unvalidated = (
                await connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname=:schema AND t.relname='document_embeddings' "
                        "AND NOT c.convalidated ORDER BY c.conname"
                    ),
                    {"schema": schema},
                )
            ).scalars().all()
            if len(unvalidated) != 1 or not re.fullmatch(r"[a-zA-Z0-9_]+", unvalidated[0]):
                raise GateBlocked("unexpected_not_valid_constraint_set")
            await connection.execute(
                text(
                    f'UPDATE "{schema}".document_embeddings SET chunk_index=0 '
                    "WHERE id='pre0129'"
                )
            )
            await connection.execute(
                text(
                    f'ALTER TABLE "{schema}".document_embeddings '
                    f'VALIDATE CONSTRAINT "{unvalidated[0]}"'
                )
            )
            await connection.commit()
            checks["not_valid_upgrade_then_validation"] = True

            stage = "upgrade_0130"
            await set_search_path(connection, schema)
            await alembic(connection, "upgrade", "0130")
            schema_revision = str(
                await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')
            )
            if schema_revision != "0130":
                raise GateBlocked("disposable_upgrade_revision_mismatch")

            # Add current, stale, alternate-space, and second-tenant rows.
            rows = (
                ("current", tenant_a, doc_a, "Вводный инструктаж", "a" * 64, "synthetic-model", 1),
                ("stale", tenant_a, doc_a, "Устаревшая редакция", "b" * 64, "synthetic-model", 2),
                ("other-space", tenant_a, doc_a, "Другая модель", "a" * 64, "synthetic-model-v2", 3),
                ("tenant-b", tenant_b, doc_b, "Синтетический документ", "d" * 64, "synthetic-model", 0),
            )
            for row_id, tenant_id, doc_id, body, source_sha, model, chunk_index in rows:
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".document_embeddings ('
                        "id, tenant_id, doc_id, doc_name, text, headings, embedding, "
                        "embedding_provider, embedding_model, embedding_revision, "
                        "embedding_native_dimensions, embedding_storage_dimensions, "
                        "embedding_content_sha256, embedding_source_revision, "
                        "embedding_indexed_at, embedding_provenance_state, chunk_index) "
                        "VALUES (:id, :tenant, :doc, 'Synthetic', :body, '{}'::jsonb, "
                        "'[1,0,0,0]', 'synthetic-provider', :model, 'synthetic-r1', "
                        "4, 4, :content_sha, :source_revision, now(), 'verified', :chunk_index)"
                    ),
                    {
                        "id": row_id,
                        "tenant": tenant_id,
                        "doc": doc_id,
                        "body": body,
                        "model": model,
                        "content_sha": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "source_revision": f"document:{source_sha}",
                        "chunk_index": chunk_index,
                    },
                )
            await connection.execute(
                text(
                    f'INSERT INTO "{schema}".document_embeddings ('
                    "id, tenant_id, doc_id, doc_name, text, headings, embedding, "
                    "embedding_provider, embedding_model, embedding_revision, "
                    "embedding_native_dimensions, embedding_storage_dimensions, "
                    "embedding_content_sha256, embedding_source_revision, "
                    "embedding_indexed_at, embedding_provenance_state, chunk_index) "
                    "SELECT 'filler-' || n::text, :tenant, :doc, 'Synthetic filler', "
                    "'нейтральный синтетический фрагмент ' || n::text, '{}'::jsonb, "
                    "'[0,1,0,0]', 'synthetic-provider', 'synthetic-model', 'synthetic-r1', "
                    "4, 4, repeat('e', 64), :source_revision, now(), 'verified', 1000+n "
                    "FROM generate_series(1, 512) AS n"
                ),
                {
                    "tenant": tenant_a,
                    "doc": doc_a,
                    "source_revision": f"document:{'a' * 64}",
                },
            )

            await connection.execute(
                text(f'ALTER TABLE "{schema}".document_embeddings ENABLE ROW LEVEL SECURITY')
            )
            await connection.execute(
                text(f'ALTER TABLE "{schema}".document_embeddings FORCE ROW LEVEL SECURITY')
            )
            await connection.execute(
                text(
                    f'CREATE POLICY hbr_tenant_isolation ON "{schema}".document_embeddings '
                    "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid) "
                    "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid)"
                )
            )
            await connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO authenticated'))
            await connection.execute(
                text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{schema}".document_embeddings TO authenticated')
            )
            await connection.commit()

            stage = "active_revision_and_embedding_space"
            active_ids = set(
                (
                    await connection.execute(
                        text(
                            f'SELECT e.id FROM "{schema}".document_embeddings e '
                            f'JOIN "{schema}".documents d ON d.id=e.doc_id AND d.tenant_id=e.tenant_id '
                            "WHERE e.tenant_id=:tenant "
                            "AND e.embedding_provenance_state='verified' "
                            "AND e.embedding_provider='synthetic-provider' "
                            "AND e.embedding_model='synthetic-model' "
                            "AND e.embedding_revision='synthetic-r1' "
                            "AND e.embedding_native_dimensions=4 "
                            "AND e.embedding_storage_dimensions=4 "
                            "AND e.embedding_source_revision='document:' || d.content_sha256"
                        ),
                        {"tenant": tenant_a},
                    )
                ).scalars().all()
            )
            if "current" not in active_ids or "stale" in active_ids or "other-space" in active_ids:
                raise GateBlocked("active_revision_or_embedding_space_filter_failed")
            checks["legacy_provenance_classified"] = True
            checks["active_revision_sql_contract"] = True
            checks["embedding_space_sql_contract"] = True

            stage = "rls"
            await connection.execute(text("SET ROLE authenticated"))
            await connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, false)"),
                {"tenant": str(tenant_a)},
            )
            visible_a = int(
                await scalar(connection, f'SELECT count(*) FROM "{schema}".document_embeddings')
            )
            leaked_b = int(
                await scalar(
                    connection,
                    f'SELECT count(*) FROM "{schema}".document_embeddings WHERE tenant_id=:tenant',
                    tenant=tenant_b,
                )
            )
            await connection.execute(text("SAVEPOINT hbr_rls_write_negative"))
            write_denied = False
            try:
                await connection.execute(
                    text(
                        f'INSERT INTO "{schema}".document_embeddings '
                        "(id, tenant_id, doc_id, doc_name, text, headings, embedding) "
                        "VALUES ('rls-cross-tenant-write', :tenant, :doc, 'Synthetic', "
                        "'synthetic denied write', '{}'::jsonb, '[0,0,1,0]')"
                    ),
                    {"tenant": tenant_b, "doc": doc_b},
                )
            except Exception:
                write_denied = True
                await connection.execute(text("ROLLBACK TO SAVEPOINT hbr_rls_write_negative"))
            else:
                await connection.execute(text("ROLLBACK TO SAVEPOINT hbr_rls_write_negative"))
            await connection.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, false)"),
                {"tenant": str(tenant_b)},
            )
            visible_b = int(
                await scalar(connection, f'SELECT count(*) FROM "{schema}".document_embeddings')
            )
            await connection.execute(text("RESET app.current_tenant_id"))
            visible_without_tenant = int(
                await scalar(connection, f'SELECT count(*) FROM "{schema}".document_embeddings')
            )
            await connection.execute(text("RESET ROLE"))
            if (
                visible_a < 1
                or visible_b < 1
                or leaked_b != 0
                or visible_without_tenant != 0
                or not write_denied
            ):
                raise GateBlocked("rls_read_isolation_failed")
            rls_state = (
                await connection.execute(
                    text(
                        "SELECT c.relrowsecurity, c.relforcerowsecurity FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname='document_embeddings'"
                    ),
                    {"schema": schema},
                )
            ).one()
            if not bool(rls_state[0]) or not bool(rls_state[1]):
                raise GateBlocked("rls_enable_or_force_flag_missing")
            checks["rls_enabled"] = True
            checks["rls_force_enabled"] = True
            checks["rls_sql_contract_tenant_a_positive"] = True
            checks["rls_sql_contract_tenant_b_positive"] = True
            checks["rls_sql_contract_cross_tenant_read_denied"] = True
            checks["rls_sql_contract_cross_tenant_write_denied"] = True
            checks["rls_sql_contract_without_tenant_denied"] = True

            stage = "fts_explain"
            gin_indexes = (
                await connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname=:schema "
                        "AND tablename='document_embeddings' "
                        "AND indexdef ILIKE '%USING gin%' AND indexdef ILIKE '%embedding_fts%'"
                    ),
                    {"schema": schema},
                )
            ).scalars().all()
            if len(gin_indexes) != 1:
                raise GateBlocked("unexpected_fts_gin_index_set")
            await connection.execute(text(f'ANALYZE "{schema}".document_embeddings'))
            fts_result_ids = set(
                (
                    await connection.execute(
                        text(
                            f'SELECT e.id FROM "{schema}".document_embeddings e '
                            f'JOIN "{schema}".documents d ON d.id=e.doc_id AND d.tenant_id=e.tenant_id '
                            "WHERE e.tenant_id=:tenant AND e.embedding_provenance_state='verified' "
                            "AND e.embedding_source_revision='document:' || d.content_sha256 "
                            "AND e.embedding_fts @@ websearch_to_tsquery('russian', :query)"
                        ),
                        {"tenant": tenant_a, "query": "вводный инструктаж"},
                    )
                ).scalars().all()
            )
            if not fts_result_ids or "stale" in fts_result_ids or "tenant-b" in fts_result_ids:
                raise GateBlocked("fts_tenant_or_revision_semantics_failed")
            normal_plan = (
                await connection.execute(
                    text(
                        f'EXPLAIN (FORMAT JSON, COSTS OFF) SELECT e.id '
                        f'FROM "{schema}".document_embeddings e '
                        f'JOIN "{schema}".documents d ON d.id=e.doc_id AND d.tenant_id=e.tenant_id '
                        "WHERE e.tenant_id=:tenant AND e.embedding_provenance_state='verified' "
                        "AND e.embedding_source_revision='document:' || d.content_sha256 "
                        "AND e.embedding_fts @@ websearch_to_tsquery('russian', :query)"
                    ),
                    {"tenant": tenant_a, "query": "вводный инструктаж"},
                )
            ).scalar_one()
            normal_nodes, normal_indexes = summarize_plan(normal_plan)
            gin_state = (
                await connection.execute(
                    text(
                        "SELECT i.indisvalid, i.indisready FROM pg_index i "
                        "JOIN pg_class c ON c.oid=i.indexrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema AND c.relname=:index_name"
                    ),
                    {"schema": schema, "index_name": gin_indexes[0]},
                )
            ).one()
            if not bool(gin_state[0]) or not bool(gin_state[1]):
                raise GateBlocked("fts_gin_index_not_valid_or_ready")

            await connection.execute(text("SET LOCAL enable_seqscan=off"))
            await connection.execute(text("SET LOCAL enable_indexscan=off"))
            seqscan_setting = str(await scalar(connection, "SHOW enable_seqscan"))
            forced_plan = (
                await connection.execute(
                    text(
                        f'EXPLAIN (FORMAT JSON, COSTS OFF) SELECT id '
                        f'FROM "{schema}".document_embeddings '
                        "WHERE embedding_provenance_state='verified' "
                        "AND embedding_fts @@ websearch_to_tsquery('russian', :query)"
                    ),
                    {"query": "вводный инструктаж"},
                )
            ).scalar_one()
            forced_nodes, forced_indexes = summarize_plan(forced_plan)
            if str(gin_indexes[0]) not in normal_indexes:
                raise GateBlocked(
                    "fts_normal_explain_did_not_use_expected_gin_index;"
                    f"normal_nodes={','.join(normal_nodes)};"
                    f"normal_indexes={','.join(normal_indexes) or 'none'};"
                    f"forced_nodes={','.join(forced_nodes)};"
                    f"forced_indexes={','.join(forced_indexes) or 'none'};"
                    f"seqscan={seqscan_setting};"
                    f"valid={bool(gin_state[0])};ready={bool(gin_state[1])}"
                )
            if str(gin_indexes[0]) not in forced_indexes:
                raise GateBlocked("fts_forced_diagnostic_did_not_use_expected_gin_index")
            checks["fts_gin_index_present"] = True
            checks["fts_gin_index_valid"] = True
            checks["fts_gin_index_ready"] = True
            checks["fts_tenant_and_active_revision_semantics"] = True
            checks["fts_normal_production_shape_uses_gin"] = True
            checks["fts_forced_gin_diagnostic"] = True
            checks["fts_normal_plan_nodes"] = normal_nodes
            checks["fts_normal_plan_indexes"] = normal_indexes
            checks["fts_forced_plan_nodes"] = forced_nodes
            checks["fts_forced_plan_indexes"] = forced_indexes

            stage = "downgrade_0127"
            await connection.commit()
            await set_search_path(connection, schema)
            await alembic(connection, "downgrade", "0127")
            if str(await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')) != "0127":
                raise GateBlocked("disposable_downgrade_revision_mismatch")
            remaining = await table_columns(connection, schema)
            if PROVENANCE_COLUMNS.intersection(remaining) or "chunk_index" in remaining or "embedding_fts" in remaining:
                raise GateBlocked("downgrade_left_hbr_columns")
            checks["downgrade_0130_to_0127"] = True

            stage = "reupgrade_0130"
            await set_search_path(connection, schema)
            await alembic(connection, "upgrade", "0130")
            if str(await scalar(connection, f'SELECT version_num FROM "{schema}".alembic_version')) != "0130":
                raise GateBlocked("disposable_reupgrade_revision_mismatch")
            reupgrade_columns = await table_columns(connection, schema)
            required_after = PROVENANCE_COLUMNS | {"chunk_index", "embedding_fts"}
            if not required_after.issubset(reupgrade_columns):
                raise GateBlocked("reupgrade_columns_missing")
            reupgrade_unvalidated = (
                await connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid=c.conrelid "
                        "JOIN pg_namespace n ON n.oid=t.relnamespace "
                        "WHERE n.nspname=:schema AND t.relname='document_embeddings' "
                        "AND NOT c.convalidated ORDER BY c.conname"
                    ),
                    {"schema": schema},
                )
            ).scalars().all()
            for constraint_name in reupgrade_unvalidated:
                if not re.fullmatch(r"[a-zA-Z0-9_]+", constraint_name):
                    raise GateBlocked("unsafe_reupgrade_constraint_name")
                await connection.execute(
                    text(
                        f'ALTER TABLE "{schema}".document_embeddings '
                        f'VALIDATE CONSTRAINT "{constraint_name}"'
                    )
                )
            reupgrade_gin_state = (
                await connection.execute(
                    text(
                        "SELECT i.indisvalid, i.indisready FROM pg_index i "
                        "JOIN pg_class c ON c.oid=i.indexrelid "
                        "JOIN pg_namespace n ON n.oid=c.relnamespace "
                        "WHERE n.nspname=:schema "
                        "AND c.relname='ix_document_embeddings_verified_fts'"
                    ),
                    {"schema": schema},
                )
            ).one()
            if not bool(reupgrade_gin_state[0]) or not bool(reupgrade_gin_state[1]):
                raise GateBlocked("reupgrade_fts_index_not_valid_or_ready")
            relations = set(
                (
                    await connection.execute(
                        text(
                            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname=:schema AND c.relkind IN ('r','p','v','m','S','f')"
                        ),
                        {"schema": schema},
                    )
                ).scalars().all()
            )
            if relations != {"alembic_version", "documents", "document_embeddings"}:
                raise GateBlocked("unexpected_disposable_relations")
            checks["reupgrade_0127_to_0130"] = True
            checks["reupgrade_constraints_validated"] = True
            checks["reupgrade_fts_index_valid_and_ready"] = True
            checks["unexpected_relations_absent"] = True
            await connection.commit()

            stage = "public_unchanged"
            after_revision = await public_revision(connection)
            if after_revision != before_revision:
                raise GateBlocked("public_alembic_revision_changed")
            public_metadata_after = await public_metadata_fingerprint(connection)
            if public_metadata_after != public_metadata_before:
                raise GateBlocked("public_schema_metadata_changed")
            checks["public_revision_after"] = after_revision
            checks["public_revision_unchanged"] = True
            checks["public_schema_metadata_unchanged"] = True
    except Exception as exc:
        failure = exc
    finally:
        cleanup_ok = await cleanup(engine, schema)
        await engine.dispose()

    if failure is not None:
        if isinstance(failure, GateBlocked):
            detail = str(failure)
        else:
            detail = type(failure).__name__
        raise GateBlocked(
            f"stage={stage};cause={detail};cleanup={'passed' if cleanup_ok else 'failed'}"
        ) from None
    if not cleanup_ok:
        raise GateBlocked(f"cleanup_failed_at:{stage}")
    cleanup_checked_at = datetime.now(UTC)
    checks["disposable_schema_removed"] = True
    return {
        "evidence_id": f"HBR-DEV-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "status": "PASSED",
        "evidence_labels": ["RUNTIME-DERIVED"],
        "scope": "isolated_supabase_dev_disposable_schema",
        "executed_at": started_at.isoformat().replace("+00:00", "Z"),
        "cleanup_checked_at": cleanup_checked_at.isoformat().replace("+00:00", "Z"),
        "target_identity": {
            "provider": "supabase",
            "environment": "supabase-dev",
            "canonical_alias": "kamilya-supabase-dev",
            "project_ref_sha256": hashlib.sha256(project_ref.encode("ascii")).hexdigest(),
            "database_name": "postgres",
        },
        "target_fingerprint": target_fingerprint,
        "disposable_schema_digest": hashlib.sha256(schema.encode("ascii")).hexdigest(),
        "migration_from": "0127",
        "migration_to": "0130",
        "source_sha256": source_digests,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--evidence-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.execute:
        print(json.dumps({"status": "BLOCKED", "error_class": "execute_flag_required"}))
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
    schema = f"hbr_kb_{uuid.uuid4().hex[:12]}"
    try:
        evidence = asyncio.run(run_gate(database_url, supabase_url, schema))
    except Exception as exc:
        result = {
            "status": "BLOCKED",
            "error_class": type(exc).__name__,
            "stage_detail": exc.args[0] if isinstance(exc, GateBlocked) and exc.args else "sanitized",
            "disposable_schema": schema,
        }
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 1
    assert_sanitized_evidence(evidence)
    if args.evidence_file:
        output_path = args.evidence_file.resolve()
        if REPO_ROOT.resolve() not in output_path.parents:
            print(json.dumps({"status": "BLOCKED", "error_class": "unsafe_evidence_path"}))
            return 2
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(evidence, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
