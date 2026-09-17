"""Pure matching and diff rules for the adaptive staff import workflow."""

from .matching import (
    ExistingOrganizationUnit,
    ExistingPosition,
    ExistingStaff,
    ImportDiffAction,
    ImportDiffEntry,
    ImportDiffResult,
    ImportEntityType,
    ImportHierarchyConflictError,
    IncomingOrganizationUnit,
    IncomingPosition,
    IncomingStaff,
    build_import_diff,
    normalize_import_key,
    topologically_order_organization_units,
    validate_organization_unit_proposals,
)

__all__ = [
    "ExistingOrganizationUnit",
    "ExistingPosition",
    "ExistingStaff",
    "ImportDiffAction",
    "ImportDiffEntry",
    "ImportEntityType",
    "ImportHierarchyConflictError",
    "ImportDiffResult",
    "IncomingOrganizationUnit",
    "IncomingPosition",
    "IncomingStaff",
    "build_import_diff",
    "normalize_import_key",
    "topologically_order_organization_units",
    "validate_organization_unit_proposals",
]
