#!/usr/bin/env python3
"""Read-only CI assertion for the HBR PostgreSQL 17 schema contract."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


EXPECTED_REVISION = "0132"
LIFECYCLE_TABLES = {
    "embedding_active_revisions",
    "embedding_reindex_runs",
    "embedding_reindex_events",
}
REQUIRED_RUN_CONSTRAINTS = {
    "ck_embedding_reindex_generation_nonnegative",
    "ck_embedding_reindex_chunk_counts",
    "ck_embedding_reindex_state_bindings",
}


class ContractError(RuntimeError):
    """Sanitized schema-contract failure."""


@dataclass(frozen=True)
class SchemaSnapshot:
    revision: str
    postgresql_major: int
    pgvector_present: bool
    relations: tuple[tuple[str, bool, bool], ...]
    columns: tuple[str, ...]
    constraints: tuple[tuple[str, str, bool, bool, bool], ...]
    indexes: tuple[tuple[str, str, str], ...]


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _require_fragments(definition: str, *fragments: str, error: str) -> None:
    normalized = _normalized(definition)
    if any(_normalized(fragment) not in normalized for fragment in fragments):
        raise ContractError(error)


def evaluate_snapshot(snapshot: SchemaSnapshot) -> dict[str, bool | int | str]:
    if snapshot.revision != EXPECTED_REVISION:
        raise ContractError("unexpected_alembic_revision")
    if snapshot.postgresql_major != 17:
        raise ContractError("unexpected_postgresql_major")
    if not snapshot.pgvector_present:
        raise ContractError("pgvector_missing")

    relation_map = {
        name: (row_security, force_row_security)
        for name, row_security, force_row_security in snapshot.relations
    }
    if set(relation_map) != LIFECYCLE_TABLES:
        raise ContractError("lifecycle_tables_missing")
    if any(not row_security or not force for row_security, force in relation_map.values()):
        raise ContractError("lifecycle_force_rls_missing")

    if set(snapshot.columns) != {
        "embedding_index_revision_id",
        "embedding_reindex_run_id",
    }:
        raise ContractError("embedding_reindex_columns_missing")

    constraints = {name: (definition, validated, deferrable, deferred) for name, definition, validated, deferrable, deferred in snapshot.constraints}
    if not REQUIRED_RUN_CONSTRAINTS.issubset(constraints):
        raise ContractError("lifecycle_constraints_missing")
    binding = constraints.get("ck_document_embeddings_reindex_binding")
    if binding is None or binding[1]:
        raise ContractError("reindex_binding_validation_contract_failed")
    _require_fragments(
        binding[0],
        "embedding_index_revision_id IS NULL",
        "embedding_reindex_run_id IS NULL",
        "embedding_index_revision_id IS NOT NULL",
        "embedding_reindex_run_id IS NOT NULL",
        error="reindex_binding_definition_failed",
    )
    generation = constraints["ck_embedding_reindex_generation_nonnegative"][0]
    _require_fragments(
        generation,
        "generation >= 0",
        error="generation_definition_failed",
    )
    chunk_counts = constraints["ck_embedding_reindex_chunk_counts"][0]
    _require_fragments(
        chunk_counts,
        "expected_chunk_count >= 0",
        "completed_chunk_count >= 0",
        "completed_chunk_count <= expected_chunk_count",
        "ready",
        "active",
        "completed_chunk_count = expected_chunk_count",
        error="chunk_count_definition_failed",
    )
    state_bindings = constraints["ck_embedding_reindex_state_bindings"][0]
    _require_fragments(
        state_bindings,
        "staged",
        "running",
        "ready",
        "aborted",
        "active",
        "rolled_back",
        "cleaned",
        "active_revision_id = candidate_revision_id",
        "active_revision_id = previous_revision_id",
        "previous_revision_id IS NOT NULL",
        error="state_binding_definition_failed",
    )
    foreign_key = constraints.get("fk_document_embeddings_reindex_run")
    if foreign_key is None or foreign_key[1] or not foreign_key[2] or not foreign_key[3]:
        raise ContractError("deferred_reindex_fk_contract_failed")
    _require_fragments(
        foreign_key[0],
        "FOREIGN KEY (tenant_id, doc_id, embedding_reindex_run_id)",
        "REFERENCES embedding_reindex_runs(tenant_id, document_id, run_id)",
        "ON DELETE RESTRICT",
        "DEFERRABLE INITIALLY DEFERRED",
        error="deferred_reindex_fk_definition_failed",
    )
    if not any(
        _normalized(definition).startswith(
            "unique (tenant_id, document_id, run_id, generation)"
        )
        for definition, _validated, _deferrable, _deferred in constraints.values()
    ):
        raise ContractError("event_generation_unique_missing")
    index_map = {name: (definition, predicate) for name, definition, predicate in snapshot.indexes}
    open_index = index_map.get("uq_embedding_reindex_open_document")
    if open_index is None:
        raise ContractError("single_open_reindex_index_missing")
    index_definition, index_predicate = open_index
    _require_fragments(
        index_definition,
        "CREATE UNIQUE INDEX",
        "embedding_reindex_runs",
        "(tenant_id, document_id)",
        error="single_open_reindex_definition_failed",
    )
    _require_fragments(
        index_predicate,
        "state",
        "staged",
        "running",
        "ready",
        error="single_open_reindex_predicate_failed",
    )

    return {
        "alembic_revision": snapshot.revision,
        "postgresql_major": snapshot.postgresql_major,
        "pgvector_present": True,
        "lifecycle_tables": len(LIFECYCLE_TABLES),
        "force_rls": True,
        "reindex_columns": True,
        "state_and_count_constraints": True,
        "deferred_fk": True,
        "event_generation_unique": True,
        "single_open_reindex": True,
    }


def _normalize_database_url(value: str) -> str:
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+asyncpg://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+asyncpg://", 1)
    return value


async def read_snapshot(database_url: str) -> SchemaSnapshot:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            revision = str(
                (
                    await connection.execute(
                        text("SELECT version_num FROM public.alembic_version")
                    )
                ).scalar_one()
            )
            postgresql_major = int(
                (await connection.execute(text("SHOW server_version_num"))).scalar_one()
            ) // 10000
            pgvector_present = bool(
                (
                    await connection.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
                        )
                    )
                ).scalar_one()
            )
            relations = tuple(
                (
                    str(row[0]),
                    bool(row[1]),
                    bool(row[2]),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                            "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                            "WHERE n.nspname='public' AND c.relname IN "
                            "('embedding_active_revisions','embedding_reindex_runs','embedding_reindex_events') "
                            "ORDER BY c.relname"
                        )
                    )
                ).all()
            )
            columns = tuple(
                str(row[0])
                for row in (
                    await connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='public' AND table_name='document_embeddings' "
                            "AND column_name IN ('embedding_index_revision_id','embedding_reindex_run_id') "
                            "ORDER BY column_name"
                        )
                    )
                ).all()
            )
            constraints = tuple(
                (
                    str(row[0]),
                    str(row[1]),
                    bool(row[2]),
                    bool(row[3]),
                    bool(row[4]),
                )
                for row in (
                    await connection.execute(
                        text(
                            "SELECT c.conname, pg_get_constraintdef(c.oid), c.convalidated, "
                            "c.condeferrable, c.condeferred "
                            "FROM pg_constraint c "
                            "JOIN pg_class t ON t.oid=c.conrelid "
                            "JOIN pg_namespace n ON n.oid=t.relnamespace "
                            "WHERE n.nspname='public' AND t.relname IN "
                            "('document_embeddings','embedding_reindex_runs','embedding_reindex_events')"
                        )
                    )
                ).all()
            )
            indexes = tuple(
                (str(row[0]), str(row[1]), str(row[2] or ""))
                for row in (
                    await connection.execute(
                        text(
                            "SELECT c.relname, pg_get_indexdef(i.indexrelid), "
                            "pg_get_expr(i.indpred, i.indrelid) "
                            "FROM pg_index i "
                            "JOIN pg_class c ON c.oid=i.indexrelid "
                            "JOIN pg_class t ON t.oid=i.indrelid "
                            "JOIN pg_namespace n ON n.oid=t.relnamespace "
                            "WHERE n.nspname='public' "
                            "AND c.relname='uq_embedding_reindex_open_document'"
                        )
                    )
                ).all()
            )
        return SchemaSnapshot(
            revision=revision,
            postgresql_major=postgresql_major,
            pgvector_present=pgvector_present,
            relations=relations,
            columns=columns,
            constraints=constraints,
            indexes=indexes,
        )
    finally:
        await engine.dispose()


async def run() -> dict[str, Any]:
    database_url = _normalize_database_url(os.environ.get("DATABASE_URL", ""))
    if not database_url:
        raise ContractError("database_url_missing")
    return {
        "status": "READY",
        "evidence_label": "RUNTIME-DERIVED",
        "scope": "ephemeral_ci_postgresql_read_only",
        "checks": evaluate_snapshot(await read_snapshot(database_url)),
    }


def main() -> int:
    try:
        result = asyncio.run(run())
    except Exception as exc:
        print(
            json.dumps(
                {"status": "BLOCKED", "error_class": type(exc).__name__},
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
