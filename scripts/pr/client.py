r"""GitHub and Linear operations client for PR management and ticket tracking.

Usage:
    uv run pr fetch-threads --pr <number> --output-dir <path>
    uv run pr commit-push --worktree <path> --message <msg> [--set-upstream]
    uv run pr post-reply --pr <number> --thread-file <file> --body <text>
    uv run pr resolve-thread --thread-file <file>
    uv run pr deferred-comment --thread-file <file> --body <text>
    uv run pr import-local-tasks --output-dir <path> [--from-file <file>] [body_files...]
    uv run pr post-deferred-replies --pr <number> --threads-dir <path>
    uv run pr request-review --pr <number>
    uv run pr get-pr [<ticket-id-or-branch>]
    uv run pr get-changed-files --pr <number>
    uv run pr set-ticket-done --ticket <id>
    uv run pr merge-pr --pr <number>
    uv run pr squash-rebase --worktree <path> --base-branch <branch>
    uv run pr merge --ticket <id> --pr <n> --working-dir <path> --branch <name>
        --base-branch <b> [--is-worktree]
    uv run pr setup-worktree <ticket-id>
    uv run pr checkout <ticket-id-or-branch>
    uv run pr get-expected-branch-name <ticket-id>
    uv run pr is-valid-branch-name --ticket <id> --branch <name>
    uv run pr extract-ticket-id [<branch-name>]
    echo "$stdout" | uv run pr extract-review-path
    uv run pr is-testable <file-path>
    uv run pr affected-tests <file-path> [--root <dir>]
    uv run pr list-unresolved-comments <ticket-id>
    uv run pr parse-coderabbit --review-file <path> --output-dir <path>
    uv run pr aggregate-tasks --input-dir <path> [--files-only]
    uv run pr promote-worktree [<identifier>]
    uv run pr cleanup-sandbox [<identifier>]
    uv run pr rebase-start [<identifier>]
    uv run pr rebase-finish [<identifier>]
    uv run pr sandbox-rebase --branch <name> --target <name>
    uv run pr sandbox-merge --branch <name> --target <name>
    uv run pr sandbox-status [--request-id <uuid>]
    echo "file1.py\nfile2.py" | uv run pr file-hash [--root <dir>] > hashes.json
    uv run pr file-hash-compare before.json after.json
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.pr import commands
from scripts.servers.sandbox.client import DEFAULT_SOCKET_PATH


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
        "--from-file",
        type=Path,
        default=None,
        help="Single file with tasks separated by ---",
    )
    import_tasks_parser.add_argument(
        "body_files",
        nargs="*",
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
        help="Get PR info for a PR ID, ticket ID, branch name, or current branch",
    )
    pr_info_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="PR ID (17/#17), ticket ID (NES-123), branch name, or omit for current branch.",
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
        default=None,
        help="Linear ticket ID (e.g., NES-123). If omitted, skips ticket operations.",
    )
    merge_workflow_parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="PR number to merge",
    )
    merge_workflow_parser.add_argument(
        "--working-dir",
        type=Path,
        required=True,
        help="Path to the working directory (worktree or repo root)",
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
    merge_workflow_parser.add_argument(
        "--is-worktree",
        action="store_true",
        help="If set, remove worktree and delete branch after merge",
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

    # checkout command
    checkout_parser = subparsers.add_parser(
        "checkout",
        help="Checkout an existing branch into a worktree",
    )
    checkout_parser.add_argument(
        "identifier",
        help="Linear ticket ID (e.g., NES-87) or branch name",
    )

    # get-expected-branch-name command
    expected_branch_parser = subparsers.add_parser(
        "get-expected-branch-name",
        help="Get the expected branch name for a Linear ticket",
    )
    expected_branch_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-87)",
    )

    # is-valid-branch-name command
    valid_branch_parser = subparsers.add_parser(
        "is-valid-branch-name",
        help="Check if a branch name matches the expected pattern for a ticket",
    )
    valid_branch_parser.add_argument(
        "--ticket",
        required=True,
        help="Linear ticket ID (e.g., NES-87)",
    )
    valid_branch_parser.add_argument(
        "--branch",
        required=True,
        help="Branch name to validate",
    )

    # extract-ticket-id command
    extract_ticket_parser = subparsers.add_parser(
        "extract-ticket-id",
        help="Extract and validate ticket ID from branch name",
    )
    extract_ticket_parser.add_argument(
        "branch_name",
        nargs="?",
        default=None,
        help="Branch name to parse. If omitted, uses current branch.",
    )

    # extract-review-path command
    subparsers.add_parser(
        "extract-review-path",
        help="Extract review file path from stdin (pipe CodeRabbit output)",
    )

    # is-testable command
    is_testable_parser = subparsers.add_parser(
        "is-testable",
        help="Check if a file requires testing",
    )
    is_testable_parser.add_argument(
        "file_path",
        help="Path to the file to check",
    )

    # affected-tests command
    affected_tests_parser = subparsers.add_parser(
        "affected-tests",
        help="Find all test files affected by changes to a source file",
    )
    affected_tests_parser.add_argument(
        "file_path",
        help="Path to the source file",
    )
    affected_tests_parser.add_argument(
        "--root",
        default=None,
        help="Repository root directory (default: cwd)",
    )

    # list-unresolved-comments command
    unresolved_comments_parser = subparsers.add_parser(
        "list-unresolved-comments",
        help="List unresolved comments for a Linear ticket",
    )
    unresolved_comments_parser.add_argument(
        "ticket_id",
        help="Linear ticket ID (e.g., NES-123)",
    )

    # parse-coderabbit command
    parse_coderabbit_parser = subparsers.add_parser(
        "parse-coderabbit",
        help="Parse a CodeRabbit review file into task JSON files",
    )
    parse_coderabbit_parser.add_argument(
        "--review-file",
        type=Path,
        required=True,
        help="Path to the CodeRabbit review file",
    )
    parse_coderabbit_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write task JSON files to",
    )

    # aggregate-tasks command
    aggregate_tasks_parser = subparsers.add_parser(
        "aggregate-tasks",
        help="Aggregate tasks and threads by file",
    )
    aggregate_tasks_parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help=(
            "Directory containing task JSON files (coderabbit_*.json, thread_*.json, local_*.json)"
        ),
    )
    aggregate_tasks_parser.add_argument(
        "--files-only",
        action="store_true",
        help="Output only file paths (one per line) for piping to file-hash",
    )

    # promote-worktree command
    promote_parser = subparsers.add_parser(
        "promote-worktree",
        help="Create a sandbox for rebase/merge (keeps source unblocked)",
    )
    promote_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="PR ID (17/#17), ticket ID (NES-123), branch name, or omit for current branch.",
    )

    # cleanup-sandbox command
    cleanup_parser = subparsers.add_parser(
        "cleanup-sandbox",
        help="Remove a rebase sandbox created by promote-worktree",
    )
    cleanup_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="PR ID, ticket ID, branch name, or omit for current branch.",
    )

    # rebase-start command
    rebase_start_parser = subparsers.add_parser(
        "rebase-start",
        help="Create sandbox, gather context, squash and rebase (returns conflict info)",
    )
    rebase_start_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="PR ID (17/#17), ticket ID (NES-123), branch name, or omit for current branch.",
    )

    # rebase-finish command
    rebase_finish_parser = subparsers.add_parser(
        "rebase-finish",
        help="Force push, sync source worktree, and cleanup sandbox",
    )
    rebase_finish_parser.add_argument(
        "identifier",
        nargs="?",
        default=None,
        help="PR ID (17/#17), ticket ID (NES-123), branch name, or omit for current branch.",
    )

    # sandbox-rebase command
    sandbox_rebase_parser = subparsers.add_parser(
        "sandbox-rebase",
        help="Rebase a branch onto a target using the sandbox server",
    )
    sandbox_rebase_parser.add_argument(
        "--branch",
        required=True,
        help="Branch to rebase",
    )
    sandbox_rebase_parser.add_argument(
        "--target",
        required=True,
        help="Target branch to rebase onto",
    )
    sandbox_rebase_parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help="Path to sandbox server socket",
    )
    sandbox_rebase_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress messages",
    )

    # sandbox-merge command
    sandbox_merge_parser = subparsers.add_parser(
        "sandbox-merge",
        help="Merge a target branch into a branch using the sandbox server",
    )
    sandbox_merge_parser.add_argument(
        "--branch",
        required=True,
        help="Branch to merge into",
    )
    sandbox_merge_parser.add_argument(
        "--target",
        required=True,
        help="Target branch to merge from",
    )
    sandbox_merge_parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help="Path to sandbox server socket",
    )
    sandbox_merge_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print progress messages",
    )

    # sandbox-status command
    sandbox_status_parser = subparsers.add_parser(
        "sandbox-status",
        help="Get status of sandbox operations",
    )
    sandbox_status_parser.add_argument(
        "--request-id",
        default=None,
        help="Specific request ID (omit for all)",
    )
    sandbox_status_parser.add_argument(
        "--socket",
        default=DEFAULT_SOCKET_PATH,
        help="Path to sandbox server socket",
    )

    # file-hash command (reads file list from stdin, outputs hashes to stdout)
    file_hash_parser = subparsers.add_parser(
        "file-hash",
        help="Hash files from stdin, output JSON to stdout",
    )
    file_hash_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Root directory for resolving relative paths (default: cwd)",
    )

    # file-hash-compare command
    file_hash_compare_parser = subparsers.add_parser(
        "file-hash-compare",
        help="Compare two hash files (exit 0=identical, 1=different, 2=error)",
    )
    file_hash_compare_parser.add_argument(
        "file1",
        type=Path,
        help="First hash JSON file",
    )
    file_hash_compare_parser.add_argument(
        "file2",
        type=Path,
        help="Second hash JSON file",
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
        return commands.import_local_tasks_command(
            args.output_dir, args.body_files or None, args.from_file
        )
    if args.command == "post-deferred-replies":
        return commands.post_deferred_replies_command(args.pr, args.threads_dir)
    if args.command == "request-review":
        return commands.request_review_command(args.pr)
    if args.command == "open-pr":
        return commands.open_pr_command(args.worktree, args.title, args.body, args.branch)
    if args.command == "get-pr":
        return commands.get_pr_command(args.identifier)
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
            args.working_dir,
            args.branch,
            args.base_branch,
            is_worktree=args.is_worktree,
        )
    if args.command == "setup-worktree":
        return commands.setup_worktree_command(args.ticket_id)
    if args.command == "checkout":
        return commands.checkout_worktree_command(args.identifier)
    if args.command == "get-expected-branch-name":
        return commands.get_expected_branch_name_command(args.ticket_id)
    if args.command == "is-valid-branch-name":
        return commands.is_valid_branch_name_command(args.ticket, args.branch)
    if args.command == "extract-ticket-id":
        return commands.extract_ticket_id_command(args.branch_name)
    if args.command == "extract-review-path":
        return commands.extract_review_path_command()
    if args.command == "is-testable":
        return commands.is_testable_command(args.file_path)
    if args.command == "affected-tests":
        return commands.affected_tests_command(args.file_path, args.root)
    if args.command == "list-unresolved-comments":
        return commands.list_unresolved_comments_command(args.ticket_id)
    if args.command == "parse-coderabbit":
        return commands.parse_coderabbit_command(args.review_file, args.output_dir)
    if args.command == "aggregate-tasks":
        return commands.aggregate_tasks_command(args.input_dir, files_only=args.files_only)
    if args.command == "promote-worktree":
        return commands.promote_worktree_command(args.identifier)
    if args.command == "cleanup-sandbox":
        return commands.cleanup_sandbox_command(args.identifier)
    if args.command == "rebase-start":
        return commands.rebase_start_command(args.identifier)
    if args.command == "rebase-finish":
        return commands.rebase_finish_command(args.identifier)
    if args.command == "sandbox-rebase":
        return commands.sandbox_rebase_command(args.branch, args.target, args.socket, args.verbose)
    if args.command == "sandbox-merge":
        return commands.sandbox_merge_command(args.branch, args.target, args.socket, args.verbose)
    if args.command == "sandbox-status":
        return commands.sandbox_status_command(args.request_id, args.socket)
    if args.command == "file-hash":
        return commands.file_hash_command(args.root)
    if args.command == "file-hash-compare":
        return commands.file_hash_compare_command(args.file1, args.file2)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
