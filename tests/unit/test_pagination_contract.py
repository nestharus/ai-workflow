from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.contracts.example_contract import ExampleResponse
from app.contracts.pagination import MAX_PAGE_SIZE, Paginated


def test_paginated_valid_construction() -> None:
    """Verify successful instantiation with valid data."""
    item = ExampleResponse(
        result="[PROCESSED] Hello",
        processed_at=datetime.now(UTC),
        original_length=5,
    )
    paginated = Paginated[ExampleResponse](
        items=[item],
        total=10,
        page=1,
        page_size=5,
    )

    assert paginated.items == [item]
    assert paginated.total == 10
    assert paginated.page == 1
    assert paginated.page_size == 5
    assert isinstance(paginated.items, list)


def test_paginated_empty_items() -> None:
    """Verify empty collections are valid."""
    paginated = Paginated[ExampleResponse](
        items=[],
        total=0,
        page=1,
        page_size=10,
    )

    assert paginated.items == []
    assert paginated.total == 0


def test_paginated_total_negative_fails() -> None:
    """Verify total cannot be negative."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=-1,
            page=1,
            page_size=10,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("total",)
    assert "greater than or equal to 0" in errors[0]["msg"]


def test_paginated_page_zero_fails() -> None:
    """Verify page must be at least 1."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=0,
            page=0,
            page_size=10,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("page",)
    assert "greater than or equal to 1" in errors[0]["msg"]


def test_paginated_page_negative_fails() -> None:
    """Verify page cannot be negative."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=0,
            page=-1,
            page_size=10,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("page",)


def test_paginated_page_size_zero_fails() -> None:
    """Verify page_size must be at least 1."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=0,
            page=1,
            page_size=0,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("page_size",)
    assert "greater than or equal to 1" in errors[0]["msg"]


def test_paginated_page_size_exceeds_max_fails() -> None:
    """Verify page_size cannot exceed 1000."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=0,
            page=1,
            page_size=1001,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("page_size",)
    assert "less than or equal to 1000" in errors[0]["msg"]


def test_paginated_extra_fields_forbidden() -> None:
    """Verify extra fields are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        Paginated[ExampleResponse](
            items=[],
            total=0,
            page=1,
            page_size=10,
            extra_field="value",  # type: ignore[call-arg]
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert "Extra inputs are not permitted" in errors[0]["msg"]


def test_paginated_serialization() -> None:
    """Verify JSON serialization."""
    item = ExampleResponse(
        result="[PROCESSED] Test",
        processed_at=datetime(2023, 10, 27, 10, 0, 0, tzinfo=UTC),
        original_length=4,
    )
    paginated = Paginated[ExampleResponse](
        items=[item],
        total=1,
        page=1,
        page_size=10,
    )

    payload = paginated.model_dump(mode="json")

    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["result"] == "[PROCESSED] Test"
    assert payload["items"][0]["original_length"] == 4


def test_paginated_with_different_types() -> None:
    """Verify generic type flexibility."""
    dict_paginated = Paginated[dict[str, str]](
        items=[{"key": "value"}, {"key": "value2"}],
        total=2,
        page=1,
        page_size=10,
    )
    assert len(dict_paginated.items) == 2
    assert dict_paginated.items[0]["key"] == "value"

    str_paginated = Paginated[str](
        items=["a", "b", "c"],
        total=3,
        page=1,
        page_size=10,
    )
    assert len(str_paginated.items) == 3
    assert str_paginated.items[0] == "a"


def test_paginated_boundary_values() -> None:
    """Test boundary conditions."""
    min_paginated = Paginated[str](
        items=["item"],
        total=1,
        page=1,
        page_size=1,
    )
    assert min_paginated.page == 1
    assert min_paginated.page_size == 1

    max_paginated = Paginated[str](
        items=[],
        total=0,
        page=999999,
        page_size=1000,
    )
    assert max_paginated.page == 999999
    assert max_paginated.page_size == 1000


def test_paginated_respects_max_page_size_constant() -> None:
    """Verify page_size validation is linked to MAX_PAGE_SIZE constant."""
    paginated = Paginated[str](
        items=[],
        total=0,
        page=1,
        page_size=MAX_PAGE_SIZE,
    )
    assert paginated.page_size == MAX_PAGE_SIZE

    with pytest.raises(ValidationError) as exc_info:
        Paginated[str](
            items=[],
            total=0,
            page=1,
            page_size=MAX_PAGE_SIZE + 1,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("page_size",)
