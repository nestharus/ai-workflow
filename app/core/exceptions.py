"""Exception handlers and error formatting utilities for FastAPI."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.contracts.errors import HTTPValidationError, ValidationErrorDetail
from app.contracts.example_contract import MAX_VALIDATION_ERRORS

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fastapi import Request

    from app.core.settings import Settings


def _sanitize_validation_errors(errors: Sequence[dict[str, Any]]) -> list[ValidationErrorDetail]:
    """Convert raw Pydantic errors into constrained validation detail models."""
    sanitized: list[ValidationErrorDetail] = []
    for error in errors:
        sanitized.append(ValidationErrorDetail(**error))
        if len(sanitized) >= MAX_VALIDATION_ERRORS:
            break
    return sanitized


async def validation_exception_handler(request: Request, exc: Exception) -> ORJSONResponse:
    """Format request validation errors as a structured JSON response."""
    if not isinstance(exc, RequestValidationError):
        raise TypeError from exc
    sanitized_errors = _sanitize_validation_errors(exc.errors())
    settings: Settings | None = getattr(getattr(request.app, "state", None), "settings", None)
    include_error_body = (
        bool(getattr(settings, "include_error_body", False)) if settings is not None else False
    )

    body_content: Any | None = None
    if include_error_body:
        try:
            raw_body = await request.body()
            body_content = json.loads(raw_body) if raw_body else None
        except (ValueError):
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
