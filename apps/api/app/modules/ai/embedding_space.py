"""Pure embedding-space identity and vector validation contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

_MAX_IDENTIFIER_LENGTH = 160
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/+:-]*$")


class EmbeddingContractError(ValueError):
    """Base error with a stable, sanitized machine-readable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class InvalidEmbeddingSpaceError(EmbeddingContractError):
    """Raised when embedding-space metadata violates the contract."""


class InvalidEmbeddingVectorError(EmbeddingContractError):
    """Raised when a vector is malformed for its declared space."""


class IncompatibleEmbeddingSpaceError(EmbeddingContractError):
    """Raised before vectors from different semantic spaces are compared."""


def _validate_identifier(value: object, field: str) -> str:
    code = f"invalid_space_{field}"
    if type(value) is not str:
        raise InvalidEmbeddingSpaceError(code)
    if not value or value != value.strip() or len(value) > _MAX_IDENTIFIER_LENGTH:
        raise InvalidEmbeddingSpaceError(code)
    if not _IDENTIFIER_RE.fullmatch(value):
        raise InvalidEmbeddingSpaceError(code)
    if "://" in value or "\\" in value or any(part == ".." for part in value.split("/")):
        raise InvalidEmbeddingSpaceError(code)
    return value


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    """Exact identity of one semantic comparison space."""

    provider: str
    model: str
    revision: str
    dimensions: int

    def __post_init__(self) -> None:
        _validate_identifier(self.provider, "provider")
        _validate_identifier(self.model, "model")
        _validate_identifier(self.revision, "revision")
        if type(self.dimensions) is not int or self.dimensions <= 0:
            raise InvalidEmbeddingSpaceError("invalid_space_dimensions")


@dataclass(frozen=True, slots=True)
class Embedding:
    """A finite immutable vector validated against an embedding space."""

    space: EmbeddingSpace
    values: tuple[float, ...]

    def __init__(self, space: EmbeddingSpace, values: Iterable[float]):
        if not isinstance(space, EmbeddingSpace):
            raise InvalidEmbeddingVectorError("invalid_embedding_space")
        try:
            materialized = tuple(values)
        except Exception as exc:
            raise InvalidEmbeddingVectorError("unsupported_embedding_input") from exc
        if len(materialized) != space.dimensions:
            raise InvalidEmbeddingVectorError("invalid_embedding_length")

        normalized: list[float] = []
        for value in materialized:
            if type(value) not in (int, float):
                raise InvalidEmbeddingVectorError("invalid_embedding_value")
            try:
                numeric = float(value)
            except (OverflowError, ValueError) as exc:
                raise InvalidEmbeddingVectorError("invalid_embedding_value") from exc
            if not math.isfinite(numeric):
                raise InvalidEmbeddingVectorError("invalid_embedding_value")
            normalized.append(numeric)

        object.__setattr__(self, "space", space)
        object.__setattr__(self, "values", tuple(normalized))


def require_compatible(left: Embedding, right: Embedding) -> None:
    """Fail closed unless both vectors belong to the exact same space."""

    if not isinstance(left, Embedding) or not isinstance(right, Embedding):
        raise InvalidEmbeddingVectorError("invalid_embedding_operand")
    for field, code in (
        ("provider", "space_provider_mismatch"),
        ("model", "space_model_mismatch"),
        ("revision", "space_revision_mismatch"),
        ("dimensions", "space_dimensions_mismatch"),
    ):
        if getattr(left.space, field) != getattr(right.space, field):
            raise IncompatibleEmbeddingSpaceError(code)
