"""Entry point for generating LLM-friendly coverage reports via `uv run llm-coverage-report`."""

from __future__ import annotations

import os
import sys
import traceback

from tools.llm_coverage_report import main as generate_llm_coverage


def _debug_enabled() -> bool:
    debug_value = os.getenv("DEBUG") or os.getenv("VERBOSE")
    return bool(debug_value and debug_value.lower() in {"1", "true", "yes", "on"})


def main() -> int:
    """Delegate LLM coverage report generation and normalize exit codes."""
    # Note: This tool is file-based (reads coverage.json, use_cases.yaml, and test files).
    # No database credentials are required.
    try:
        generate_llm_coverage()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        raise SystemExit(code) from exc
    except Exception as exc:
        error_message = f"Failed to generate LLM coverage report: {exc}"
        if _debug_enabled():
            print(error_message, file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        else:
            print(error_message, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
