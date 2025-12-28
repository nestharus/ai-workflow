from pathlib import Path

import pytest

from scripts.pr.client import main, parse_args


class TestParseArgs:
    def test_fetch_threads_command(self) -> None:
        """Test parsing fetch-threads command."""
        args = parse_args(["fetch-threads", "--pr", "42", "--output-dir", "/tmp/threads"])
        assert args.command == "fetch-threads"
        assert args.pr == 42
        assert args.output_dir == Path("/tmp/threads")

    def test_commit_push_command(self) -> None:
        """Test parsing commit-push command."""
        args = parse_args(["commit-push", "--worktree", "/tmp/wt", "--message", "fix bug"])
        assert args.command == "commit-push"
        assert args.worktree == Path("/tmp/wt")
        assert args.message == "fix bug"
        assert args.set_upstream is False

    def test_commit_push_with_set_upstream(self) -> None:
        """Test parsing commit-push with --set-upstream flag."""
        args = parse_args(
            ["commit-push", "--worktree", "/tmp/wt", "--message", "fix", "--set-upstream"]
        )
        assert args.set_upstream is True

    def test_post_reply_command(self) -> None:
        """Test parsing post-reply command."""
        args = parse_args(
            ["post-reply", "--pr", "10", "--thread-file", "/tmp/thread.json", "--body", "LGTM"]
        )
        assert args.command == "post-reply"
        assert args.pr == 10
        assert args.thread_file == Path("/tmp/thread.json")
        assert args.body == "LGTM"

    def test_resolve_thread_command(self) -> None:
        """Test parsing resolve-thread command."""
        args = parse_args(["resolve-thread", "--thread-file", "/tmp/thread.json"])
        assert args.command == "resolve-thread"
        assert args.thread_file == Path("/tmp/thread.json")

    def test_deferred_comment_command(self) -> None:
        """Test parsing deferred-comment command."""
        args = parse_args(
            ["deferred-comment", "--thread-file", "/tmp/t.json", "--body", "Will fix later"]
        )
        assert args.command == "deferred-comment"
        assert args.thread_file == Path("/tmp/t.json")
        assert args.body == "Will fix later"

    def test_import_local_tasks_command(self) -> None:
        """Test parsing import-local-tasks command."""
        args = parse_args(
            ["import-local-tasks", "--output-dir", "/tmp/out", "body1.txt", "body2.txt"]
        )
        assert args.command == "import-local-tasks"
        assert args.output_dir == Path("/tmp/out")
        assert args.body_files == [Path("body1.txt"), Path("body2.txt")]

    def test_post_deferred_replies_command(self) -> None:
        """Test parsing post-deferred-replies command."""
        args = parse_args(["post-deferred-replies", "--pr", "5", "--threads-dir", "/tmp/threads"])
        assert args.command == "post-deferred-replies"
        assert args.pr == 5
        assert args.threads_dir == Path("/tmp/threads")

    def test_request_review_command(self) -> None:
        """Test parsing request-review command."""
        args = parse_args(["request-review", "--pr", "99"])
        assert args.command == "request-review"
        assert args.pr == 99

    def test_open_pr_command(self) -> None:
        """Test parsing open-pr command."""
        args = parse_args(
            [
                "open-pr",
                "--worktree",
                "/tmp/wt",
                "--title",
                "Add feature",
                "--body",
                "Description",
                "--branch",
                "feature-branch",
            ]
        )
        assert args.command == "open-pr"
        assert args.worktree == Path("/tmp/wt")
        assert args.title == "Add feature"
        assert args.body == "Description"
        assert args.branch == "feature-branch"

    def test_get_pr_command_with_identifier(self) -> None:
        """Test parsing get-pr command with identifier."""
        args = parse_args(["get-pr", "NES-123"])
        assert args.command == "get-pr"
        assert args.identifier == "NES-123"

    def test_get_pr_command_without_identifier(self) -> None:
        """Test parsing get-pr command without identifier."""
        args = parse_args(["get-pr"])
        assert args.command == "get-pr"
        assert args.identifier is None

    def test_get_changed_files_command(self) -> None:
        """Test parsing get-changed-files command."""
        args = parse_args(["get-changed-files", "--pr", "50"])
        assert args.command == "get-changed-files"
        assert args.pr == 50

    def test_set_ticket_done_command(self) -> None:
        """Test parsing set-ticket-done command."""
        args = parse_args(["set-ticket-done", "--ticket", "NES-100"])
        assert args.command == "set-ticket-done"
        assert args.ticket == "NES-100"

    def test_merge_pr_command(self) -> None:
        """Test parsing merge-pr command."""
        args = parse_args(["merge-pr", "--pr", "25"])
        assert args.command == "merge-pr"
        assert args.pr == 25

    def test_squash_rebase_command(self) -> None:
        """Test parsing squash-rebase command."""
        args = parse_args(["squash-rebase", "--worktree", "/tmp/wt", "--base-branch", "main"])
        assert args.command == "squash-rebase"
        assert args.worktree == Path("/tmp/wt")
        assert args.base_branch == "main"

    def test_merge_workflow_command(self) -> None:
        """Test parsing merge command with all arguments."""
        args = parse_args(
            [
                "merge",
                "--ticket",
                "NES-50",
                "--pr",
                "100",
                "--working-dir",
                "/tmp/work",
                "--branch",
                "feature",
                "--base-branch",
                "main",
                "--is-worktree",
            ]
        )
        assert args.command == "merge"
        assert args.ticket == "NES-50"
        assert args.pr == 100
        assert args.working_dir == Path("/tmp/work")
        assert args.branch == "feature"
        assert args.base_branch == "main"
        assert args.is_worktree is True

    def test_merge_workflow_without_ticket(self) -> None:
        """Test parsing merge command without ticket."""
        args = parse_args(
            [
                "merge",
                "--pr",
                "100",
                "--working-dir",
                "/tmp/work",
                "--branch",
                "feature",
                "--base-branch",
                "main",
            ]
        )
        assert args.ticket is None
        assert args.is_worktree is False

    def test_setup_worktree_command(self) -> None:
        """Test parsing setup-worktree command."""
        args = parse_args(["setup-worktree", "NES-87"])
        assert args.command == "setup-worktree"
        assert args.ticket_id == "NES-87"

    def test_checkout_command(self) -> None:
        """Test parsing checkout command."""
        args = parse_args(["checkout", "feature-branch"])
        assert args.command == "checkout"
        assert args.identifier == "feature-branch"

    def test_get_expected_branch_name_command(self) -> None:
        """Test parsing get-expected-branch-name command."""
        args = parse_args(["get-expected-branch-name", "NES-55"])
        assert args.command == "get-expected-branch-name"
        assert args.ticket_id == "NES-55"

    def test_is_valid_branch_name_command(self) -> None:
        """Test parsing is-valid-branch-name command."""
        args = parse_args(
            ["is-valid-branch-name", "--ticket", "NES-87", "--branch", "nes-87-feature"]
        )
        assert args.command == "is-valid-branch-name"
        assert args.ticket == "NES-87"
        assert args.branch == "nes-87-feature"

    def test_extract_ticket_id_with_branch(self) -> None:
        """Test parsing extract-ticket-id with branch name."""
        args = parse_args(["extract-ticket-id", "nes-123-feature"])
        assert args.command == "extract-ticket-id"
        assert args.branch_name == "nes-123-feature"

    def test_extract_ticket_id_without_branch(self) -> None:
        """Test parsing extract-ticket-id without branch name."""
        args = parse_args(["extract-ticket-id"])
        assert args.command == "extract-ticket-id"
        assert args.branch_name is None

    def test_list_unresolved_comments_command(self) -> None:
        """Test parsing list-unresolved-comments command."""
        args = parse_args(["list-unresolved-comments", "NES-123"])
        assert args.command == "list-unresolved-comments"
        assert args.ticket_id == "NES-123"

    def test_promote_worktree_with_identifier(self) -> None:
        """Test parsing promote-worktree with identifier."""
        args = parse_args(["promote-worktree", "NES-123"])
        assert args.command == "promote-worktree"
        assert args.identifier == "NES-123"

    def test_promote_worktree_without_identifier(self) -> None:
        """Test parsing promote-worktree without identifier."""
        args = parse_args(["promote-worktree"])
        assert args.identifier is None

    def test_cleanup_sandbox_with_identifier(self) -> None:
        """Test parsing cleanup-sandbox with identifier."""
        args = parse_args(["cleanup-sandbox", "NES-50"])
        assert args.command == "cleanup-sandbox"
        assert args.identifier == "NES-50"

    def test_cleanup_sandbox_without_identifier(self) -> None:
        """Test parsing cleanup-sandbox without identifier."""
        args = parse_args(["cleanup-sandbox"])
        assert args.identifier is None

    def test_rebase_start_with_identifier(self) -> None:
        """Test parsing rebase-start with identifier."""
        args = parse_args(["rebase-start", "17"])
        assert args.command == "rebase-start"
        assert args.identifier == "17"

    def test_rebase_start_without_identifier(self) -> None:
        """Test parsing rebase-start without identifier."""
        args = parse_args(["rebase-start"])
        assert args.identifier is None

    def test_rebase_finish_with_identifier(self) -> None:
        """Test parsing rebase-finish with identifier."""
        args = parse_args(["rebase-finish", "#17"])
        assert args.command == "rebase-finish"
        assert args.identifier == "#17"

    def test_rebase_finish_without_identifier(self) -> None:
        """Test parsing rebase-finish without identifier."""
        args = parse_args(["rebase-finish"])
        assert args.identifier is None

    def test_sandbox_rebase_command(self) -> None:
        """Test parsing sandbox-rebase command."""
        args = parse_args(["sandbox-rebase", "--branch", "feature", "--target", "main"])
        assert args.command == "sandbox-rebase"
        assert args.branch == "feature"
        assert args.target == "main"
        assert args.verbose is False

    def test_sandbox_rebase_with_verbose(self) -> None:
        """Test parsing sandbox-rebase with verbose flag."""
        args = parse_args(["sandbox-rebase", "--branch", "f", "--target", "m", "-v"])
        assert args.verbose is True

    def test_sandbox_rebase_with_custom_socket(self) -> None:
        """Test parsing sandbox-rebase with custom socket."""
        args = parse_args(
            ["sandbox-rebase", "--branch", "f", "--target", "m", "--socket", "/custom/sock"]
        )
        assert args.socket == "/custom/sock"

    def test_sandbox_merge_command(self) -> None:
        """Test parsing sandbox-merge command."""
        args = parse_args(["sandbox-merge", "--branch", "feature", "--target", "main"])
        assert args.command == "sandbox-merge"
        assert args.branch == "feature"
        assert args.target == "main"
        assert args.verbose is False

    def test_sandbox_merge_with_verbose(self) -> None:
        """Test parsing sandbox-merge with --verbose flag."""
        args = parse_args(["sandbox-merge", "--branch", "f", "--target", "m", "--verbose"])
        assert args.verbose is True

    def test_sandbox_status_without_request_id(self) -> None:
        """Test parsing sandbox-status without request-id."""
        args = parse_args(["sandbox-status"])
        assert args.command == "sandbox-status"
        assert args.request_id is None

    def test_sandbox_status_with_request_id(self) -> None:
        """Test parsing sandbox-status with request-id."""
        args = parse_args(["sandbox-status", "--request-id", "abc-123"])
        assert args.request_id == "abc-123"

    def test_missing_required_command_raises(self) -> None:
        """Test that missing command raises error."""
        with pytest.raises(SystemExit):
            parse_args([])
