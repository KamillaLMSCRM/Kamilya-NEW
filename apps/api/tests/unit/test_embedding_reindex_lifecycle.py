import pytest

from app.modules.ai.embedding_reindex_lifecycle import (
    ChunkManifestEntry,
    IndexedChunkEvidence,
    ReindexLifecycleError,
    ReindexState,
    RevisionBinding,
    abort_reindex,
    activate_candidate,
    active_query_binding,
    finalize_cleanup,
    record_indexed_batch,
    rollback_cutover,
    stage_reindex,
)
from app.modules.ai.embedding_space import EmbeddingSpace

OLD_SOURCE = "document:" + "a" * 64
NEW_SOURCE = "document:" + "b" * 64
OLD_SPACE = EmbeddingSpace("provider", "model", "r1", 3)
NEW_SPACE = EmbeddingSpace("provider", "model", "r2", 3)
OTHER_SPACE = EmbeddingSpace("provider", "other-model", "r2", 3)


def _active() -> RevisionBinding:
    return RevisionBinding(
        revision_id="active-r1",
        source_revision=OLD_SOURCE,
        space=OLD_SPACE,
        manifest_sha256="1" * 64,
    )


def _manifest() -> tuple[ChunkManifestEntry, ...]:
    return (
        ChunkManifestEntry("chunk-0", 0, "c" * 64),
        ChunkManifestEntry("chunk-1", 1, "d" * 64),
    )


def _stage():
    return stage_reindex(
        tenant_id="tenant-1",
        document_id="doc-1",
        run_id="run-1",
        active=_active(),
        candidate_revision_id="candidate-r2",
        candidate_source_revision=NEW_SOURCE,
        candidate_space=NEW_SPACE,
        manifest=_manifest(),
    )


def _evidence(entry: ChunkManifestEntry, *, space=NEW_SPACE, revision=NEW_SOURCE):
    return IndexedChunkEvidence(
        chunk_id=entry.chunk_id,
        chunk_index=entry.chunk_index,
        content_sha256=entry.content_sha256,
        source_revision=revision,
        space=space,
    )


def _ready():
    run = _stage()
    return record_indexed_batch(
        run,
        [_evidence(entry) for entry in _manifest()],
        event_id="batch-all",
        expected_generation=0,
    )


def _active_candidate():
    run = _ready()
    return activate_candidate(
        run,
        event_id="activate-r2",
        expected_generation=run.generation,
        expected_candidate_revision_id=run.candidate.revision_id,
        expected_manifest_sha256=run.candidate.manifest_sha256,
    )


def test_partial_reindex_keeps_old_active_and_cannot_activate() -> None:
    run = _stage()
    partial = record_indexed_batch(
        run,
        [_evidence(_manifest()[0])],
        event_id="batch-1",
        expected_generation=0,
    )
    assert partial.state is ReindexState.RUNNING
    assert active_query_binding(partial).revision_id == "active-r1"
    with pytest.raises(ReindexLifecycleError, match="incomplete_reindex_cannot_activate"):
        activate_candidate(
            partial,
            event_id="activate-too-early",
            expected_generation=partial.generation,
            expected_candidate_revision_id=partial.candidate.revision_id,
            expected_manifest_sha256=partial.candidate.manifest_sha256,
        )


def test_complete_manifest_activates_atomically() -> None:
    ready = _ready()
    assert ready.state is ReindexState.READY
    assert active_query_binding(ready).revision_id == "active-r1"
    activated = activate_candidate(
        ready,
        event_id="activate-r2",
        expected_generation=ready.generation,
        expected_candidate_revision_id="candidate-r2",
        expected_manifest_sha256=ready.candidate.manifest_sha256,
    )
    assert activated.state is ReindexState.ACTIVE
    assert activated.previous_active == _active()
    assert active_query_binding(activated).revision_id == "candidate-r2"


@pytest.mark.parametrize(
    "evidence,error",
    [
        (_evidence(_manifest()[0], space=OTHER_SPACE), "mixed_reindex_embedding_space"),
        (
            _evidence(_manifest()[0], revision="document:" + "e" * 64),
            "mixed_reindex_source_revision",
        ),
        (
            IndexedChunkEvidence("chunk-0", 0, "e" * 64, NEW_SOURCE, NEW_SPACE),
            "reindex_chunk_manifest_mismatch",
        ),
        (
            IndexedChunkEvidence("unexpected", 2, "f" * 64, NEW_SOURCE, NEW_SPACE),
            "unexpected_reindex_chunk",
        ),
    ],
)
def test_mixed_or_unexpected_candidate_evidence_fails_closed(evidence, error) -> None:
    with pytest.raises(ReindexLifecycleError, match=error):
        record_indexed_batch(
            _stage(),
            [evidence],
            event_id="bad-batch",
            expected_generation=0,
        )


