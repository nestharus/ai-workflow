from scripts.dev.linter.linters.pymarkdown import PymarkdownLinter


class TestPymarkdownLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = PymarkdownLinter()
        assert linter.name == "pymarkdown"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = PymarkdownLinter()
        assert linter.supports_file_filtering is True
