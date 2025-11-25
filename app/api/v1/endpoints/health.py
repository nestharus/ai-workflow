"""Health check route for uptime monitoring."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

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
)
async def health_check() -> HealthResponse:
    """Return service health status."""
    return HealthResponse(status="ok")
