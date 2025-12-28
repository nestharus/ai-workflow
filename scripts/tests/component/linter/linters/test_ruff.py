from scripts.dev.linter.linters.ruff import RuffLinter


class TestRuffLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = RuffLinter()
        assert linter.name == "ruff"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = RuffLinter()
        assert linter.supports_file_filtering is True
