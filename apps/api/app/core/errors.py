from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "not_found", "message": str(exc)},
    )


async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": "Input validation failed",
            "details": exc.errors(),
        },
    )


async def unique_violation_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": "conflict", "message": "Resource already exists"},
    )
