"""Pure admission policy for tenant training-report scopes."""

from __future__ import annotations

from enum import StrEnum


class ReportingScopeMode(StrEnum):
    TENANT = "tenant"
    RESTRICTED = "restricted"
    DENIED = "denied"


def decide_reporting_scope(role: str, *, has_responsibilities: bool) -> ReportingScopeMode:
    """Choose the reporting boundary without granting a new global role.

    Existing tenant reporting roles remain backward compatible.  A configured
    responsibility narrows a methodologist to its explicit audience; it never
    broadens a learner account into a reporting role.
    """

    if role in {"admin", "superadmin"}:
        return ReportingScopeMode.TENANT
    if role == "methodologist":
        return (
            ReportingScopeMode.RESTRICTED
            if has_responsibilities
            else ReportingScopeMode.TENANT
        )
    return ReportingScopeMode.DENIED
