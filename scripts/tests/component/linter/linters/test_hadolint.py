from scripts.dev.linter.linters.hadolint import HadolintLinter


class TestHadolintLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = HadolintLinter()
        assert linter.name == "hadolint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = HadolintLinter()
        assert linter.supports_file_filtering is True