def test_run_level_event_replay_is_idempotent_and_conflict_is_rejected() -> None:
    run = _stage()
    evidence = [_evidence(_manifest()[0])]
    first = record_indexed_batch(
        run,
        evidence,
        event_id="batch-1",
        expected_generation=0,
    )
    replay = record_indexed_batch(
        first,
        evidence,
        event_id="batch-1",
        expected_generation=0,
    )
    assert replay is first
    with pytest.raises(ReindexLifecycleError, match="reindex_event_conflict"):
        record_indexed_batch(
            first,
            [_evidence(_manifest()[1])],
            event_id="batch-1",
            expected_generation=first.generation,
        )


def test_stale_generation_cannot_mutate_run() -> None:
    run = record_indexed_batch(
        _stage(),
        [_evidence(_manifest()[0])],
        event_id="batch-1",
        expected_generation=0,
    )
    with pytest.raises(ReindexLifecycleError, match="stale_reindex_generation"):
        record_indexed_batch(
            run,
            [_evidence(_manifest()[1])],
            event_id="batch-2",
            expected_generation=0,
        )


def test_abort_retains_old_active_and_cleanup_targets_only_candidate() -> None:
    run = record_indexed_batch(
        _stage(),
        [_evidence(_manifest()[0])],
        event_id="batch-1",
        expected_generation=0,
    )
    aborted = abort_reindex(
        run,
        event_id="abort-r2",
        expected_generation=run.generation,
    )
    assert aborted.state is ReindexState.ABORTED
    assert active_query_binding(aborted).revision_id == "active-r1"
    cleaned, directive = finalize_cleanup(
        aborted,
        event_id="cleanup-r2",
        expected_generation=aborted.generation,
    )
    assert cleaned.state is ReindexState.CLEANED
    assert directive.revision_ids == ("candidate-r2",)
    assert directive.tenant_id == "tenant-1"
    assert directive.document_id == "doc-1"


def test_post_cutover_rollback_restores_old_active_and_cleans_candidate() -> None:
    activated = _active_candidate()
    rolled_back = rollback_cutover(
        activated,
        event_id="rollback-r2",
        expected_generation=activated.generation,
    )
    assert rolled_back.state is ReindexState.ROLLED_BACK
    assert active_query_binding(rolled_back).revision_id == "active-r1"
    cleaned, directive = finalize_cleanup(
        rolled_back,
        event_id="cleanup-rollback",
        expected_generation=rolled_back.generation,
    )
    assert cleaned.state is ReindexState.CLEANED
    assert directive.revision_ids == ("candidate-r2",)


def test_successful_finalize_targets_only_previous_revision_and_ends_rollback_window() -> None:
    activated = _active_candidate()
    cleaned, directive = finalize_cleanup(
        activated,
        event_id="cleanup-r1",
        expected_generation=activated.generation,
    )
    assert active_query_binding(cleaned).revision_id == "candidate-r2"
    assert directive.revision_ids == ("active-r1",)
    with pytest.raises(ReindexLifecycleError, match="reindex_rollback_not_allowed"):
        rollback_cutover(
            cleaned,
            event_id="late-rollback",
            expected_generation=cleaned.generation,
        )


def test_activation_is_bound_to_exact_candidate_and_manifest() -> None:
    ready = _ready()
    with pytest.raises(ReindexLifecycleError, match="candidate_revision_activation_mismatch"):
        activate_candidate(
            ready,
            event_id="wrong-revision",
            expected_generation=ready.generation,
            expected_candidate_revision_id="candidate-r3",
            expected_manifest_sha256=ready.candidate.manifest_sha256,
        )
    with pytest.raises(ReindexLifecycleError, match="candidate_manifest_activation_mismatch"):
        activate_candidate(
            ready,
            event_id="wrong-manifest",
            expected_generation=ready.generation,
            expected_candidate_revision_id=ready.candidate.revision_id,
            expected_manifest_sha256="f" * 64,
        )


def test_manifest_is_deterministic_and_rejects_duplicate_chunk_coordinates() -> None:
    reversed_run = stage_reindex(
        tenant_id="tenant-1",
        document_id="doc-1",
        run_id="run-2",
        active=_active(),
        candidate_revision_id="candidate-r2",
        candidate_source_revision=NEW_SOURCE,
        candidate_space=NEW_SPACE,
        manifest=tuple(reversed(_manifest())),
    )
    assert reversed_run.candidate.manifest_sha256 == _stage().candidate.manifest_sha256
    with pytest.raises(ReindexLifecycleError, match="duplicate_manifest_chunk_index"):
        stage_reindex(
            tenant_id="tenant-1",
            document_id="doc-1",
            run_id="bad-run",
            active=_active(),
            candidate_revision_id="candidate-r2",
            candidate_source_revision=NEW_SOURCE,
            candidate_space=NEW_SPACE,
            manifest=(
                ChunkManifestEntry("a", 0, "a" * 64),
                ChunkManifestEntry("b", 0, "b" * 64),
            ),
        )
