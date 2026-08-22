"""Consistent API error handling.

Provides structured error responses that never expose internal stack traces.
All API errors follow a uniform format for predictable client integration.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base application error with HTTP status code."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, resource: str = "Resource") -> None:
        super().__init__(code="NOT_FOUND", message=f"{resource} not found", status_code=404)


class ValidationError(AppError):
    """Input validation failed."""

    def __init__(self, message: str = "Validation failed") -> None:
        super().__init__(code="VALIDATION_ERROR", message=message, status_code=422)


class UnauthorizedError(AppError):
    """Authentication required or failed."""

    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(code="UNAUTHORIZED", message=message, status_code=401)


class RateLimitError(AppError):
    """Rate limit exceeded."""

    def __init__(self) -> None:
        super().__init__(code="RATE_LIMIT_EXCEEDED", message="Too many requests", status_code=429)


def error_response(status_code: int, code: str, message: str) -> JSONResponse:
    """Create a consistent error response."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        return error_response(500, "INTERNAL_SERVER_ERROR", "An unexpected error occurred")
