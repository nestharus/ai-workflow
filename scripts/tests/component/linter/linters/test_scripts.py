from scripts.dev.linter.linters.scripts import ScriptsLinter


class TestScriptsLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = ScriptsLinter()
        assert linter.name == "scripts"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = ScriptsLinter()
        assert linter.supports_file_filtering is True
