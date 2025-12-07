"""Command-line interface for Linear client operations.

This module provides simple CLI commands for common Linear operations,
intended to simplify usage in shell scripts and Claude command files.
"""

import argparse
import json
import sys
from typing import NoReturn

from scripts.clients.linear_client import LinearClient, LinearClientError


class JsonArgumentParser(argparse.ArgumentParser):
    """ArgumentParser subclass that outputs JSON errors to maintain consistent output format."""

    def error(self, message: str) -> NoReturn:
        """Output structured JSON error and exit with code 2."""
        print(json.dumps({"ok": False, "error": {"code": "INVALID_INPUT", "message": message}}))
        sys.exit(2)


def get_issue(issue_id: str) -> None:
    """Fetch and print issue details as JSON."""
    client = LinearClient()
    issue = client.get_issue(issue_id)
    print(json.dumps({"ok": True, "data": issue}, indent=2))


def list_projects() -> None:
    """List and print projects as JSON (first page only)."""
    client = LinearClient()
    projects = client.list_projects()
    print(json.dumps({"ok": True, "data": {"projects": projects}}, indent=2))


def list_teams() -> None:
    """List and print all teams as JSON."""
    client = LinearClient()
    teams = client.list_teams()
    print(json.dumps({"ok": True, "data": {"teams": teams}}, indent=2))


def list_comments(issue_id: str) -> None:
    """List and print comments on an issue as JSON."""
    client = LinearClient()
    comments = client.list_comments(issue_id)
    print(json.dumps({"ok": True, "data": {"comments": comments}}, indent=2))


def create_issue(
    team: str,
    title: str,
    description: str | None = None,
    project: str | None = None,
) -> None:
    """Create a new issue and print result as JSON."""
    client = LinearClient()
    issue = client.create_issue(
        team=team,
        title=title,
        description=description,
        project=project,
    )
    print(json.dumps({"ok": True, "data": issue}, indent=2))


def update_issue(
    issue_id: str,
    description: str | None = None,
) -> None:
    """Update an issue description and print result as JSON."""
    client = LinearClient()
    issue = client.update_issue(
        issue_id=issue_id,
        description=description,
    )
    print(json.dumps({"ok": True, "data": issue}, indent=2))


def create_comment(issue_id: str, body: str) -> None:
    """Create a comment on an issue and print result as JSON."""
    client = LinearClient()
    comment = client.create_comment(issue_id=issue_id, body=body)
    print(json.dumps({"ok": True, "data": comment}, indent=2))


def main() -> None:
    """Parse arguments and dispatch to appropriate command."""
    parser = JsonArgumentParser(
        description="CLI for Linear client operations",
        prog="linear",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # get-issue command
    get_issue_parser = subparsers.add_parser("get-issue", help="Fetch issue details")
    get_issue_parser.add_argument("issue_id", help="Issue ID (e.g., NES-24)")

    # list-projects command
    subparsers.add_parser("list-projects", help="List projects (first page only)")

    # list-teams command
    subparsers.add_parser("list-teams", help="List all teams")

    # list-comments command
    list_comments_parser = subparsers.add_parser("list-comments", help="List comments on an issue")
    list_comments_parser.add_argument("issue_id", help="Issue ID (e.g., NES-24)")

    # create-issue command
    create_issue_parser = subparsers.add_parser("create-issue", help="Create a new issue")
    create_issue_parser.add_argument(
        "--team", required=True, help="Team identifier (UUID, key, or name)"
    )
    create_issue_parser.add_argument("--title", required=True, help="Issue title")
    create_issue_parser.add_argument("--description", help="Issue description")
    create_issue_parser.add_argument("--project", help="Project ID")

    # update-issue command
    update_issue_parser = subparsers.add_parser("update-issue", help="Update an issue description")
    update_issue_parser.add_argument("issue_id", help="Issue ID (e.g., NES-24)")
    update_issue_parser.add_argument("--description", help="New issue description")

    # create-comment command
    create_comment_parser = subparsers.add_parser(
        "create-comment", help="Create a comment on an issue"
    )
    create_comment_parser.add_argument("issue_id", help="Issue ID (e.g., NES-24)")
    create_comment_parser.add_argument("--body", required=True, help="Comment body")

    args = parser.parse_args()

    if not args.command:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "A command is required. Available commands: get-issue, "
                        "list-projects, list-teams, list-comments, create-issue, "
                        "update-issue, create-comment",
                    },
                }
            )
        )
        sys.exit(2)

    try:
        if args.command == "get-issue":
            get_issue(args.issue_id)
        elif args.command == "list-projects":
            list_projects()
        elif args.command == "list-teams":
            list_teams()
        elif args.command == "list-comments":
            list_comments(args.issue_id)
        elif args.command == "create-issue":
            create_issue(
                team=args.team,
                title=args.title,
                description=args.description,
                project=args.project,
            )
        elif args.command == "update-issue":
            update_issue(
                issue_id=args.issue_id,
                description=args.description,
            )
        elif args.command == "create-comment":
            create_comment(issue_id=args.issue_id, body=args.body)
    except LinearClientError as e:
        print(json.dumps({"ok": False, "error": {"code": e.code, "message": e.message}}))
        sys.exit(1)


if __name__ == "__main__":
    main()
