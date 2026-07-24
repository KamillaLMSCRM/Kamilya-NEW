import pytest
from pydantic import ValidationError

from app.modules.users.schemas import UserCreate


def test_existing_account_payload_accepts_empty_hidden_password():
    request = UserCreate(
        email="existing@example.com",
        role="methodologist",
        first_name="",
        last_name="",
        password="",
    )

    assert request.password is None


def test_new_account_payload_still_rejects_short_non_empty_password():
    with pytest.raises(ValidationError):
        UserCreate(
            email="new@example.com",
            role="methodologist",
            first_name="A",
            last_name="User",
            password="short",
        )
