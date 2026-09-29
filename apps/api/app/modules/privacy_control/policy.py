"""Deterministic privacy catalog and disclosure decisions.

The catalog describes which data classes a named application operation handles.
It deliberately contains field *names*, never field values.  HTTP adapters and
background jobs call the same seam so policy does not drift between surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

POLICY_VERSION = "2026-09-29.v1"


class DisclosureOutcome(StrEnum):
    FULL = "full"
    MASKED = "masked"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    operation: str
    actor_role: str


@dataclass(frozen=True, slots=True)
class ProcessingDecision:
    policy_version: str
    operation: str
    purpose: str
    outcome: DisclosureOutcome
    reason_code: str
    field_names: tuple[str, ...]
    data_classes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _OperationPolicy:
    purpose: str
    allowed_roles: frozenset[str]
    field_names: tuple[str, ...]
    data_classes: tuple[str, ...]
    outcome: DisclosureOutcome = DisclosureOutcome.FULL


_ADMIN_ROLES = frozenset({"admin", "superadmin"})
_STAFF_EDITOR_ROLES = frozenset({"methodologist", "superadmin"})

_CATALOG: dict[str, _OperationPolicy] = {
    "employee.create": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_STAFF_EDITOR_ROLES,
        field_names=(
            "email",
            "first_name",
            "last_name",
            "organization_unit_id",
            "personnel_number",
            "phone",
            "position_id",
        ),
        data_classes=(
            "contact_identifier",
            "identity",
            "organization_assignment",
        ),
    ),
    "employee.update": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_STAFF_EDITOR_ROLES,
        field_names=("email", "first_name", "last_name", "personnel_number", "phone"),
        data_classes=("contact_identifier", "identity"),
    ),
    "employee.terminate": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_STAFF_EDITOR_ROLES,
        field_names=("is_active", "status", "termination_reason"),
        data_classes=("employment",),
    ),
    "employee.import_preview": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_STAFF_EDITOR_ROLES,
        field_names=(
            "department",
            "email",
            "first_name",
            "hire_date",
            "last_name",
            "personnel_number",
            "phone",
            "position",
        ),
        data_classes=(
            "contact_identifier",
            "employment",
            "identity",
            "organization_assignment",
        ),
    ),
    "employee.import": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_STAFF_EDITOR_ROLES,
        field_names=(
            "department",
            "email",
            "first_name",
            "hire_date",
            "last_name",
            "personnel_number",
            "phone",
            "position",
        ),
        data_classes=(
            "contact_identifier",
            "employment",
            "identity",
            "organization_assignment",
        ),
    ),
    "team_member.create": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=("email", "first_name", "is_active", "last_name", "password", "role"),
        data_classes=(
            "authentication_secret",
            "contact_identifier",
            "employment",
            "identity",
        ),
    ),
    "team_member.update": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=("email", "first_name", "is_active", "last_name"),
        data_classes=("contact_identifier", "employment", "identity"),
    ),
    "team_member.deactivate": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=("is_active",),
        data_classes=("employment",),
    ),
    "team_member.reset_password": _OperationPolicy(
        purpose="account_security",
        allowed_roles=_ADMIN_ROLES,
        field_names=("password",),
        data_classes=("authentication_secret",),
    ),
    "team_member.change_role": _OperationPolicy(
        purpose="access_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=("role",),
        data_classes=("employment",),
    ),
    "team_member.assign_role": _OperationPolicy(
        purpose="access_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=("role",),
        data_classes=("employment",),
    ),
    "employee.export": _OperationPolicy(
        purpose="workforce_administration",
        allowed_roles=_ADMIN_ROLES,
        field_names=(
            "created_at",
            "email",
            "first_name",
            "id",
            "is_active",
            "last_login",
            "last_name",
            "role",
            "telegram_id",
        ),
        data_classes=(
            "contact_identifier",
            "employment",
            "identity",
            "internal_identifier",
            "online_identifier",
        ),
    ),
    "enrollment.export": _OperationPolicy(
        purpose="training_compliance_reporting",
        allowed_roles=frozenset({"methodologist"}),
        field_names=(
            "completed_at",
            "course_title",
            "email",
            "enrolled_at",
            "first_name",
            "last_name",
            "status",
        ),
        data_classes=("contact_identifier", "identity", "learning_record"),
    ),
    "quiz_result.export": _OperationPolicy(
        purpose="training_compliance_reporting",
        allowed_roles=_ADMIN_ROLES,
        field_names=(
            "completed_at",
            "email",
            "earned_points",
            "first_name",
            "last_name",
            "passed",
            "quiz_id",
            "score_percent",
            "time_spent_seconds",
            "total_points",
        ),
        data_classes=("contact_identifier", "identity", "learning_record"),
    ),
}


def evaluate_processing(request: ProcessingRequest) -> ProcessingDecision:
    """Return one fail-closed decision from the versioned operation catalog."""

    policy = _CATALOG.get(request.operation)
    if policy is None:
        return ProcessingDecision(
            policy_version=POLICY_VERSION,
            operation=request.operation,
            purpose="unknown",
            outcome=DisclosureOutcome.DENY,
            reason_code="policy_missing",
            field_names=(),
            data_classes=(),
        )
    if request.actor_role not in policy.allowed_roles:
        return ProcessingDecision(
            policy_version=POLICY_VERSION,
            operation=request.operation,
            purpose=policy.purpose,
            outcome=DisclosureOutcome.DENY,
            reason_code="actor_role_denied",
            field_names=policy.field_names,
            data_classes=policy.data_classes,
        )
    return ProcessingDecision(
        policy_version=POLICY_VERSION,
        operation=request.operation,
        purpose=policy.purpose,
        outcome=policy.outcome,
        reason_code="policy_allow",
        field_names=policy.field_names,
        data_classes=policy.data_classes,
    )
