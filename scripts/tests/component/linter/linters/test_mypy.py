from scripts.dev.linter.linters.mypy import MypyLinter


class TestMypyLinterInit:
    def test_name(self) -> None:
        """Test linter name attribute."""
        linter = MypyLinter()
        assert linter.name == "mypy"

    def test_supports_file_filtering(self) -> None:
        """Test supports_file_filtering attribute."""
        linter = MypyLinter()
        assert linter.supports_file_filtering is True
