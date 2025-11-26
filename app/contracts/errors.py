"""Error response contracts for request validation failures."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.example_contract import MAX_JSON_DEPTH, MAX_VALIDATION_ERRORS
from app.core.errors import (
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
    UnauthorizedError,
)

_BODY_UNSET: Final[object] = object()
DetailsList = Annotated[list[Any], Field(max_length=MAX_VALIDATION_ERRORS)]

ErrorLocation = str | int


class ErrorCode(str, Enum):
    """Machine-readable error identifiers for API responses."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    DOMAIN_VALIDATION_ERROR = "DOMAIN_VALIDATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    EXAMPLE_INVALID = "EXAMPLE_INVALID"


class AppError(BaseModel):
    """Canonical envelope for non-validation errors."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    code: ErrorCode = Field(title="Error Code")
    message: str = Field(title="Message")
    status_code: int = Field(alias="statusCode", title="HTTP Status Code")
    details: dict[str, Any] | DetailsList | None = Field(
        default=None,
        title="Details",
    )

    @classmethod
    def from_domain(cls, exc: DomainError) -> AppError:
        """Map domain errors to HTTP-aware envelopes."""
        if isinstance(exc, ResourceNotFoundError):
            return cls(
                code=ErrorCode.RESOURCE_NOT_FOUND,
                message=str(exc) or "Resource not found",
                status_code=404,
                details=None,
            )
        if isinstance(exc, DomainValidationError):
            return cls(
                code=ErrorCode.DOMAIN_VALIDATION_ERROR,
                message=str(exc) or "Domain validation failed",
                status_code=400,
                details=None,
            )
        if isinstance(exc, UnauthorizedError):
            return cls(
                code=ErrorCode.UNAUTHORIZED,
                message=str(exc) or "Unauthorized",
                status_code=401,
                details=None,
            )
        return cls(
            code=ErrorCode.INTERNAL_ERROR,
            message=str(exc) or "Unexpected error",
            status_code=500,
            details=None,
        )

    @classmethod
    def internal_error(cls) -> AppError:
        """Return a standardized envelope for unexpected failures."""
        return cls(
            code=ErrorCode.INTERNAL_ERROR,
            message="Unexpected error while processing request",
            status_code=500,
            details=None,
        )


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
    "AppError",
    "ErrorCode",
    "ErrorLocation",
    "HTTPValidationError",
    "ValidationErrorDetail",
]
