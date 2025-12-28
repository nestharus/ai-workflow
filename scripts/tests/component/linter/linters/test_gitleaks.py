from scripts.dev.linter.linters.gitleaks import (
    GITLEAKS_CLI_NOT_FOUND,
    GITLEAKS_CONFIG_MISSING,
    GITLEAKS_CONFIG_UNREADABLE,
    GITLEAKS_TIMEOUT_MSG,
    GitleaksLinter,
)


class TestGitleaksLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = GitleaksLinter()
        assert linter.name == "gitleaks"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = GitleaksLinter()
        assert linter.supports_file_filtering is True
