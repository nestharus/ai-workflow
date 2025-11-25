"""Service layer implementation for example operations.

This module demonstrates the service pattern where business logic is encapsulated
in a class-based structure, separating it from the HTTP transport layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.contracts.example_contract import ExampleRequest, ExampleResponse

if TYPE_CHECKING:
    from app.core.settings import Settings
    from app.repositories.example_repository import ExampleRepositoryProtocol


class ExampleService:
    """Encapsulates business logic for the example domain.

    Demonstrates dependency injection patterns with repository and settings
    injected via constructor, following service-patterns.md.

    The service determines the message prefix based on the injected ``Settings``:
    when ``settings.debug`` is ``True``, messages are prefixed with ``[DEBUG]``;
    otherwise, the default ``[PROCESSED]`` prefix is used. This allows runtime
    behavior to vary based on application configuration without code changes.

    Note:
        The injected repository is available for data access operations. To
        demonstrate async repository usage, the ``process`` method could be
        converted to ``async def`` and call ``await self._repository.get_prefix()``
        to retrieve a database-driven prefix. This would require updating the
        endpoint to use ``async def`` as well.

    Attributes:
        _repository: Repository for example domain data access.
        _settings: Application settings instance.
    """

    def __init__(
        self,
        repository: ExampleRepositoryProtocol,
        settings: Settings,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            repository: Repository for example domain data access.
            settings: Application settings loaded via dependency injection.
        """
        self._repository = repository
        self._settings = settings

    def process(self, request: ExampleRequest) -> ExampleResponse:
        """Process an example request by applying a transformation.

        The result prefix is determined by the injected ``Settings``: uses
        ``[DEBUG]`` when ``settings.debug`` is ``True``, otherwise ``[PROCESSED]``.

        Note:
            To use the repository for prefix retrieval, convert this method to
            ``async def process(...)`` and call ``await self._repository.get_prefix()``.
            The endpoint in ``app/api/v1/endpoints/example.py`` would also need
            to become async to await this method.

        Args:
            request: The validated request object.

        Returns:
            ExampleResponse: The result of the processing operation.
        """
        # Use settings to derive prefix from app configuration
        # When debug=True, use [DEBUG]; otherwise use [PROCESSED]
        prefix = "[PROCESSED]" if not self._settings.debug else "[DEBUG]"

        # Simulate business logic: string manipulation
        processed_content = f"{prefix} [{request.type.upper()}] {request.message}"

        return ExampleResponse(
            result=processed_content,
            processed_at=datetime.now(UTC),
            original_length=len(request.message),
        )

    def shutdown(self) -> None:
        """Clean up service resources.

        Placeholder for resource cleanup (connections, file handles, etc.)
        to demonstrate lifecycle management.
        """
