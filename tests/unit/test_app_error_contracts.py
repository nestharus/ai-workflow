from __future__ import annotations

from app.contracts.errors import AppError, ErrorCode
from app.core.errors import DomainValidationError, ResourceNotFoundError, UnauthorizedError


def test_from_domain_resource_not_found_defaults():
    error = AppError.from_domain(ResourceNotFoundError())

    assert error.code is ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
    assert error.message == "Resource not found"


def test_from_domain_resource_not_found_custom_message():
    msg = "User missing"

    error = AppError.from_domain(ResourceNotFoundError(msg))

    assert error.code is ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
    assert error.message == msg


def test_from_domain_domain_validation_defaults():
    error = AppError.from_domain(DomainValidationError())

    assert error.code is ErrorCode.DOMAIN_VALIDATION_ERROR
    assert error.status_code == 400
    assert error.message == "Domain validation failed"


def test_from_domain_unauthorized_defaults():
    error = AppError.from_domain(UnauthorizedError())

    assert error.code is ErrorCode.UNAUTHORIZED
    assert error.status_code == 401
    assert error.message == "Unauthorized"


def test_internal_error_factory():
    error = AppError.internal_error()

    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.status_code == 500
    assert error.message == "Unexpected error while processing request"


def test_serialization_uses_alias_and_omits_null_details():
    error = AppError.from_domain(UnauthorizedError("denied"))

    payload = error.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "statusCode" in payload
    assert "status_code" not in payload
    assert payload["statusCode"] == 401
    assert payload["code"] == ErrorCode.UNAUTHORIZED
    assert "details" not in payload
