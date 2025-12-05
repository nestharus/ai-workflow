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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import ORJSONResponse
from pydantic import TypeAdapter

from app.api.v1.endpoints.health import health_check
from app.api.v1.router import api_router
from app.contracts.errors import AppError, ErrorCode, HTTPValidationError
from app.core.errors import DomainError
from app.core.exceptions import (
    domain_exception_handler,
    internal_exception_handler,
    validation_exception_handler,
)
from app.core.middleware import (
    MetricsMiddleware,
    RateLimitingMiddleware,
    RequestIDMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from app.infrastructure.duckdb import DuckDBClient, create_duckdb_client
from app.infrastructure.elasticsearch import (
    ElasticsearchWrapper,
    create_elasticsearch_wrapper,
)
from app.infrastructure.surrealdb import SurrealDBPool, create_surrealdb_pool

logger = logging.getLogger(__name__)
OPENAPI_DEFS_KEY: Final[str] = "$defs"


def _register_schema(schema_definitions: dict[str, Any], schema: dict[str, Any], name: str) -> None:
    """Register a schema and its nested definitions into the OpenAPI components."""
    schema_definitions[name] = schema
    if OPENAPI_DEFS_KEY in schema:
        for definition_name, definition in schema[OPENAPI_DEFS_KEY].items():
            schema_definitions[definition_name] = definition
        del schema[OPENAPI_DEFS_KEY]


def _create_custom_openapi(app: FastAPI) -> Callable[[], dict[str, Any]]:
    """Create a custom OpenAPI schema generator for the app."""

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
        ref_template = "#/components/schemas/{model}"

        error_schema = HTTPValidationError.model_json_schema(ref_template=ref_template)
        _register_schema(schema_definitions, error_schema, "HTTPValidationError")

        app_error_schema = AppError.model_json_schema(ref_template=ref_template)
        _register_schema(schema_definitions, app_error_schema, "AppError")

        error_code_schema = TypeAdapter(ErrorCode).json_schema(ref_template=ref_template)
        _register_schema(schema_definitions, error_code_schema, "ErrorCode")
        if (
            "ValidationError" in schema_definitions
            and "ValidationErrorDetail" in schema_definitions
        ):
            schema_definitions["ValidationError"] = schema_definitions["ValidationErrorDetail"]
        return app.openapi_schema

    return custom_openapi


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """Register all middleware on the FastAPI application."""
    # Middleware registration (last added runs first on request path):
    # TrustedHost (outer) -> HTTPS redirect -> CORS -> Security headers -> GZip ->
    # RequestID -> RateLimiting -> Metrics -> RequestLogging (inner) -> route handler.

    # Observability middleware (innermost, runs closest to route handler)
    if settings.enable_request_logging:
        app.add_middleware(RequestLoggingMiddleware)

    if settings.enable_metrics:
        app.add_middleware(MetricsMiddleware)

    if settings.enable_rate_limiting:
        app.add_middleware(
            RateLimitingMiddleware,
            requests_per_window=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )

    if settings.enable_request_id:
        app.add_middleware(RequestIDMiddleware)

    if settings.enable_gzip:
        app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)

    app.add_middleware(
        SecurityHeadersMiddleware,
        enforce_https=settings.enforce_https,
    )

    if settings.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_origin_regex=settings.cors_allow_origin_regex,
            allow_methods=settings.cors_allow_methods,
            allow_headers=settings.cors_allow_headers,
            expose_headers=settings.cors_expose_headers,
            allow_credentials=settings.cors_allow_credentials,
            max_age=settings.cors_max_age,
        )

    if settings.enforce_https:
        app.add_middleware(HTTPSRedirectMiddleware)

    if settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        surreal_pool: SurrealDBPool | None = None
        elasticsearch_client: ElasticsearchWrapper | None = None
        duckdb_client: DuckDBClient | None = None
        try:
            surreal_pool = await create_surrealdb_pool(settings)
            app.state.surrealdb_pool = surreal_pool
            logger.info("Initialized SurrealDB pool")

            elasticsearch_client = await create_elasticsearch_wrapper(settings)
            app.state.elasticsearch_client = elasticsearch_client
            logger.info("Initialized Elasticsearch client")

            duckdb_client = await create_duckdb_client(settings)
            app.state.duckdb_client = duckdb_client
            logger.info("Initialized DuckDB client")

            yield
        except Exception:
            logger.exception("Failed to initialize application resources")
            raise
        finally:
            if duckdb_client is not None:
                try:
                    await duckdb_client.close()
                except Exception:
                    logger.exception("Failed to close DuckDB client cleanly")
            if elasticsearch_client is not None:
                try:
                    await elasticsearch_client.close()
                except Exception:
                    logger.exception("Failed to close Elasticsearch client cleanly")
            if surreal_pool is not None:
                try:
                    await surreal_pool.close()
                except Exception:
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
    app.include_router(api_router, prefix=settings.api_prefix)
    app.add_exception_handler(DomainError, domain_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, internal_exception_handler)
    app.add_api_route("/health", health_check, methods=["GET"], include_in_schema=False)

    _register_middleware(app, settings)
    app.openapi = _create_custom_openapi(app)  # type: ignore[method-assign]

    return app
