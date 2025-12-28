from scripts.dev.zip_changes import (
    GitCommandError,
    get_commit_files,
    get_uncommitted_files,
    run_git_command,
)


class TestGitCommandError:
    def test_stores_command(self) -> None:
        """Should store the command that failed."""
        cmd = ["git", "status"]
        error = GitCommandError(cmd, 1, "error message")

        assert error.cmd == cmd

    def test_stores_returncode(self) -> None:
        """Should store the return code."""
        error = GitCommandError(["git"], 42, "error message")

        assert error.returncode == 42

    def test_stores_stderr(self) -> None:
        """Should store the stderr output."""
        error = GitCommandError(["git"], 1, "error message")

        assert error.stderr == "error message"

    def test_formats_message(self) -> None:
        """Should format a descriptive error message."""
        error = GitCommandError(["git", "status"], 1, "fatal: not a repo")

        assert "git status" in str(error)
        assert "exit 1" in str(error)
        assert "fatal: not a repo" in str(error)
