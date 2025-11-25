"""FastAPI app construction and OpenAPI schema helpers."""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from app.core.settings import Settings
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import ORJSONResponse

from app.api.v1.endpoints.health import health_check
from app.api.v1.router import api_router
from app.contracts.errors import HTTPValidationError
from app.core.exceptions import validation_exception_handler
from app.infrastructure.db_connections import (
    ElasticsearchWrapper,
    SurrealDBPool,
    create_elasticsearch_wrapper,
    create_surrealdb_pool,
)

logger = logging.getLogger(__name__)
OPENAPI_DEFS_KEY: Final[str] = "$defs"


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        surreal_pool: SurrealDBPool | None = None
        elasticsearch_client: ElasticsearchWrapper | None = None
        try:
            surreal_pool = await create_surrealdb_pool(settings)
            app.state.surrealdb_pool = surreal_pool
            logger.info("Initialized SurrealDB pool")

            elasticsearch_client = await create_elasticsearch_wrapper(settings)
            app.state.elasticsearch_client = elasticsearch_client
            logger.info("Initialized Elasticsearch client")

            yield
        except Exception:
            logger.exception("Failed to initialize application resources")
            raise
        finally:
            if elasticsearch_client is not None:
                try:
                    await elasticsearch_client.close()
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception("Failed to close Elasticsearch client cleanly")
            if surreal_pool is not None:
                try:
                    await surreal_pool.close()
                except Exception:  # pragma: no cover - defensive logging
                    logger.exception("Failed to close SurrealDB pool cleanly")

    return lifespan


def create_app(settings: Settings) -> FastAPI:
    """Construct and configure the FastAPI application instance.

    Args:
        settings: Validated runtime options.

    Returns:
        FastAPI: Application wired with orjson responses.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        default_response_class=ORJSONResponse,
        lifespan=_lifespan(settings),
    )
    app.state.settings = settings
    # Mount versioned API router; keeps new endpoints scoped under /api/v1.
    app.include_router(api_router, prefix="/api/v1")
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_api_route("/health", health_check, methods=["GET"], include_in_schema=False)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
        )
        schema_definitions = app.openapi_schema.setdefault("components", {}).setdefault(
            "schemas", {}
        )
        error_schema = HTTPValidationError.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        schema_definitions["HTTPValidationError"] = error_schema
        if OPENAPI_DEFS_KEY in error_schema:
            for name, definition in error_schema[OPENAPI_DEFS_KEY].items():
                schema_definitions[name] = definition
            del error_schema[OPENAPI_DEFS_KEY]
        if (
            "ValidationError" in schema_definitions
            and "ValidationErrorDetail" in schema_definitions
        ):
            schema_definitions["ValidationError"] = schema_definitions["ValidationErrorDetail"]
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app
