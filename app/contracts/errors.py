"""Error response contracts for request validation failures."""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.example_contract import MAX_JSON_DEPTH, MAX_VALIDATION_ERRORS

_BODY_UNSET: Final[object] = object()

ErrorLocation = str | int


class ValidationErrorDetail(BaseModel):
    """Represents a single validation failure with optional context."""

    model_config = ConfigDict(extra="ignore")

    loc: list[ErrorLocation] = Field(
        title="Location",
        description="Path to the field that failed validation.",
        max_length=MAX_JSON_DEPTH,
    )
    msg: str = Field(title="Message")
    type: str = Field(title="Error Type")
    ctx: dict[str, Any] | None = Field(default=None, title="Context")


class HTTPValidationError(BaseModel):
    """Aggregated validation errors formatted for HTTP responses."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "description": "Detailed validation errors including location and context."
        },
    )

    detail: list[ValidationErrorDetail] = Field(
        title="Detail",
        max_length=MAX_VALIDATION_ERRORS,
    )
    body: Any | None = Field(
        default=_BODY_UNSET,
        description="Request payload echoed when include_error_body=True.",
    )


VALIDATION_ERROR_RESPONSE: Final[dict[str, Any]] = {
    "model": HTTPValidationError,
    "description": "Validation Error",
}

__all__ = [
    "VALIDATION_ERROR_RESPONSE",
    "ErrorLocation",
    "HTTPValidationError",
    "ValidationErrorDetail",
]
