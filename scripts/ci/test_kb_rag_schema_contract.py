from dataclasses import replace
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.kb_rag_schema_contract import (
    ContractError,
    SchemaSnapshot,
    evaluate_snapshot,
)


def _valid_snapshot() -> SchemaSnapshot:
    return SchemaSnapshot(
        revision="0137",
        postgresql_major=17,
        pgvector_present=True,
        relations=(
            ("embedding_active_revisions", True, True),
            ("embedding_reindex_events", True, True),
            ("embedding_reindex_runs", True, True),
        ),
        columns=("embedding_index_revision_id", "embedding_reindex_run_id"),
        constraints=(
            (
                "ck_embedding_reindex_generation_nonnegative",
                "CHECK (generation >= 0)",
                True,
                False,
                False,
            ),
            (
                "ck_embedding_reindex_chunk_counts",
                "CHECK (expected_chunk_count >= 0 AND completed_chunk_count >= 0 "
                "AND completed_chunk_count <= expected_chunk_count AND "
                "(state NOT IN ('ready','active') OR "
                "completed_chunk_count = expected_chunk_count))",
                True,
                False,
                False,
            ),
            (
                "ck_embedding_reindex_state_bindings",
                "CHECK ((state IN ('staged','running','ready','aborted') AND "
                "active_revision_id <> candidate_revision_id) OR "
                "(state='active' AND active_revision_id = candidate_revision_id "
                "AND previous_revision_id IS NOT NULL) OR "
                "(state='rolled_back' AND active_revision_id = previous_revision_id "
                "AND previous_revision_id IS NOT NULL) OR state='cleaned')",
                True,
                False,
                False,
            ),
            (
                "ck_document_embeddings_reindex_binding",
                "CHECK ((embedding_index_revision_id IS NULL AND "
                "embedding_reindex_run_id IS NULL) OR "
                "(embedding_index_revision_id IS NOT NULL AND "
                "embedding_reindex_run_id IS NOT NULL))",
                False,
                False,
                False,
            ),
            (
                "fk_document_embeddings_reindex_run",
                "FOREIGN KEY (tenant_id, doc_id, embedding_reindex_run_id) "
                "REFERENCES embedding_reindex_runs(tenant_id, document_id, run_id) "
                "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
                False,
                True,
                True,
            ),
            (
                "embedding_reindex_events_tenant_id_document_id_run_id_generation_key",
                "UNIQUE (tenant_id, document_id, run_id, generation)",
                True,
                False,
                False,
            ),
        ),
        indexes=(
            (
                "uq_embedding_reindex_open_document",
                "CREATE UNIQUE INDEX uq_embedding_reindex_open_document "
                "ON embedding_reindex_runs (tenant_id, document_id)",
                "state IN ('staged','running','ready')",
            ),
        ),
        privileges=(
            ("embedding_active_revisions", True, True, True, False),
            ("embedding_reindex_events", True, True, True, False),
            ("embedding_reindex_runs", True, True, True, False),
        ),
    )


def _with_constraint_definition(
    snapshot: SchemaSnapshot,
    constraint_name: str,
    definition: str,
    *,
    validated: bool | None = None,
    deferrable: bool | None = None,
    deferred: bool | None = None,
) -> SchemaSnapshot:
    return replace(
        snapshot,
        constraints=tuple(
            (
                name,
                definition if name == constraint_name else current_definition,
                current_validated if validated is None or name != constraint_name else validated,
                current_deferrable if deferrable is None or name != constraint_name else deferrable,
                current_deferred if deferred is None or name != constraint_name else deferred,
            )
            for (
                name,
                current_definition,
                current_validated,
                current_deferrable,
                current_deferred,
            ) in snapshot.constraints
        ),
    )


def test_valid_snapshot_returns_sanitized_ci_contract() -> None:
    checks = evaluate_snapshot(_valid_snapshot())
    assert checks["alembic_revision"] == "0137"
    assert checks["postgresql_major"] == 17
    assert checks["force_rls"] is True
    assert checks["runtime_privileges"] is True
    assert checks["deferred_fk"] is True


