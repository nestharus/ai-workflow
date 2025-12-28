from scripts.dev.setup import (
    UvNotFoundError,
    main,
    run_pre_commit_install,
)


class TestUvNotFoundError:
    def test_has_guidance_message(self) -> None:
        """Should include guidance to install uv."""
        error = UvNotFoundError()
        assert "uv" in str(error)
        assert "PATH" in str(error)
