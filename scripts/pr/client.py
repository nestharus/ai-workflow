"""GitHub and Linear operations client for PR management and ticket tracking.

Usage:
    uv run pr fetch-threads --pr <number> --output-dir <path>
    uv run pr commit-push --worktree <path> --message <msg> [--set-upstream]
    uv run pr post-reply --pr <number> --thread-file <file> --body <text>
    uv run pr resolve-thread --thread-file <file>
    uv run pr deferred-comment --thread-file <file> --body <text>
    uv run pr import-local-tasks --output-dir <path> <body_file1> <body_file2> ...
    uv run pr post-deferred-replies --pr <number> --threads-dir <path>
    uv run pr request-review --pr <number>
    uv run pr get-pr <ticket-id>
    uv run pr get-changed-files --pr <number>
    uv run pr set-ticket-done --ticket <id>
    uv run pr merge-pr --pr <number>
    uv run pr squash-rebase --worktree <path> --base-branch <branch>
    uv run pr merge --ticket <id> --pr <n> --worktree <path> --branch <name> --base-branch <b>
    uv run pr setup-worktree <ticket-id>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.pr import commands


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="GitHub PR operations client",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # fetch-threads command
    fetch_parser = subparsers.add_parser(
        "fetch-threads",
        help="Fetch unresolved threads, filter, format, and save to files",
    )
    fetch_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to fetch threads from",
    )
    fetch_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write thread files to",
    )

    # commit-push command
    commit_parser = subparsers.add_parser(
        "commit-push",
        help="Commit and push changes from a worktree",
    )
    commit_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    commit_parser.add_argument(
        "--message",
        required=True,
        help="Commit message",
    )
    commit_parser.add_argument(
        "--set-upstream",
        action="store_true",
        help="Set upstream tracking with -u flag (for new branches)",
    )

    # post-reply command
    reply_parser = subparsers.add_parser(
        "post-reply",
        help="Post a reply to a PR comment",
    )
    reply_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )
    reply_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )
    reply_parser.add_argument(
        "--body",
        required=True,
        help="Reply body text",
    )

    # resolve-thread command
    resolve_parser = subparsers.add_parser(
        "resolve-thread",
        help="Resolve a review thread",
    )
    resolve_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )

    # deferred-comment command
    deferred_parser = subparsers.add_parser(
        "deferred-comment",
        help="Store a deferred reply in a thread file for later posting",
    )
    deferred_parser.add_argument(
        "--thread-file",
        type=Path,
        required=True,
        help="Path to thread JSON file",
    )
    deferred_parser.add_argument(
        "--body",
        required=True,
        help="Reply body text to store",
    )

    # import-local-tasks command
    import_tasks_parser = subparsers.add_parser(
        "import-local-tasks",
        help="Import local task body files into JSON task files",
    )
    import_tasks_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write the local task JSON files to",
    )
    import_tasks_parser.add_argument(
        "body_files",
        nargs="+",
        type=Path,
        help="Paths to body files (plain text with task content)",
    )

    # post-deferred-replies command
    post_replies_parser = subparsers.add_parser(
        "post-deferred-replies",
        help="Post deferred replies from thread files to a PR",
    )
    post_replies_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )
    post_replies_parser.add_argument(
        "--threads-dir",
        type=Path,
        required=True,
        help="Directory containing thread files with deferred replies",
    )

    # request-review command
    review_parser = subparsers.add_parser(
        "request-review",
        help="Request a CodeRabbit review on a PR",
    )
    review_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )

    # open-pr command
    open_parser = subparsers.add_parser(
        "open-pr",
        help="Create a new PR for a branch",
    )
    open_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    open_parser.add_argument(
        "--title",
        required=True,
        help="PR title",
    )
    open_parser.add_argument(
        "--body",
        required=True,
        help="PR body text",
    )
    open_parser.add_argument(
        "--branch",
        required=True,
        help="Branch name for the PR head",
    )

    # get-pr command
    pr_info_parser = subparsers.add_parser(
        "get-pr",
        help="Get PR info for a Linear ticket (branch name, PR number, PR URL, base branch)",
    )
    pr_info_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-123)",
    )

    # get-changed-files command
    changed_files_parser = subparsers.add_parser(
        "get-changed-files",
        help="Get list of files changed in a PR",
    )
    changed_files_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number",
    )

    # set-ticket-done command
    done_parser = subparsers.add_parser(
        "set-ticket-done",
        help="Mark a Linear ticket as Done",
    )
    done_parser.add_argument(
        "--ticket",
        required=True,
        help="Linear ticket ID (e.g., NES-123)",
    )

    # merge-pr command (simple merge only)
    merge_parser = subparsers.add_parser(
        "merge-pr",
        help="Merge a PR using squash merge (simple)",
    )
    merge_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to merge",
    )

    # squash-rebase command
    squash_rebase_parser = subparsers.add_parser(
        "squash-rebase",
        help="Squash all commits and rebase onto base branch",
    )
    squash_rebase_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    squash_rebase_parser.add_argument(
        "--base-branch",
        required=True,
        help="Target branch to rebase onto",
    )

    # merge command (full workflow)
    merge_workflow_parser = subparsers.add_parser(
        "merge",
        help="Complete merge workflow: merge PR, cleanup, sync, mark done",
    )
    merge_workflow_parser.add_argument(
        "--ticket",
        required=True,
        help="Linear ticket ID (e.g., NES-123)",
    )
    merge_workflow_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to merge",
    )
    merge_workflow_parser.add_argument(
        "--worktree",
        type=Path,
        required=True,
        help="Path to the git worktree",
    )
    merge_workflow_parser.add_argument(
        "--branch",
        required=True,
        help="Branch name to delete",
    )
    merge_workflow_parser.add_argument(
        "--base-branch",
        required=True,
        help="Target branch to sync",
    )

    # setup-worktree command
    setup_worktree_parser = subparsers.add_parser(
        "setup-worktree",
        help="Setup a git worktree for a Linear ticket",
    )
    setup_worktree_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-87)",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point for the GitHub client."""
    args = parse_args(argv)

    if args.command == "fetch-threads":
        return commands.fetch_threads_command(args.pr, args.output_dir)
    if args.command == "commit-push":
        return commands.commit_push_command(
            args.worktree, args.message, set_upstream=args.set_upstream
        )
    if args.command == "post-reply":
        return commands.post_reply_command(args.pr, args.thread_file, args.body)
    if args.command == "resolve-thread":
        return commands.resolve_thread_command(args.thread_file)
    if args.command == "deferred-comment":
        return commands.deferred_comment_command(args.thread_file, args.body)
    if args.command == "import-local-tasks":
        return commands.import_local_tasks_command(args.output_dir, args.body_files)
    if args.command == "post-deferred-replies":
        return commands.post_deferred_replies_command(args.pr, args.threads_dir)
    if args.command == "request-review":
        return commands.request_review_command(args.pr)
    if args.command == "open-pr":
        return commands.open_pr_command(args.worktree, args.title, args.body, args.branch)
    if args.command == "get-pr":
        return commands.get_pr_command(args.ticket_id)
    if args.command == "get-changed-files":
        return commands.get_changed_files_command(args.pr)
    if args.command == "set-ticket-done":
        return commands.set_ticket_done_command(args.ticket)
    if args.command == "merge-pr":
        return commands.merge_pr_command(args.pr)
    if args.command == "squash-rebase":
        return commands.squash_rebase_command(args.worktree, args.base_branch)
    if args.command == "merge":
        return commands.merge_workflow_command(
            args.ticket,
            args.pr,
            args.worktree,
            args.branch,
            args.base_branch,
        )
    if args.command == "setup-worktree":
        return commands.setup_worktree_command(args.ticket_id)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
