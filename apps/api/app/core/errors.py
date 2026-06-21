from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError


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


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Input validation failed",
            "details": exc.errors(),
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
    import logging
    logging.getLogger(__name__).exception("Unhandled exception")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal_error", "message": "Internal server error"},
        headers=_cors_headers(request),
    )
