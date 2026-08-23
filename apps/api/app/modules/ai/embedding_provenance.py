"""Pure, fail-closed adapter for persisted embedding provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, TypeAlias

from app.modules.ai.embedding_space import EmbeddingSpace


PROVENANCE_COLUMNS = (
    "embedding_provenance_state",
    "embedding_provider",
    "embedding_model",
    "embedding_revision",
    "embedding_native_dimensions",
    "embedding_storage_dimensions",
    "embedding_content_sha256",
    "embedding_source_revision",
    "embedding_indexed_at",
)

_COLUMN_SET = frozenset(PROVENANCE_COLUMNS)
_METADATA_COLUMNS = PROVENANCE_COLUMNS[1:]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REVISION_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")
_MAX_SOURCE_REVISION_LENGTH = 160


class InvalidEmbeddingProvenanceError(ValueError):
    """Stable, sanitized error for malformed persisted provenance."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LegacyUnclassified:
    """A row whose embedding provenance is intentionally unknown."""


@dataclass(frozen=True, slots=True)
class VerifiedEmbeddingProvenance:
    """Exact embedding identity and independently persisted source metadata."""

    space: EmbeddingSpace
    native_dimensions: int
    storage_dimensions: int
    content_sha256: str
    source_revision: str
    indexed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.space, EmbeddingSpace):
            raise InvalidEmbeddingProvenanceError("invalid_verified_space")
        if type(self.native_dimensions) is not int or self.native_dimensions <= 0:
            raise InvalidEmbeddingProvenanceError("invalid_native_dimensions")
        if type(self.storage_dimensions) is not int or self.storage_dimensions <= 0:
            raise InvalidEmbeddingProvenanceError("invalid_storage_dimensions")
        if self.native_dimensions > self.storage_dimensions:
            raise InvalidEmbeddingProvenanceError("native_dimensions_exceed_storage")
        if type(self.content_sha256) is not str or not _SHA256_RE.fullmatch(self.content_sha256):
            raise InvalidEmbeddingProvenanceError("invalid_content_sha256")
        if (
            type(self.source_revision) is not str
            or not self.source_revision
            or len(self.source_revision) > _MAX_SOURCE_REVISION_LENGTH
            or self.source_revision != self.source_revision.strip()
            or not _SAFE_REVISION_RE.fullmatch(self.source_revision)
        ):
            raise InvalidEmbeddingProvenanceError("invalid_source_revision")
        if (
            not isinstance(self.indexed_at, datetime)
            or self.indexed_at.tzinfo is None
            or self.indexed_at.utcoffset() is None
        ):
            raise InvalidEmbeddingProvenanceError("invalid_indexed_at")


EmbeddingProvenance: TypeAlias = LegacyUnclassified | VerifiedEmbeddingProvenance


def serialize_embedding_provenance(provenance: EmbeddingProvenance) -> dict[str, object]:
    """Convert provenance to exactly the columns owned by migration 0128."""

    if isinstance(provenance, LegacyUnclassified):
        row = dict.fromkeys(PROVENANCE_COLUMNS)
        row["embedding_provenance_state"] = "legacy_unclassified"
        return row
    if not isinstance(provenance, VerifiedEmbeddingProvenance):
        raise InvalidEmbeddingProvenanceError("unknown_provenance_state")
    return {
        "embedding_provenance_state": "verified",
        "embedding_provider": provenance.space.provider,
        "embedding_model": provenance.space.model,
        "embedding_revision": provenance.space.revision,
        "embedding_native_dimensions": provenance.native_dimensions,
        "embedding_storage_dimensions": provenance.storage_dimensions,
        "embedding_content_sha256": provenance.content_sha256,
        "embedding_source_revision": provenance.source_revision,
        "embedding_indexed_at": provenance.indexed_at,
    }


def _invalid_row(code: str) -> InvalidEmbeddingProvenanceError:
    return InvalidEmbeddingProvenanceError(code)


def _parse_indexed_at(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise _invalid_row("invalid_indexed_at") from None
    else:
        raise _invalid_row("invalid_indexed_at")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid_row("invalid_indexed_at")
    return parsed


def deserialize_embedding_provenance(row: Mapping[str, object]) -> EmbeddingProvenance:
    """Validate a complete persistence row without exposing raw row values in errors."""

    if not isinstance(row, Mapping):
        raise _invalid_row("invalid_provenance_row")
    if set(row) != _COLUMN_SET:
        raise _invalid_row("invalid_provenance_columns")

    values = MappingProxyType(dict(row))
    state = values["embedding_provenance_state"]
    present = tuple(values[column] is not None for column in _METADATA_COLUMNS)
    if state == "legacy_unclassified":
        if any(present):
            raise _invalid_row("partial_legacy_provenance")
        return LegacyUnclassified()
    if state != "verified":
        raise _invalid_row("unknown_provenance_state")
    if not all(present):
        raise _invalid_row("partial_verified_provenance")

    try:
        space = EmbeddingSpace(
            provider=values["embedding_provider"],  # type: ignore[arg-type]
            model=values["embedding_model"],  # type: ignore[arg-type]
            revision=values["embedding_revision"],  # type: ignore[arg-type]
            dimensions=values["embedding_native_dimensions"],  # type: ignore[arg-type]
        )
        return VerifiedEmbeddingProvenance(
            space=space,
            native_dimensions=values["embedding_native_dimensions"],  # type: ignore[arg-type]
            storage_dimensions=values["embedding_storage_dimensions"],  # type: ignore[arg-type]
            content_sha256=values["embedding_content_sha256"],  # type: ignore[arg-type]
            source_revision=values["embedding_source_revision"],  # type: ignore[arg-type]
            indexed_at=_parse_indexed_at(values["embedding_indexed_at"]),
        )
    except InvalidEmbeddingProvenanceError:
        raise
    except (TypeError, ValueError):
        raise _invalid_row("invalid_verified_provenance") from None


__all__ = [
    "EmbeddingProvenance",
    "InvalidEmbeddingProvenanceError",
    "LegacyUnclassified",
    "PROVENANCE_COLUMNS",
    "VerifiedEmbeddingProvenance",
    "deserialize_embedding_provenance",
    "serialize_embedding_provenance",
]
