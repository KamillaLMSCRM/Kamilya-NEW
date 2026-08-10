import json

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request

from app.core.errors import http_exception_handler, validation_error_handler


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


async def test_validation_error_handler_serializes_value_error_context():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/public/leads",
            "headers": [],
        }
    )
    exception = RequestValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "consent_version"),
                "msg": "Value error, is not the current public lead consent version",
                "input": "old",
                "ctx": {"error": ValueError("is not the current public lead consent version")},
            }
        ]
    )

    response = await validation_error_handler(request, exception)
    payload = json.loads(response.body)

    assert response.status_code == 422
    assert payload["error"] == "validation_error"
    assert payload["details"][0]["ctx"]["error"] == ("is not the current public lead consent version")
