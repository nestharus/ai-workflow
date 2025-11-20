"""Service layer implementation for example operations.

This module demonstrates the service pattern where business logic is encapsulated
in a class-based structure, separating it from the HTTP transport layer.
"""

from datetime import UTC, datetime

from app.contracts.example_contract import ExampleRequest, ExampleResponse


class ExampleService:
    """Encapsulates business logic for the example domain.

    Demonstrates dependency injection patterns and stateless processing
    wrapped in a service class.
    """

    def __init__(self, prefix: str = "[PROCESSED]") -> None:
        """Initialize the service with configuration parameters.

        Args:
            prefix: String to prepend to processed messages.
        """
        self._prefix = prefix

    def process(self, request: ExampleRequest) -> ExampleResponse:
        """Process an example request by applying a transformation.

        Args:
            request: The validated request object.

        Returns:
            ExampleResponse: The result of the processing operation.
        """
        # Simulate business logic: string manipulation
        processed_content = f"{self._prefix} [{request.type.upper()}] {request.message}"

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
