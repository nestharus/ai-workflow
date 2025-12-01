"""Run the project lint suite including formatting, type checks, and security scans."""

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"
HADOLINT_EXCLUDE_DIRS = {
    REPO_ROOT / "to_adapt",
    REPO_ROOT / "docs" / "plans",
    REPO_ROOT / "docs" / "references",
    REPO_ROOT / ".venv",
    REPO_ROOT / ".venv2",
}
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
    ".serena/**",
    "docs/plans/**",
    "docs/references/**",
]
PYMARKDOWN_TARGETS: list[str] = [
    "README.md",
    "AGENTS.md",
    "docs/**/*.md",
    "scripts/knowledge/README.md",
]


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
        dockerfiles = [
            path
            for path in REPO_ROOT.rglob("Dockerfile")
            if path.is_file()
            and not any(excluded in path.parents for excluded in HADOLINT_EXCLUDE_DIRS)
        ]
        if not dockerfiles:
            print("No Dockerfiles found for hadolint scan")
        else:
            _run_checked(
                [
                    hadolint_exe,
                    "--config",
                    str(HADOLINT_CONFIG),
                    *[str(path) for path in dockerfiles],
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
        yaml_files = [
            str(path)
            for path in REPO_ROOT.rglob("*.yml")
            if path.is_file()
            and not any(excluded in path.parts for excluded in PYMARKDOWN_EXCLUDES)
        ]
        yaml_files.extend(
            str(path)
            for path in REPO_ROOT.rglob("*.yaml")
            if path.is_file()
            and not any(excluded in path.parts for excluded in PYMARKDOWN_EXCLUDES)
        )
        if yaml_files:
            yamllint_config = str(REPO_ROOT / ".yamllint.yaml")
            _run_checked([uv_exe, "run", "yamllint", "-c", yamllint_config, *yaml_files])
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
