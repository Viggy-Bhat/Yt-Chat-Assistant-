"""Custom exception types and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from loguru import logger


class AppError(Exception):
    """Base application error.

    Subclasses set ``status_code`` and a default ``message``; instances may
    override either.
    """

    status_code: int = 500
    message: str = "Internal server error"

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    message = "Resource conflict"


class BadRequestError(AppError):
    status_code = 400
    message = "Bad request"


class YouTubeFetchError(AppError):
    status_code = 502
    message = "Failed to fetch YouTube data"


class IngestionError(AppError):
    status_code = 500
    message = "Ingestion failed"


class LLMError(AppError):
    status_code = 503
    message = "LLM service unavailable"


def _error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    """Wire custom error handlers into the FastAPI app."""

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        code = exc.__class__.__name__
        logger.warning(f"{code}: {exc.message}")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(code, exc.message, exc.details),
        )

    @app.exception_handler(404)
    async def _not_found(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=_error_payload("NotFound", "Route not found"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content=_error_payload("InternalError", "An unexpected error occurred"),
        )
