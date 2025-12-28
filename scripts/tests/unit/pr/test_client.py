from pathlib import Path
from unittest.mock import patch

from scripts.pr.client import main, parse_args


class TestMain:
    def test_fetch_threads_command(self) -> None:
        """Test main dispatches fetch-threads command."""
        with patch("scripts.pr.client.commands.fetch_threads_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["fetch-threads", "--pr", "42", "--output-dir", "/tmp/out"])
            assert result == 0
            mock_cmd.assert_called_once_with(42, Path("/tmp/out"))

    def test_commit_push_command(self) -> None:
        """Test main dispatches commit-push command."""
        with patch("scripts.pr.client.commands.commit_push_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(
                ["commit-push", "--worktree", "/tmp/wt", "--message", "fix", "--set-upstream"]
            )
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp/wt"), "fix", set_upstream=True)

    def test_post_reply_command(self) -> None:
        """Test main dispatches post-reply command."""
        with patch("scripts.pr.client.commands.post_reply_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(
                ["post-reply", "--pr", "10", "--thread-file", "/tmp/t.json", "--body", "OK"]
            )
            assert result == 0
            mock_cmd.assert_called_once_with(10, Path("/tmp/t.json"), "OK")

    def test_resolve_thread_command(self) -> None:
        """Test main dispatches resolve-thread command."""
        with patch("scripts.pr.client.commands.resolve_thread_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["resolve-thread", "--thread-file", "/tmp/t.json"])
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp/t.json"))

    def test_deferred_comment_command(self) -> None:
        """Test main dispatches deferred-comment command."""
        with patch("scripts.pr.client.commands.deferred_comment_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["deferred-comment", "--thread-file", "/tmp/t.json", "--body", "Later"])
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp/t.json"), "Later")

    def test_import_local_tasks_command(self) -> None:
        """Test main dispatches import-local-tasks command."""
        with patch("scripts.pr.client.commands.import_local_tasks_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["import-local-tasks", "--output-dir", "/tmp", "b1.txt", "b2.txt"])
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp"), [Path("b1.txt"), Path("b2.txt")])

    def test_post_deferred_replies_command(self) -> None:
        """Test main dispatches post-deferred-replies command."""
        with patch("scripts.pr.client.commands.post_deferred_replies_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["post-deferred-replies", "--pr", "5", "--threads-dir", "/tmp/t"])
            assert result == 0
            mock_cmd.assert_called_once_with(5, Path("/tmp/t"))

    def test_request_review_command(self) -> None:
        """Test main dispatches request-review command."""
        with patch("scripts.pr.client.commands.request_review_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["request-review", "--pr", "99"])
            assert result == 0
            mock_cmd.assert_called_once_with(99)

    def test_open_pr_command(self) -> None:
        """Test main dispatches open-pr command."""
        with patch("scripts.pr.client.commands.open_pr_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(
                [
                    "open-pr",
                    "--worktree",
                    "/tmp/wt",
                    "--title",
                    "Title",
                    "--body",
                    "Body",
                    "--branch",
                    "br",
                ]
            )
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp/wt"), "Title", "Body", "br")

    def test_get_pr_command(self) -> None:
        """Test main dispatches get-pr command."""
        with patch("scripts.pr.client.commands.get_pr_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["get-pr", "NES-123"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-123")

    def test_get_changed_files_command(self) -> None:
        """Test main dispatches get-changed-files command."""
        with patch("scripts.pr.client.commands.get_changed_files_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["get-changed-files", "--pr", "50"])
            assert result == 0
            mock_cmd.assert_called_once_with(50)

    def test_set_ticket_done_command(self) -> None:
        """Test main dispatches set-ticket-done command."""
        with patch("scripts.pr.client.commands.set_ticket_done_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["set-ticket-done", "--ticket", "NES-100"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-100")

    def test_merge_pr_command(self) -> None:
        """Test main dispatches merge-pr command."""
        with patch("scripts.pr.client.commands.merge_pr_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["merge-pr", "--pr", "25"])
            assert result == 0
            mock_cmd.assert_called_once_with(25)

    def test_squash_rebase_command(self) -> None:
        """Test main dispatches squash-rebase command."""
        with patch("scripts.pr.client.commands.squash_rebase_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["squash-rebase", "--worktree", "/tmp/wt", "--base-branch", "main"])
            assert result == 0
            mock_cmd.assert_called_once_with(Path("/tmp/wt"), "main")

    def test_merge_workflow_command(self) -> None:
        """Test main dispatches merge command."""
        with patch("scripts.pr.client.commands.merge_workflow_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(
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
            assert result == 0
            mock_cmd.assert_called_once_with(
                "NES-50", 100, Path("/tmp/work"), "feature", "main", is_worktree=True
            )

    def test_setup_worktree_command(self) -> None:
        """Test main dispatches setup-worktree command."""
        with patch("scripts.pr.client.commands.setup_worktree_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["setup-worktree", "NES-87"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-87")

    def test_checkout_command(self) -> None:
        """Test main dispatches checkout command."""
        with patch("scripts.pr.client.commands.checkout_worktree_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["checkout", "feature"])
            assert result == 0
            mock_cmd.assert_called_once_with("feature")

    def test_get_expected_branch_name_command(self) -> None:
        """Test main dispatches get-expected-branch-name command."""
        with patch("scripts.pr.client.commands.get_expected_branch_name_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["get-expected-branch-name", "NES-55"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-55")

    def test_is_valid_branch_name_command(self) -> None:
        """Test main dispatches is-valid-branch-name command."""
        with patch("scripts.pr.client.commands.is_valid_branch_name_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["is-valid-branch-name", "--ticket", "NES-87", "--branch", "nes-87-feat"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-87", "nes-87-feat")

    def test_extract_ticket_id_command(self) -> None:
        """Test main dispatches extract-ticket-id command."""
        with patch("scripts.pr.client.commands.extract_ticket_id_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["extract-ticket-id", "nes-123-feature"])
            assert result == 0
            mock_cmd.assert_called_once_with("nes-123-feature")

    def test_list_unresolved_comments_command(self) -> None:
        """Test main dispatches list-unresolved-comments command."""
        with patch("scripts.pr.client.commands.list_unresolved_comments_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["list-unresolved-comments", "NES-123"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-123")

    def test_promote_worktree_command(self) -> None:
        """Test main dispatches promote-worktree command."""
        with patch("scripts.pr.client.commands.promote_worktree_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["promote-worktree", "NES-123"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-123")

    def test_cleanup_sandbox_command(self) -> None:
        """Test main dispatches cleanup-sandbox command."""
        with patch("scripts.pr.client.commands.cleanup_sandbox_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["cleanup-sandbox", "NES-50"])
            assert result == 0
            mock_cmd.assert_called_once_with("NES-50")

    def test_rebase_start_command(self) -> None:
        """Test main dispatches rebase-start command."""
        with patch("scripts.pr.client.commands.rebase_start_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["rebase-start", "17"])
            assert result == 0
            mock_cmd.assert_called_once_with("17")

    def test_rebase_finish_command(self) -> None:
        """Test main dispatches rebase-finish command."""
        with patch("scripts.pr.client.commands.rebase_finish_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["rebase-finish", "#17"])
            assert result == 0
            mock_cmd.assert_called_once_with("#17")

    def test_sandbox_rebase_command(self) -> None:
        """Test main dispatches sandbox-rebase command."""
        with patch("scripts.pr.client.commands.sandbox_rebase_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["sandbox-rebase", "--branch", "feature", "--target", "main", "-v"])
            assert result == 0
            # Check the call includes socket and verbose
            mock_cmd.assert_called_once()
            call_args = mock_cmd.call_args[0]
            assert call_args[0] == "feature"
            assert call_args[1] == "main"
            assert call_args[3] is True  # verbose

    def test_sandbox_merge_command(self) -> None:
        """Test main dispatches sandbox-merge command."""
        with patch("scripts.pr.client.commands.sandbox_merge_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["sandbox-merge", "--branch", "feat", "--target", "main"])
            assert result == 0
            mock_cmd.assert_called_once()
            call_args = mock_cmd.call_args[0]
            assert call_args[0] == "feat"
            assert call_args[1] == "main"

    def test_sandbox_status_command(self) -> None:
        """Test main dispatches sandbox-status command."""
        with patch("scripts.pr.client.commands.sandbox_status_command") as mock_cmd:
            mock_cmd.return_value = 0
            result = main(["sandbox-status", "--request-id", "abc-123"])
            assert result == 0
            mock_cmd.assert_called_once()
            call_args = mock_cmd.call_args[0]
            assert call_args[0] == "abc-123"

    def test_command_returns_nonzero(self) -> None:
        """Test that main returns command's non-zero exit code."""
        with patch("scripts.pr.client.commands.fetch_threads_command") as mock_cmd:
            mock_cmd.return_value = 1
            result = main(["fetch-threads", "--pr", "42", "--output-dir", "/tmp"])
            assert result == 1
