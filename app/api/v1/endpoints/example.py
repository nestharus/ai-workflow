"""Demo endpoint routes demonstrating service wiring.

These are non-resource demo endpoints intended to illustrate the
request -> service -> response flow. They are not first-class
resources and should not be used in production workloads.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query, status

from app.api.v1.dependencies import ExampleServiceDep
from app.contracts.errors import VALIDATION_ERROR_RESPONSE, AppError
from app.contracts.example_contract import (
    ExampleRequest,
    ExampleResponse,
    ProcessedMessageResponse,
)
from app.contracts.pagination import MAX_PAGE_SIZE, Paginated

router = APIRouter()


@router.get(
    "/sample",
    response_model=ExampleResponse,
    summary="Get a sample response",
    description=(
        "[DEMO] Returns a hardcoded sample response to demonstrate the response "
        "schema. This is a non-resource demo endpoint."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: VALIDATION_ERROR_RESPONSE,
        status.HTTP_404_NOT_FOUND: {"model": AppError, "description": "Resource not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        },
    },
)
def sample_item() -> ExampleResponse:
    """Return a static sample response."""
    result_text = "Sample Result"
    processed_at = datetime.now(UTC)
    return ExampleResponse(
        result=f"[DEMO] {result_text}",
        processed_at=processed_at,
        original_length=len(result_text),
    )


@router.post(
    "/process",
    response_model=ExampleResponse,
    status_code=status.HTTP_200_OK,
    summary="Process a text message",
    description=(
        "[DEMO] Accepts a message object, applies simple string transformation, "
        "and returns the result. Demonstrates the full request -> service -> response "
        "flow. This is a non-resource demo endpoint."
    ),
    responses={
        status.HTTP_200_OK: {"description": "Successful processing"},
        status.HTTP_400_BAD_REQUEST: VALIDATION_ERROR_RESPONSE,
        status.HTTP_404_NOT_FOUND: {"model": AppError, "description": "Resource not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        },
    },
)
async def process_message(request: ExampleRequest, service: ExampleServiceDep) -> ExampleResponse:
    """Process an input message using the ExampleService."""
    return await service.process(request)


@router.get(
    "/processed-messages",
    response_model=Paginated[ProcessedMessageResponse],
    summary="List processed messages",
    description=(
        "[DEMO] Returns a paginated list of processed messages queried from CSV "
        "data via DuckDB. Demonstrates real database querying with pagination."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: VALIDATION_ERROR_RESPONSE,
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        },
    },
)
async def list_processed_messages(
    service: ExampleServiceDep,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(10, ge=1, le=MAX_PAGE_SIZE, description="Number of items per page"),
) -> Paginated[ProcessedMessageResponse]:
    """Retrieve a paginated list of processed messages."""
    result = await service.list_processed_messages(page, page_size)
    return Paginated[ProcessedMessageResponse](
        items=[
            ProcessedMessageResponse(
                id=msg.id,
                content=msg.content,
                type=msg.type,  # type: ignore[arg-type]
                processed_at=msg.processed_at,
            )
            for msg in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/processed-messages/{message_id}",
    response_model=ProcessedMessageResponse,
    summary="Get a processed message by ID",
    description=(
        "[DEMO] Retrieves a single processed message by its unique identifier. "
        "Demonstrates real 404 handling when a resource is not found."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: VALIDATION_ERROR_RESPONSE,
        status.HTTP_404_NOT_FOUND: {"model": AppError, "description": "Message not found"},
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        },
    },
)
async def get_processed_message(
    message_id: str,
    service: ExampleServiceDep,
) -> ProcessedMessageResponse:
    """Retrieve a processed message by its unique identifier."""
    msg = await service.get_processed_message(message_id)
    return ProcessedMessageResponse(
        id=msg.id,
        content=msg.content,
        type=msg.type,  # type: ignore[arg-type]
        processed_at=msg.processed_at,
    )
