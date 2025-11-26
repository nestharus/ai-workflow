"""Generic pagination envelope for collection endpoints.

This module provides the canonical `Paginated[T]` model used to wrap paginated
collection responses across the API. It ensures consistent pagination structure
for all list endpoints.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

# Pagination constraints
MAX_PAGE_SIZE = 1000


class Paginated[T](BaseModel):
    """Generic pagination response envelope for API collection endpoints.

    Provides a consistent structure for paginated responses, wrapping a collection
    of items with metadata about the current page and total count.

    Attributes:
        items: The collection of items for the current page.
        total: Total count of items across all pages (must be non-negative).
        page: Current page number (1-indexed, must be at least 1).
        page_size: Number of items per page (must be between 1 and 1000).

    Type Parameters:
        T: The type of items in the collection.

    Examples:
        >>> from app.contracts.example_contract import ExampleResponse
        >>> from datetime import datetime, UTC
        >>> response = ExampleResponse(
        ...     result="[PROCESSED] Hello",
        ...     processed_at=datetime.now(UTC),
        ...     original_length=5,
        ... )
        >>> paginated = Paginated[ExampleResponse](
        ...     items=[response],
        ...     total=1,
        ...     page=1,
        ...     page_size=10,
        ... )
    """

    model_config = ConfigDict(extra="forbid")

    items: Annotated[list[T], Field(max_length=MAX_PAGE_SIZE)]
    total: Annotated[int, Field(ge=0)]
    page: Annotated[int, Field(ge=1)]
    page_size: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)]


__all__ = ["MAX_PAGE_SIZE", "Paginated"]
