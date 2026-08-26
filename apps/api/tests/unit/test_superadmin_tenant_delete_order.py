from app.modules.admin.superadmin.service import TENANT_DELETE_SQL


def _delete_index(table_name: str) -> int:
    prefix = f"DELETE FROM {table_name} "
    return next(
        index
        for index, statement in enumerate(TENANT_DELETE_SQL)
        if statement.strip().replace("\n", " ").startswith(prefix)
    )


def test_registration_legal_acceptances_are_deleted_before_users() -> None:
    assert _delete_index("registration_legal_acceptances") < _delete_index("users")
