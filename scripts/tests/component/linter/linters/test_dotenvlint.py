from scripts.dev.linter.linters.dotenvlint import DotenvlintLinter


class TestDotenvlintLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = DotenvlintLinter()
        assert linter.name == "dotenvlint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = DotenvlintLinter()
        assert linter.supports_file_filtering is True
