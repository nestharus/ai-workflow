"""Install pre-commit hooks via uv for consistent dev setup."""

import shutil
import subprocess


class UvNotFoundError(RuntimeError):
    """Raised when the uv CLI is unavailable on PATH during setup."""

    def __init__(self) -> None:
        """Initialize with guidance to install uv."""
        super().__init__("The `uv` CLI must be installed and on PATH to run project setup.")


def run_pre_commit_install() -> None:
    """Invoke `pre-commit install` through uv so dev dependencies are always available."""
    uv_exe = shutil.which("uv")
    if uv_exe is None:
        raise UvNotFoundError()

    subprocess.check_call([uv_exe, "run", "--group", "dev", "pre-commit", "install"])  # noqa: S603


def main() -> int:
    """Entry point for installing Git hooks and printing status."""
    try:
        run_pre_commit_install()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(
            "Failed to install pre-commit hooks; try `uv run pre-commit install` manually or "
            "`uv sync --group dev` if dependencies are missing."
        )
        return getattr(exc, "returncode", 1)

    print("Pre-commit hooks installed! Run `uv run pre-commit run --all-files` to validate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
