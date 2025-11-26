"""Service layer implementation for example operations.

This module demonstrates the service pattern where business logic is encapsulated
in a class-based structure, separating it from the HTTP transport layer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.contracts.example_contract import ExampleRequest, ExampleResponse
from app.contracts.pagination import Paginated
from app.core.errors import ResourceNotFoundError

if TYPE_CHECKING:
    from app.core.settings import Settings
    from app.repositories.example_repository import (
        ExampleRepositoryProtocol,
        ProcessedMessage,
    )


class ExampleService:
    """Encapsulates business logic for the example domain.

    Demonstrates dependency injection patterns with repository and settings
    injected via constructor, following service-patterns.md.

    The service determines the message prefix based on the injected ``Settings``:
    when ``settings.debug`` is ``True``, messages are prefixed with ``[DEBUG]``;
    otherwise, it uses the configurable ``settings.example_prefix`` value. This
    allows runtime behavior to vary based on application configuration without
    code changes.

    Note:
        The injected repository is used to persist processed messages.

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

    async def process(self, request: ExampleRequest) -> ExampleResponse:
        """Process an example request by applying a transformation and persisting it."""
        prefix = "[DEBUG]" if self._settings.debug else self._settings.example_prefix
        processed_at = datetime.now(UTC)
        processed_content = f"{prefix} [{request.type.upper()}] {request.message}"

        response = ExampleResponse(
            result=processed_content,
            processed_at=processed_at,
            original_length=len(request.message),
        )

        await self._repository.save_processed_message(
            content=response.result,
            message_type=request.type,
            processed_at=processed_at,
        )

        return response

    async def get_processed_message(self, id: str) -> ProcessedMessage:
        """Retrieve a processed message by its unique identifier.

        Args:
            id: The unique identifier of the message to retrieve.

        Returns:
            The ProcessedMessage domain object.

        Raises:
            ResourceNotFoundError: If no message with the given ID exists.
        """
        message = await self._repository.get_by_id(id)
        if message is None:
            msg = f"Processed message {id} not found"
            raise ResourceNotFoundError(msg)
        return message

    async def list_processed_messages(
        self, page: int, page_size: int
    ) -> Paginated[ProcessedMessage]:
        """Retrieve a paginated list of processed messages.

        Args:
            page: Page number (1-indexed).
            page_size: Number of items per page.

        Returns:
            Paginated response containing messages and pagination metadata.
        """
        offset = (page - 1) * page_size
        messages, total = await self._repository.list_paginated(offset, page_size)
        return Paginated(
            items=messages,
            total=total,
            page=page,
            page_size=page_size,
        )

    def shutdown(self) -> None:
        """Clean up service resources.

        Placeholder for resource cleanup (connections, file handles, etc.)
        to demonstrate lifecycle management.
        """
        # No resources to clean up; repository manages connections
