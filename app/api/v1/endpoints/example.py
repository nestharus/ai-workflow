"""Example endpoint routes demonstrating service wiring."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.contracts.errors import VALIDATION_ERROR_RESPONSE
from app.contracts.example_contract import ExampleRequest, ExampleResponse
from app.services.example_service import ExampleService

router = APIRouter()


def get_example_service() -> ExampleService:
    """Provide an ExampleService instance for dependency injection."""
    return ExampleService(prefix="[DEMO]")


@router.get(
    "/sample",
    response_model=ExampleResponse,
    summary="Get a sample response",
    description="Returns a hardcoded sample response to demonstrate the response schema.",
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
    summary="Process a text message",
    description=(
        "Accepts a message object, applies simple string transformation, "
        "and returns the result. Demonstrates the full request -> service -> response flow."
    ),
    responses={
        200: {"description": "Successful processing"},
        400: VALIDATION_ERROR_RESPONSE,
    },
)
def process_message(
    request: ExampleRequest, service: Annotated[ExampleService, Depends(get_example_service)]
) -> ExampleResponse:
    """Process an input message using the ExampleService."""
    return service.process(request)
