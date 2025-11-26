"""Entry point for generating the OpenAPI schema via `uv run gen_openapi`."""

from __future__ import annotations

import os
import sys
import traceback

from tools.gen_openapi import main as generate_openapi


def _debug_enabled() -> bool:
    debug_value = os.getenv("DEBUG") or os.getenv("VERBOSE")
    return bool(debug_value and debug_value.lower() in {"1", "true", "yes", "on"})


def _is_local_environment() -> bool:
    """Check if running in a local development environment."""
    env = os.getenv("ENV", "").lower()
    ci = os.getenv("CI", "").lower()
    return env in {"", "local", "dev", "development"} and ci not in {"true", "1", "yes"}


def main() -> int:
    """Delegate OpenAPI generation and normalize exit codes."""
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
        generate_openapi()
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
