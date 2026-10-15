"""Cross-origin authenticated downloads must retain their original filename."""

import httpx
import pytest
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.main import app


@pytest.mark.asyncio
async def test_download_filename_is_exposed_without_widening_origins():
    configured = next(item for item in app.user_middleware if item.cls is CORSMiddleware)

    async def download(scope, receive, send):
        await Response(b"synthetic", headers={"Content-Disposition": "attachment; filename*=UTF-8''qa.txt"})(scope, receive, send)

    cors = configured.cls(download, **configured.kwargs)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=cors), base_url="http://test") as client:
        allowed = await client.get("/download", headers={"Origin": "https://kamilya-lms-dev.vercel.app"})
        assert allowed.headers["access-control-allow-origin"] == "https://kamilya-lms-dev.vercel.app"
        exposed = {name.strip().lower() for name in allowed.headers.get("access-control-expose-headers", "").split(",")}
        assert "content-disposition" in exposed
        assert "*" not in exposed
        denied = await client.get("/download", headers={"Origin": "https://untrusted.invalid"})
        assert "access-control-allow-origin" not in denied.headers
