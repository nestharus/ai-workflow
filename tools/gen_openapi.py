"""Generate the OpenAPI schema JSON for the AI Workflow API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

if TYPE_CHECKING:
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


def main() -> None:
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


if __name__ == "__main__":
    main()
