"""Exception handlers and error formatting utilities for FastAPI."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.contracts.errors import AppError, ErrorCode, HTTPValidationError, ValidationErrorDetail
from app.contracts.example_contract import MAX_VALIDATION_ERRORS
from app.core.errors import DomainError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.settings import Settings


def _sanitize_validation_errors(errors: Sequence[dict[str, Any]]) -> list[ValidationErrorDetail]:
    """Convert raw Pydantic errors into constrained validation detail models."""
    sanitized: list[ValidationErrorDetail] = []
    for error in errors:
        ctx = error.get("ctx")
        if isinstance(ctx, dict):
            safe_ctx: dict[str, Any] = {}
            for key, value in ctx.items():
                try:
                    json.dumps(value)
                    safe_ctx[key] = value
                except TypeError:
                    safe_ctx[key] = str(value)
            error = {**error, "ctx": safe_ctx}
        sanitized.append(ValidationErrorDetail(**error))
        if len(sanitized) >= MAX_VALIDATION_ERRORS:
            break
    return sanitized


async def validation_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """Format request validation errors as a structured JSON response."""
    if not isinstance(exc, RequestValidationError):
        raise TypeError from exc
    sanitized_errors = _sanitize_validation_errors(exc.errors())
    app = request.app
    settings: Settings | None
    if isinstance(app, FastAPI):
        settings = getattr(getattr(app, "state", None), "settings", None)
    else:
        settings = None
    include_error_body = (
        bool(getattr(settings, "include_error_body", False)) if settings is not None else False
    )

    body_content: Any | None = None
    if include_error_body:
        try:
            raw_body = await request.body()
            body_content = json.loads(raw_body) if raw_body else None
        except ValueError:
            body_content = None

    logger.warning(
        "Validation error on %s %s: %s",
        request.method,
        request.url.path,
        str(sanitized_errors)[:1000],
    )
    if include_error_body:
        response_model = HTTPValidationError(detail=sanitized_errors, body=body_content)
    else:
        response_model = HTTPValidationError(detail=sanitized_errors)
    return ORJSONResponse(
        status_code=400,
        content=response_model.model_dump(mode="json", exclude_none=True, exclude_unset=True),
    )


async def domain_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """Convert domain errors into standardized envelopes."""
    if not isinstance(exc, DomainError):
        raise TypeError from exc
    app_error = AppError.from_domain(exc)
    logger.warning(
        "Domain error on %s %s [%s]: %s",
        request.method,
        request.url.path,
        app_error.code,
        app_error.message,
    )
    return ORJSONResponse(
        status_code=app_error.status_code,
        content=app_error.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


async def internal_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """Handle unexpected failures with a generic envelope."""
    logger.exception(
        "Unhandled error on %s %s [%s]",
        request.method,
        request.url.path,
        ErrorCode.INTERNAL_ERROR,
    )
    app_error = AppError.internal_error()
    return ORJSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=app_error.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
