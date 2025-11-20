"""ASGI entry point for the AI Workflow API. Uses factory pattern for app creation."""

from app.core.dependencies import get_settings
from app.core.factory import create_app

settings = get_settings()
app = create_app(settings)
