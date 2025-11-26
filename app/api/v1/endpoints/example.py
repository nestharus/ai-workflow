"""Demo endpoint routes demonstrating service wiring.

These are non-resource demo endpoints intended to illustrate the
request -> service -> response flow. They are not first-class
resources and should not be used in production workloads.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.api.v1.dependencies import ExampleServiceDep
from app.contracts.errors import VALIDATION_ERROR_RESPONSE, AppError
from app.contracts.example_contract import ExampleRequest, ExampleResponse

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
        # TODO: Replace with actual 404 when database querying is implemented (DuckDB + CSV).
        # Currently included for OpenAPI schema consistency across all example endpoints.
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