@pytest.mark.parametrize(
    ("snapshot", "error"),
    (
        (replace(_valid_snapshot(), revision="0130"), "unexpected_alembic_revision"),
        (replace(_valid_snapshot(), postgresql_major=16), "unexpected_postgresql_major"),
        (replace(_valid_snapshot(), pgvector_present=False), "pgvector_missing"),
        (replace(_valid_snapshot(), privileges=()), "lifecycle_runtime_privileges_missing"),
        (
            replace(
                _valid_snapshot(),
                privileges=(
                    ("embedding_active_revisions", True, True, True, True),
                    ("embedding_reindex_events", True, True, True, False),
                    ("embedding_reindex_runs", True, True, True, False),
                ),
            ),
            "lifecycle_runtime_privileges_invalid",
        ),
        (
            replace(
                _valid_snapshot(),
                relations=(("embedding_active_revisions", True, False),),
            ),
            "lifecycle_tables_missing",
        ),
        (replace(_valid_snapshot(), indexes=()), "single_open_reindex_index_missing"),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "ck_embedding_reindex_generation_nonnegative",
                "CHECK (generation > 0)",
            ),
            "generation_definition_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "ck_document_embeddings_reindex_binding",
                "CHECK (embedding_index_revision_id IS NULL AND "
                "embedding_reindex_run_id IS NULL)",
            ),
            "reindex_binding_definition_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "ck_embedding_reindex_chunk_counts",
                "CHECK (expected_chunk_count >= 0 AND completed_chunk_count >= 0 "
                "AND completed_chunk_count <= expected_chunk_count AND "
                "state NOT IN ('ready','active'))",
            ),
            "chunk_count_definition_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "ck_embedding_reindex_state_bindings",
                "CHECK (state IN ('staged','running','ready','aborted','active',"
                "'rolled_back','cleaned') AND active_revision_id = candidate_revision_id "
                "AND previous_revision_id IS NOT NULL)",
            ),
            "state_binding_definition_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "fk_document_embeddings_reindex_run",
                "FOREIGN KEY (tenant_id, doc_id, embedding_reindex_run_id) "
                "REFERENCES wrong_table(tenant_id, document_id, run_id) "
                "ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED",
            ),
            "deferred_reindex_fk_definition_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "fk_document_embeddings_reindex_run",
                "FOREIGN KEY (tenant_id, doc_id, embedding_reindex_run_id) "
                "REFERENCES embedding_reindex_runs(tenant_id, document_id, run_id) "
                "ON DELETE RESTRICT",
                deferrable=False,
                deferred=False,
            ),
            "deferred_reindex_fk_contract_failed",
        ),
        (
            _with_constraint_definition(
                _valid_snapshot(),
                "embedding_reindex_events_tenant_id_document_id_run_id_generation_key",
                "UNIQUE (tenant_id, document_id, run_id, event_id)",
            ),
            "event_generation_unique_missing",
        ),
        (
            replace(
                _valid_snapshot(),
                indexes=(
                    (
                        "uq_embedding_reindex_open_document",
                        "CREATE UNIQUE INDEX uq_embedding_reindex_open_document "
                        "ON embedding_reindex_runs (tenant_id, document_id)",
                        "state = 'staged'",
                    ),
                ),
            ),
            "single_open_reindex_predicate_failed",
        ),
        (
            replace(
                _valid_snapshot(),
                indexes=(
                    (
                        "uq_embedding_reindex_open_document",
                        "CREATE INDEX uq_embedding_reindex_open_document "
                        "ON embedding_reindex_runs (tenant_id, run_id)",
                        "state IN ('staged','running','ready')",
                    ),
                ),
            ),
            "single_open_reindex_definition_failed",
        ),
    ),
)
def test_invalid_snapshot_fails_closed(snapshot, error) -> None:
    with pytest.raises(ContractError, match=error):
        evaluate_snapshot(snapshot)
