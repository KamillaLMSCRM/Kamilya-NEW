import pytest
from fastapi import HTTPException

from app.modules.auth.router import register


@pytest.mark.asyncio
async def test_legacy_register_is_retired_without_database_access():
    with pytest.raises(HTTPException) as exc_info:
        await register()

    assert exc_info.value.status_code == 410
