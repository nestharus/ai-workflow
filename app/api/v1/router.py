"""API Router aggregator for Version 1 endpoints."""

from fastapi import APIRouter

from app.api.v1.endpoints import example, health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(example.router, prefix="/example", tags=["example"])
