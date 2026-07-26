import pytest
from pydantic import ValidationError

from app.core.auth import ROLES
from app.modules.admin.superadmin.schemas import AdminCreate
from app.modules.admin.superadmin.service import GRANTABLE_ROLES
from app.modules.users.schemas import UserUpdate
from app.modules.users.service import TEAM_ROLES


def test_tenant_team_roles_do_not_include_platform_superadmin():
    assert "superadmin" not in TEAM_ROLES
    assert TEAM_ROLES == ("methodologist", "admin")


def test_org_admin_is_not_a_canonical_or_assignable_role():
    assert "org_admin" not in ROLES
    assert "org_admin" not in TEAM_ROLES
    assert "org_admin" not in GRANTABLE_ROLES
    with pytest.raises(ValidationError):
        AdminCreate(
            email="admin@example.kz",
            first_name="Admin",
            last_name="User",
            role="org_admin",
        )


def test_superadmin_ui_can_grant_methodologist_but_not_superadmin():
    assert "methodologist" in GRANTABLE_ROLES
    assert "superadmin" not in GRANTABLE_ROLES


def test_user_patch_schema_does_not_accept_role_changes():
    fields = set(UserUpdate.model_fields)
    assert "role" not in fields
