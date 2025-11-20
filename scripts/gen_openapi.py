"""Entry point for generating the OpenAPI schema via `uv run gen_openapi`."""

from __future__ import annotations

import os
import sys
import traceback

from tools.gen_openapi import main as generate_openapi


def _debug_enabled() -> bool:
    debug_value = os.getenv("DEBUG") or os.getenv("VERBOSE")
    return bool(debug_value and debug_value.lower() in {"1", "true", "yes", "on"})


def _ensure_surreal_credentials() -> None:
    """Provide default SurrealDB credentials for schema generation if absent.

    Defaults are strictly for local development/schema generation, must never
    be used in staging or production, and should not be committed to version
    control. Use environment-specific credentials or a local-only secrets store
    for any purpose beyond local schema generation.
    """
    # Settings validation requires complex creds; adding special flags just for
    # gen_openapi would overcomplicate things, so we use strong defaults here.
    os.environ.setdefault("SURREALDB_USER", "GenUser1!Abc#")
    os.environ.setdefault("SURREALDB_PASS", "GenPass1!Xyz$")


def main() -> int:
    """Delegate OpenAPI generation and normalize exit codes."""
    _ensure_surreal_credentials()
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
