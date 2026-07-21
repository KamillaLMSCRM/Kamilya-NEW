from app.modules.admin.superadmin.service import GRANTABLE_ROLES
from app.modules.users.schemas import UserUpdate
from app.modules.users.service import TEAM_ROLES


def test_tenant_team_roles_do_not_include_platform_superadmin():
    assert "superadmin" not in TEAM_ROLES
    assert TEAM_ROLES == ("methodologist", "admin", "org_admin")


def test_superadmin_ui_can_grant_methodologist_but_not_superadmin():
    assert "methodologist" in GRANTABLE_ROLES
    assert "superadmin" not in GRANTABLE_ROLES


def test_user_patch_schema_does_not_accept_role_changes():
    fields = set(UserUpdate.model_fields)
    assert "role" not in fields
