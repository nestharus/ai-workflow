"""Health check route for uptime monitoring."""

from typing import Literal

from fastapi import APIRouter, Request, status
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
        "unversioned `/health` liveness check registered at the application root. "
        "Checks critical dependencies (SurrealDB pool, Elasticsearch client) and "
        "returns 'unhealthy' if any are missing, 'degraded' on transient failures, "
        "or 'ok' when all dependencies are available."
    ),
    responses={
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AppError,
            "description": "Internal server error",
        }
    },
)
async def health_check(request: Request) -> HealthResponse:
    """Return service health status based on dependency availability."""
    app_state = request.app.state

    surrealdb_pool = getattr(app_state, "surrealdb_pool", None)
    elasticsearch_client = getattr(app_state, "elasticsearch_client", None)

    if surrealdb_pool is None or elasticsearch_client is None:
        return HealthResponse(status="unhealthy")

    # Check if dependencies are experiencing transient issues
    surrealdb_healthy = await surrealdb_pool.health_check()
    elasticsearch_healthy = await elasticsearch_client.health_check()

    if not surrealdb_healthy or not elasticsearch_healthy:
        return HealthResponse(status="degraded")

    return HealthResponse(status="ok")
