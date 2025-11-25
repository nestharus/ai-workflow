"""Health check route for uptime monitoring."""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.contracts.errors import AppError

router = APIRouter()


class HealthResponse(BaseModel):
    """Response schema for the health endpoint."""

    status: Literal["ok", "degraded", "unhealthy"]


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Readiness health check",
    description=(
        "Versioned readiness probe exposed at `/api/v1/health`, distinct from the "
        "unversioned `/health` liveness check registered at the application root."
    ),
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        }
    },
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(status="ok")
