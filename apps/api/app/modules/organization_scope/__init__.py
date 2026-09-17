"""Tenant-safe organization audience resolution.

Consumers should use this module instead of embedding recursive hierarchy SQL or
legacy department fallback rules in their own queries.
"""

from .resolver import (
    MoveScope,
    OrganizationScopeNotFoundError,
    resolve_ancestor_path,
    resolve_descendants,
    resolve_employee_scope,
    validate_move,
)

__all__ = [
    "MoveScope",
    "OrganizationScopeNotFoundError",
    "resolve_ancestor_path",
    "resolve_descendants",
    "resolve_employee_scope",
    "validate_move",
]
