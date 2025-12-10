"""CLI entry point for AI commands.

Usage:
    uv run ai update-plan <ticket-id> [additional prompt]

Examples:
    # Update plan from unresolved comments
    uv run ai update-plan NES-102

    # Update plan with specific prompt
    uv run ai update-plan NES-102 "Add error handling for edge cases"

    # Via shell wrapper
    ./ai update-plan NES-102
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import NoReturn

from scripts.dev.commands import update_plan


class JsonArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that outputs JSON errors for consistency."""

    def error(self, message: str) -> NoReturn:
        """Output structured JSON error and exit with code 2."""
        print(json.dumps({"ok": False, "error": {"code": "INVALID_INPUT", "message": message}}))
        sys.exit(2)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Optional argument list for testing. Uses sys.argv if None.

    Returns:
        Parsed arguments namespace.
    """
    parser = JsonArgumentParser(
        description="AI workflow commands",
        prog="ai",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # update-plan command
    update_plan_parser = subparsers.add_parser(
        "update-plan",
        help="Update an existing implementation plan with additional requirements",
    )
    update_plan_parser.add_argument(
        "args",
        nargs="+",
        help="Ticket ID followed by optional update prompt",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for AI commands.

    Args:
        argv: Optional argument list for testing. Uses sys.argv if None.

    Returns:
        Exit code (0 for success, 1 for errors, 2 for invalid input).
    """
    args = parse_args(argv)

    if args.command == "update-plan":
        # First arg is ticket_id, rest is optional prompt
        ticket_id = args.args[0]
        prompt = " ".join(args.args[1:]) if len(args.args) > 1 else None
        return update_plan.run(ticket_id, prompt)

    # Unknown command (shouldn't happen with required=True)
    print(
        json.dumps(
            {
                "ok": False,
                "error": {"code": "UNKNOWN_COMMAND", "message": f"Unknown command: {args.command}"},
            }
        )
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
