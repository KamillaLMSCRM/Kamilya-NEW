"""Bounded, immutable conversion-fidelity metadata for direct source intake."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MAX_FIDELITY_WARNING_COUNT = 32
MAX_FIDELITY_WARNING_LENGTH = 512
_SCANNED_PROFILE = "scanned_or_low_text"
_VERIFIED_RECOVERY_NOTICES = frozenset({"Ruled PDF tables restored from verified source geometry."})


def _bounded_warnings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    warnings: list[str] = []
    for item in value[:MAX_FIDELITY_WARNING_COUNT]:
        if isinstance(item, str) and item.strip():
            warnings.append(item.strip()[:MAX_FIDELITY_WARNING_LENGTH])
    return tuple(warnings)


@dataclass(frozen=True)
class ConversionFidelity:
    """Structured conversion metadata with an explicit unverified default.

    Older callers construct ``DirectSourceDocument`` without metadata.  Those
    snapshots remain readable, but ``metadata_verified`` stays false so an
    absent record can never be mistaken for a clean conversion.
    """

    engine: str | None = None
    profile: str | None = None
    fallback_used: bool | None = None
    warnings: tuple[str, ...] = ()
    pages: int | None = None
    tables: int | None = None
    engine_version: str | None = None
    routing_reason: str | None = None
    metadata_present: bool = False
    metadata_verified: bool = False

    @classmethod
    def unverified(cls) -> ConversionFidelity:
        return cls()

    @classmethod
    def from_metadata(cls, metadata: object) -> ConversionFidelity:
        if not isinstance(metadata, Mapping):
            return cls(metadata_present=metadata is not None, metadata_verified=False)

        def optional_text(key: str) -> str | None:
            value = metadata.get(key)
            return value.strip()[:256] if isinstance(value, str) and value.strip() else None

        def optional_count(key: str) -> int | None:
            value = metadata.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

        fallback = metadata.get("fallback_used")
        fallback_value = fallback if isinstance(fallback, bool) else None
        warnings = _bounded_warnings(metadata.get("warnings"))
        # A mapping with malformed typed fields is retained as unverified.  Do
        # not silently coerce values, because that can manufacture a clean
        # provenance claim from legacy or corrupt metadata.
        raw_warnings = metadata.get("warnings")
        # Bounded retention must not turn omitted warnings into affirmative
        # clean provenance (for example a loss warning after32 recovery notices).
        warnings_well_formed = (isinstance(raw_warnings, list | tuple)
            and len(raw_warnings) <= MAX_FIDELITY_WARNING_COUNT
            and all(isinstance(item, str) and item.strip() for item in raw_warnings))
        valid = all(
            (key not in metadata or metadata.get(key) is None or isinstance(metadata.get(key), str))
            for key in ("profile", "engine_version", "routing_reason")
        ) and ("fallback_used" not in metadata or isinstance(fallback, bool))
        valid = valid and ("warnings" not in metadata or warnings_well_formed)

        def valid_count(key: str) -> bool:
            value = metadata.get(key)
            return key not in metadata or (
                isinstance(value, int) and not isinstance(value, bool) and value >= 0
            )

        valid = valid and valid_count("pages") and valid_count("tables")
        # An empty or partial legacy mapping has no affirmative fidelity
        # contract. Keep it readable, but never label it clean.
        valid = valid and {"engine", "fallback_used", "warnings"}.issubset(metadata)
        valid = valid and optional_text("engine") is not None
        # Only the known ordinary-DOCX parser has a legacy unprofiled fallback
        # contract. Do not extend it to an unclassified PDF/digital-only engine.
        if fallback_value is True and optional_text("profile") is None and optional_text("engine") != "python-docx":
            valid = False
        return cls(
            engine=optional_text("engine"),
            profile=optional_text("profile"),
            fallback_used=fallback_value,
            warnings=warnings,
            pages=optional_count("pages"),
            tables=optional_count("tables"),
            engine_version=optional_text("engine_version"),
            routing_reason=optional_text("routing_reason"),
            metadata_present=True,
            metadata_verified=valid,
        )

    @property
    def is_scanned_or_low_text(self) -> bool:
        return self.profile == _SCANNED_PROFILE

    @property
    def is_degraded(self) -> bool:
        return any(warning not in _VERIFIED_RECOVERY_NOTICES for warning in self.warnings) or (
            self.is_scanned_or_low_text and self.fallback_used is True)

    @property
    def needs_review(self) -> bool:
        return self.status != "clean"

    @property
    def admission_blocked(self) -> bool:
        """Only block the known lossy scanned digital-only fallback shape."""
        return self.is_scanned_or_low_text and self.fallback_used is True

    @property
    def status(self) -> str:
        if not self.metadata_present or not self.metadata_verified:
            return "unverified"
        return "degraded" if self.is_degraded else "clean"

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "profile": self.profile,
            "fallback_used": self.fallback_used,
            "warnings": list(self.warnings),
            "pages": self.pages,
            "tables": self.tables,
            "engine_version": self.engine_version,
            "routing_reason": self.routing_reason,
            "metadata_present": self.metadata_present,
            "metadata_verified": self.metadata_verified,
            "status": self.status,
        }
