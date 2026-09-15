from types import SimpleNamespace

from tests.conftest import (
    _forbidden_local_postgres,
    _requires_database_contour,
    pytest_collection_modifyitems,
)


def test_workstation_postgres_is_rejected_before_connection() -> None:
    assert _forbidden_local_postgres(
        "postgresql+asyncpg://test:test@localhost:5432/test",
        explicitly_allowed=False,
        github_actions=False,
        platform="win32",
    )
    assert _forbidden_local_postgres(
        "postgresql+asyncpg://test:test@localhost:5432/test",
        explicitly_allowed=True,
        github_actions=True,
        platform="win32",
    )
    assert not _forbidden_local_postgres(
        "postgresql+asyncpg://test:test@localhost:5432/test",
        explicitly_allowed=True,
        github_actions=True,
        platform="linux",
    )


def test_remote_supabase_postgres_is_not_rejected() -> None:
    assert not _forbidden_local_postgres(
        "postgresql+asyncpg://test:test@db.example.supabase.co:5432/test",
        explicitly_allowed=False,
        github_actions=False,
        platform="win32",
    )


def test_every_integration_test_requires_an_approved_database_contour() -> None:
    assert _requires_database_contour("C:/repo/apps/api/tests/integration/test_claim.py")
    assert _requires_database_contour("C:\\repo\\apps\\api\\tests\\integration\\test_claim.py")
    assert _requires_database_contour("tests/integration/test_claim.py")
    assert not _requires_database_contour("C:/repo/apps/api/tests/unit/test_claim.py")


def test_collection_hook_injects_guard_fixture_before_test_execution() -> None:
    integration = SimpleNamespace(
        path="tests/integration/test_claim.py",
        fixturenames=[],
    )
    unit = SimpleNamespace(path="tests/unit/test_claim.py", fixturenames=[])

    pytest_collection_modifyitems([integration, unit])

    assert integration.fixturenames == ["require_database_test_contour"]
    assert unit.fixturenames == []
