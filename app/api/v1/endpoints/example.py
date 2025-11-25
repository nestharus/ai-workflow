"""Example endpoint routes demonstrating service wiring."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.v1.dependencies import ExampleServiceDep
from app.contracts.errors import VALIDATION_ERROR_RESPONSE
from app.contracts.example_contract import ExampleRequest, ExampleResponse

router = APIRouter()


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
def process_message(request: ExampleRequest, service: ExampleServiceDep) -> ExampleResponse:
    """Process an input message using the ExampleService."""
    return service.process(request)
