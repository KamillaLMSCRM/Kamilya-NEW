from datetime import datetime, timezone

import pytest

from app.modules.ai.embedding_provenance import (
    PROVENANCE_COLUMNS,
    InvalidEmbeddingProvenanceError,
    LegacyUnclassified,
    VerifiedEmbeddingProvenance,
    deserialize_embedding_provenance,
    serialize_embedding_provenance,
)
from app.modules.ai.embedding_space import EmbeddingSpace


def make_space() -> EmbeddingSpace:
    return EmbeddingSpace(provider="openai", model="embed/model", revision="v1", dimensions=3)


def make_verified(**overrides: object) -> VerifiedEmbeddingProvenance:
    values: dict[str, object] = {
        "space": make_space(),
        "native_dimensions": 3,
        "storage_dimensions": 4,
        "content_sha256": "a" * 64,
        "source_revision": "git-2026-08-23",
        "indexed_at": datetime(2026, 8, 23, 10, 30, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return VerifiedEmbeddingProvenance(**values)  # type: ignore[arg-type]


def test_legacy_is_explicit_and_serializes_with_state_and_null_metadata() -> None:
    provenance = LegacyUnclassified()
    row = serialize_embedding_provenance(provenance)

    assert isinstance(provenance, LegacyUnclassified)
    assert set(row) == set(PROVENANCE_COLUMNS)
    assert row["embedding_provenance_state"] == "legacy_unclassified"
    assert all(
        value is None
        for column, value in row.items()
        if column != "embedding_provenance_state"
    )
    assert deserialize_embedding_provenance(row) == provenance


def test_verified_round_trip_preserves_exact_space_and_separate_dimensions() -> None:
    provenance = make_verified()
    row = serialize_embedding_provenance(provenance)
    restored = deserialize_embedding_provenance(row)

    assert set(row) == set(PROVENANCE_COLUMNS)
    assert row["embedding_provenance_state"] == "verified"
    assert isinstance(restored, VerifiedEmbeddingProvenance)
    assert restored.space == provenance.space
    assert restored.native_dimensions == 3
    assert restored.storage_dimensions == 4
    assert restored.indexed_at.tzinfo is not None


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("native_dimensions", 0, "invalid_native_dimensions"),
        ("storage_dimensions", 0, "invalid_storage_dimensions"),
        ("native_dimensions", 5, "native_dimensions_exceed_storage"),
        ("content_sha256", "A" * 64, "invalid_content_sha256"),
        ("content_sha256", "not-a-hash", "invalid_content_sha256"),
        ("source_revision", "  unsafe ", "invalid_source_revision"),
        ("indexed_at", datetime(2026, 8, 23), "invalid_indexed_at"),
    ],
)
def test_verified_validation_is_fail_closed(field: str, value: object, code: str) -> None:
    with pytest.raises(InvalidEmbeddingProvenanceError) as error:
        make_verified(**{field: value})

    assert error.value.code == code
    assert str(error.value) == code


def test_legacy_cannot_expose_guessed_provenance() -> None:
    row = serialize_embedding_provenance(LegacyUnclassified())
    assert row["embedding_provider"] is None
    assert row["embedding_model"] is None
    assert row["embedding_revision"] is None
    assert row["embedding_native_dimensions"] is None


@pytest.mark.parametrize(
    "row_mutation,code",
    [
        (lambda row: row.update(embedding_model=None), "partial_verified_provenance"),
        (
            lambda row: row.update(embedding_provenance_state="legacy_unclassified"),
            "partial_legacy_provenance",
        ),
        (lambda row: row.update(embedding_provenance_state="future"), "unknown_provenance_state"),
        (lambda row: row.update(unexpected="value"), "invalid_provenance_columns"),
        (lambda row: row.update(embedding_content_sha256="B" * 64), "invalid_content_sha256"),
        (lambda row: row.update(embedding_storage_dimensions="4"), "invalid_storage_dimensions"),
        (lambda row: row.update(embedding_indexed_at="2026-08-23T10:30:00"), "invalid_indexed_at"),
    ],
)
def test_deserialization_rejects_invalid_rows_without_raw_values(row_mutation, code: str) -> None:
    row = serialize_embedding_provenance(make_verified())
    row_mutation(row)

    with pytest.raises(InvalidEmbeddingProvenanceError) as error:
        deserialize_embedding_provenance(row)

    assert error.value.code == code
    assert "2026" not in str(error.value)
    assert "value" not in str(error.value)


def test_unknown_state_and_non_mapping_are_sanitized() -> None:
    with pytest.raises(InvalidEmbeddingProvenanceError, match="unknown_provenance_state"):
        serialize_embedding_provenance(object())  # type: ignore[arg-type]
    with pytest.raises(InvalidEmbeddingProvenanceError, match="invalid_provenance_row"):
        deserialize_embedding_provenance(object())  # type: ignore[arg-type]
