from tests.conftest import _forbidden_local_postgres


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
