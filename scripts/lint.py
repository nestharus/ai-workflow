"""Run the project lint suite including formatting, type checks, and security scans."""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
UV_CLI_REQUIRED = "uv CLI required to run lint"
HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"
PYMARKDOWN_EXCLUDES = [
    "__pycache__",
    ".venv*",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".sonar/**",
    ".review",
    "openapi",
    ".idea*",
    "to_adapt",
    "to_adapt/**",
    "htmlcov",
    ".coverage*",
    "coverage.xml",
    "uv.lock",
    "LICENSE",
    ".git",
    ".github",
    ".code",
    "out",
    ".uv-cache",
    ".cache",
    ".knowledge/knowledge.duckdb",
]
PYMARKDOWN_TARGETS: list[str] = ["README.md", "AGENTS.md", "docs/**", "scripts/knowledge/README.md"]


class InvalidCommandError(TypeError):
    """Raised when a command argument is malformed."""

    def __init__(self) -> None:
        """Initialize with a standard validation message."""
        super().__init__("command must be a non-empty list of strings")


def _uv() -> str:
    uv_exe = shutil.which("uv")
    if uv_exe is None:
        raise RuntimeError(UV_CLI_REQUIRED)
    return uv_exe


def _hadolint() -> str:
    hadolint_exe = shutil.which("hadolint")
    if hadolint_exe is None:
        raise RuntimeError(HADOLINT_CLI_REQUIRED)
    return hadolint_exe


def _run_checked(command: list[str]) -> None:
    """Invoke a subprocess command with error propagation."""
    if not (
        isinstance(command, list) and command and all(isinstance(part, str) for part in command)
    ):
        raise InvalidCommandError()
    subprocess.check_call(command)  # noqa: S603


def main() -> int:
    """Execute all linting steps and return a process exit code."""
    try:
        uv_exe = _uv()
        _run_checked([uv_exe, "run", "ruff", "format", "."])
        _run_checked([uv_exe, "run", "ruff", "check", "--fix", "."])
        _run_checked([uv_exe, "run", "mypy"])
        hadolint_exe = _hadolint()
        _run_checked(
            [
                hadolint_exe,
                "--config",
                str(HADOLINT_CONFIG),
                str(DOCKERFILE_PATH),
            ]
        )
        pymarkdown_cmd = [
            uv_exe,
            "run",
            "pymarkdown",
            "-c",
            str(REPO_ROOT / ".pymarkdown.json"),
            "scan",
            "-r",
            *PYMARKDOWN_TARGETS,
        ]
        for pattern in PYMARKDOWN_EXCLUDES:
            pymarkdown_cmd.extend(["-e", pattern])
        _run_checked(pymarkdown_cmd)
        if not OPENAPI_SCHEMA.exists():
            print(
                f"OpenAPI schema missing at {OPENAPI_SCHEMA}. Run `uv run gen_openapi` first.",
                file=sys.stderr,
            )
            return 1

        _run_checked(
            [
                uv_exe,
                "run",
                "checkov",
                "--config-file",
                str(CHECKOV_CONFIG),
                "--framework",
                "openapi",
                "-f",
                str(OPENAPI_SCHEMA),
            ]
        )

    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
