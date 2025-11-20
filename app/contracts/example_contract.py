"""Data contracts for the Example service.

These models define the schema for the example endpoint, demonstrating Pydantic
validation capabilities including field constraints, custom validators, and
immutable configurations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Type aliases using Python 3.12+ syntax
type MessageType = Literal["info", "warning", "error"]

# Validation constants
MAX_MESSAGE_LENGTH = 500
MIN_MESSAGE_LENGTH = 1
MAX_VALIDATION_ERRORS = 32
MAX_JSON_DEPTH = 20


class EmptyMessageError(ValueError):
    """Raised when ExampleRequest.message is empty or whitespace."""

    _MESSAGE = "ExampleRequest.message must not be empty or whitespace only"

    def __init__(self) -> None:
        """Initialize with the fixed validation message."""
        super().__init__(self._MESSAGE)


class ExampleRequest(BaseModel):
    """Request envelope for the example processing endpoint.

    Attributes:
        message: The content to be processed. Must be between 1 and 500 characters.
        type: The category of the message (info, warning, error). Defaults to "info".

    Examples:
        ExampleRequest(message="Hello World", type="info")
    """

    model_config = ConfigDict(extra="forbid")

    message: Annotated[str, Field(min_length=MIN_MESSAGE_LENGTH, max_length=MAX_MESSAGE_LENGTH)]
    type: MessageType = "info"

    @model_validator(mode="after")
    def validate_message_content(self) -> ExampleRequest:
        """Ensure message contains meaningful content."""
        if self.message.strip() == "":
            raise EmptyMessageError()
        return self


class ExampleResponse(BaseModel):
    """Response object containing the processed result.

    Attributes:
        result: The transformed message string.
        processed_at: Timestamp or status indicator of when processing occurred.
        original_length: Length of the original input message.

    Examples:
        ExampleResponse(
            result="[PROCESSED] Hello World",
            processed_at=datetime.fromisoformat("2023-10-27T10:00:00+00:00"),
            original_length=11
        )
    """

    model_config = ConfigDict(extra="forbid")

    result: Annotated[str, Field(min_length=1)]
    processed_at: datetime
    original_length: int
