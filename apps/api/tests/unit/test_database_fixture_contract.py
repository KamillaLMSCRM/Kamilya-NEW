from pathlib import Path


def test_api_fixture_does_not_invent_local_postgresql() -> None:
    fixture = Path(__file__).parents[1] / "conftest.py"
    source = fixture.read_text(encoding="utf-8")

    assert "postgresql+asyncpg://lms:lms_dev_password_2026@localhost" not in source
    assert "database integration requires explicit approved DATABASE_URL" in source
