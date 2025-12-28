from scripts.dev.linter.linters.yamllint import YamllintLinter


class TestYamllintLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = YamllintLinter()
        assert linter.name == "yamllint"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = YamllintLinter()
        assert linter.supports_file_filtering is True
