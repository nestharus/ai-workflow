"""Generate the OpenAPI schema JSON for the AI Workflow API via `uv run app.api.generate`."""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import orjson
from fastapi import FastAPI

OPENAPI_VERSION = "3.1.0"
ALLOWED_OPENAPI_KEYS = {
    "openapi",
    "info",
    "jsonSchemaDialect",
    "servers",
    "paths",
    "components",
    "security",
    "tags",
    "externalDocs",
    "webhooks",
}
VENDOR_EXTENSION_PREFIX = "x-"


class OpenAPISchemaTypeError(TypeError):
    """Raised when FastAPI returns a non-dict schema object."""

    def __init__(self, type_name: str) -> None:
        """Record the unexpected schema type name."""
        super().__init__(f"Expected dict schema from FastAPI, got {type_name}.")


class SchemaSerializationError(RuntimeError):
    """Raised when serializing the OpenAPI schema fails."""

    def __init__(self) -> None:
        """Initialize with a serialization failure message."""
        super().__init__("Failed to serialize OpenAPI schema.")


def _debug_enabled() -> bool:
    """Check if debug output is enabled via environment variables."""
    debug_value = os.getenv("DEBUG") or os.getenv("VERBOSE")
    return bool(debug_value and debug_value.lower() in {"1", "true", "yes", "on"})


def _is_local_environment() -> bool:
    """Check if running in a local development environment."""
    env = os.getenv("ENV", "").lower()
    ci = os.getenv("CI", "").lower()
    return env in {"", "local", "dev", "development"} and ci not in {"true", "1", "yes"}


def build_application() -> FastAPI:
    """Import and return the FastAPI application instance."""
    from app.main import app

    return app


def generate_schema(app: FastAPI) -> dict[str, Any]:
    """Return the OpenAPI schema dictionary."""
    schema = app.openapi()
    if not isinstance(schema, dict):
        raise OpenAPISchemaTypeError(type(schema).__name__)
    return schema


def normalize_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Force OpenAPI 3.1 and drop unsupported top-level keys (preserving x-*)."""
    filtered_schema = {
        key: value
        for key, value in schema.items()
        if key in ALLOWED_OPENAPI_KEYS or key.startswith(VENDOR_EXTENSION_PREFIX)
    }
    filtered_schema["openapi"] = OPENAPI_VERSION
    return filtered_schema


def write_schema(schema: dict[str, Any], output_path: Path) -> None:
    """Serialize the schema to JSON and write it to disk."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = orjson.dumps(schema, option=orjson.OPT_INDENT_2).decode("utf-8")
    except orjson.JSONEncodeError as exc:
        raise SchemaSerializationError() from exc
    output_path.write_text(payload, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for OpenAPI generation."""
    parser = argparse.ArgumentParser(
        description="Generate the OpenAPI schema JSON for the AI Workflow API."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("openapi/openapi.json"),
        help="Path to write the generated OpenAPI JSON (default: openapi/openapi.json).",
    )
    return parser.parse_args()


def _generate_openapi() -> None:
    """Generate and write the OpenAPI schema, exiting on failure."""
    args = parse_args()
    output_path = Path(args.output)
    try:
        app = build_application()
        schema = normalize_openapi_schema(generate_schema(app))
        write_schema(schema, output_path)
    except (ImportError, TypeError, RuntimeError, ValueError) as exc:
        print(f"Failed to generate OpenAPI schema: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Wrote OpenAPI schema to {output_path}")


def main() -> int:
    """Entry point: set up credentials and delegate OpenAPI generation."""
    # Only set default credentials in local/development environments to prevent
    # accidental use in CI/staging/production where real credentials should be provided.
    if _is_local_environment():
        os.environ.setdefault("SURREALDB_USER", "GenUser1!Abc#")
        os.environ.setdefault("SURREALDB_PASS", "GenPass1!Xyz$")
    elif not (os.getenv("SURREALDB_USER") and os.getenv("SURREALDB_PASS")):
        print(
            "Error: SURREALDB_USER and SURREALDB_PASS must be set in non-local environments.",
            file=sys.stderr,
        )
        return 1
    try:
        _generate_openapi()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise SystemExit(code) from exc
    except Exception as exc:
        error_message = f"Failed to generate OpenAPI schema: {exc}"
        if _debug_enabled():
            print(error_message, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        else:
            print(error_message, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
