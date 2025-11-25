"""Domain exception hierarchy for business logic and repositories."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain and business-rule violations."""


class ResourceNotFoundError(DomainError):
    """Raised when a requested domain resource cannot be found."""


class DomainValidationError(DomainError, ValueError):
    """Raised when domain invariants or input validation fail."""


class UnauthorizedError(DomainError):
    """Raised when an operation is attempted without required permissions."""


__all__ = [
    "DomainError",
    "DomainValidationError",
    "ResourceNotFoundError",
    "UnauthorizedError",
]
