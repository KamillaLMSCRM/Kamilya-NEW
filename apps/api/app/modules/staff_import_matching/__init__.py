"""Pure matching and diff rules for the adaptive staff import workflow."""

from .matching import (
    ExistingOrganizationUnit,
    ExistingPosition,
    ExistingStaff,
    ImportDiffAction,
    ImportDiffEntry,
    ImportDiffResult,
    ImportEntityType,
    IncomingOrganizationUnit,
    IncomingPosition,
    IncomingStaff,
    build_import_diff,
    normalize_import_key,
)

__all__ = [
    "ExistingOrganizationUnit",
    "ExistingPosition",
    "ExistingStaff",
    "ImportDiffAction",
    "ImportDiffEntry",
    "ImportEntityType",
    "ImportDiffResult",
    "IncomingOrganizationUnit",
    "IncomingPosition",
    "IncomingStaff",
    "build_import_diff",
    "normalize_import_key",
]
