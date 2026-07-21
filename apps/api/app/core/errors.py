import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def _cors_headers(request: Request) -> dict:
    """Return CORS headers based on the request Origin."""
    from app.core.config import get_settings
    settings = get_settings()
    origin = request.headers.get("origin", "")
    headers = {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
    }
    if origin in settings.CORS_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "not_found", "message": str(exc)},
        headers=_cors_headers(request),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle FastAPI HTTPException raised anywhere in the app.

    FastAPI registers a default handler for HTTPException, but our custom
    422 handler in `register_error_handlers` was shadowing it. Without this
    explicit handler, HTTPException(422, "AI returned invalid response")
    was being caught by `validation_error_handler` which called
    `.errors()` on an HTTPException → AttributeError → 500 to client.

    See: docs/лог рендер.txt — incident 2026-06-28T03:06.
    """
    detail = exc.detail
    # Normalize: HTTPException detail may be str, dict, or list.
    if isinstance(detail, dict):
        message = detail.get("message") or str(detail)
    elif isinstance(detail, list):
        message = str(detail)
    else:
        message = str(detail)
    content = {
        "error": _error_code_for_status(exc.status_code),
        "message": message,
    }
    # Keep machine-readable context for product flows that need more than a
    # human message (for example, document compatibility groups). Existing
    # clients remain compatible with the stable error/message envelope.
    if isinstance(detail, (dict, list)):
        content["details"] = detail
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=_cors_headers(request),
    )


def _error_code_for_status(status_code: int) -> str:
    """Map HTTP status to short error code used in JSON envelope."""
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "unprocessable_entity",
        429: "rate_limited",
        502: "bad_gateway",
        503: "service_unavailable",
    }.get(status_code, "error")


async def validation_error_handler(
    request: Request, exc: RequestValidationError | ValidationError
) -> JSONResponse:
    """Handle pydantic / FastAPI request validation errors (NOT HTTPException).

    Important: this handler is also triggered by FastAPI for 422 responses,
    so it MUST discriminate between real validation errors (which have
    `.errors()`) and HTTPException(422) which doesn't. Both can land here.
    """
    if isinstance(exc, HTTPException):
        # Fall back to generic http handler — this branch means someone
        # threw HTTPException(422) and FastAPI routed it here. Shouldn't
        # happen with the explicit handler above, but defensive.
        return await http_exception_handler(request, exc)

    if isinstance(exc, RequestValidationError):
        details = exc.errors()
    elif isinstance(exc, ValidationError):
        details = exc.errors()
    else:
        details = []

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Input validation failed",
            "details": details,
        },
        headers=_cors_headers(request),
    )


async def unique_violation_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "conflict", "message": "Resource already exists"},
        headers=_cors_headers(request),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "message": "Internal server error"},
        headers=_cors_headers(request),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(404, not_found_handler)
    # Register HTTPException first so it takes precedence over the 422
    # validation handler — otherwise HTTPException(422, ...) routed through
    # validation_error_handler crashes on .errors() (incident 2026-06-28).
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(ValidationError, validation_error_handler)
    app.add_exception_handler(500, unhandled_exception_handler)
