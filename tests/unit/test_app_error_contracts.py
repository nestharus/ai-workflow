from __future__ import annotations

from app.contracts.errors import (
    AppError,
    ErrorCode,
    HTTPValidationError,
    ValidationErrorDetail,
)
from app.core.errors import (
    DomainError,
    DomainValidationError,
    ResourceNotFoundError,
    UnauthorizedError,
)


def test_from_domain_resource_not_found_defaults() -> None:
    error = AppError.from_domain(ResourceNotFoundError())

    assert error.code is ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
    assert error.message == "Resource not found"


def test_from_domain_resource_not_found_custom_message() -> None:
    msg = "User missing"

    error = AppError.from_domain(ResourceNotFoundError(msg))

    assert error.code is ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
    assert error.message == msg


def test_from_domain_domain_validation_defaults() -> None:
    error = AppError.from_domain(DomainValidationError())

    assert error.code is ErrorCode.DOMAIN_VALIDATION_ERROR
    assert error.status_code == 400
    assert error.message == "Domain validation failed"


def test_from_domain_unauthorized_defaults() -> None:
    error = AppError.from_domain(UnauthorizedError())

    assert error.code is ErrorCode.UNAUTHORIZED
    assert error.status_code == 401
    assert error.message == "Unauthorized"


def test_from_domain_generic_domain_error_returns_internal_error() -> None:
    """Test that a generic DomainError (not a subclass) returns INTERNAL_ERROR."""
    # Create a generic DomainError (not a specific subclass)
    generic_error = DomainError("Something went wrong")

    error = AppError.from_domain(generic_error)

    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.status_code == 500
    assert error.message == "Something went wrong"


def test_from_domain_generic_domain_error_with_empty_message() -> None:
    """Test that a generic DomainError with empty message uses default."""
    generic_error = DomainError()

    error = AppError.from_domain(generic_error)

    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.status_code == 500
    assert error.message == "Unexpected error"


def test_internal_error_factory() -> None:
    error = AppError.internal_error()

    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.status_code == 500
    assert error.message == "Unexpected error while processing request"


def test_serialization_uses_alias_and_omits_null_details() -> None:
    error = AppError.from_domain(UnauthorizedError("denied"))

    payload = error.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "statusCode" in payload
    assert "status_code" not in payload
    assert payload["statusCode"] == 401
    assert payload["code"] == ErrorCode.UNAUTHORIZED
    assert "details" not in payload


def test_from_validation_error_without_body() -> None:
    """Test that from_validation_error creates correct AppError envelope without body."""
    validation_detail = ValidationErrorDetail(
        loc=["body", "message"],
        msg="Field required",
        type="missing",
        ctx=None,
    )
    validation_error = HTTPValidationError(detail=[validation_detail])

    error = AppError.from_validation_error(validation_error)

    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.status_code == 400
    assert error.message == "Request validation failed"
    assert error.details is not None
    assert "detail" in error.details
    assert len(error.details["detail"]) == 1
    assert error.details["detail"][0]["loc"] == ["body", "message"]
    assert error.details["detail"][0]["msg"] == "Field required"
    assert error.details["detail"][0]["type"] == "missing"
    # Body should not be present when not explicitly set
    assert "body" not in error.details


def test_from_validation_error_with_body() -> None:
    """Test that from_validation_error preserves body when included."""
    validation_detail = ValidationErrorDetail(
        loc=["body", "email"],
        msg="Invalid email format",
        type="value_error",
        ctx={"pattern": "^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$"},
    )
    request_body = {"email": "invalid-email", "name": "Test User"}
    validation_error = HTTPValidationError(detail=[validation_detail], body=request_body)

    error = AppError.from_validation_error(validation_error)

    assert error.code is ErrorCode.VALIDATION_ERROR
    assert error.status_code == 400
    assert error.details is not None
    assert "detail" in error.details
    assert "body" in error.details
    assert error.details["body"] == request_body


def test_validation_error_serialization_uses_alias() -> None:
    """Test that validation error serialization uses statusCode alias."""
    validation_detail = ValidationErrorDetail(
        loc=["body", "field"],
        msg="Test error",
        type="test",
    )
    validation_error = HTTPValidationError(detail=[validation_detail])
    error = AppError.from_validation_error(validation_error)

    payload = error.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "statusCode" in payload
    assert "status_code" not in payload
    assert payload["statusCode"] == 400
    assert payload["code"] == "VALIDATION_ERROR"
    assert "details" in payload
    assert "detail" in payload["details"]
