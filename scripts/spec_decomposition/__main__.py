"""CLI entry point for spec decomposition.

Usage:
    uv run python -m scripts.spec_decomposition init <spec_path> [--workspace <path>]
    uv run python -m scripts.spec_decomposition extract-entity --workspace <path> --entity <name> --evidence <json>
    uv run python -m scripts.spec_decomposition extract-relation --workspace <path> --from <id> --to <id> --type <type> --evidence <json>
    uv run python -m scripts.spec_decomposition extract-context --workspace <path> --entity <id> --evidence <json>
    uv run python -m scripts.spec_decomposition finalize --workspace <path>
"""

from __future__ import annotations

import sys

from scripts.spec_decomposition.cli import main

if __name__ == "__main__":
    sys.exit(main())
