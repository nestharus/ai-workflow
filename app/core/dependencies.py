"""Dependency injection utilities for FastAPI routes."""

from functools import lru_cache

from app.core.settings import Settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings."""
    return Settings()  # type: ignore[call-arg]
