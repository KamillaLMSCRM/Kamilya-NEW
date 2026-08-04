from fastapi import HTTPException
from starlette.requests import Request

from app.core.errors import http_exception_handler


async def test_http_exception_handler_preserves_retry_after_header():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/ai/generate-course",
            "headers": [],
        }
    )
    exception = HTTPException(
        status_code=429,
        detail={
            "code": "tenant_ai_job_limit_reached",
            "message": "Tenant AI job limit reached",
            "retry_after_seconds": 510,
        },
        headers={"Retry-After": "510"},
    )

    response = await http_exception_handler(request, exception)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "510"
