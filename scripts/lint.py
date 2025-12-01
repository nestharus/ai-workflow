"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# Linter names in execution order
LINTER_NAMES = ["ruff", "mypy", "hadolint", "pymarkdown", "yamllint", "checkov"]
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
UV_CLI_REQUIRED = "uv CLI required to run lint"
HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"

# Lint script config file paths
LINT_HADOLINT_CONFIG = REPO_ROOT / ".lint.hadolint.yaml"
LINT_PYMARKDOWN_CONFIG = REPO_ROOT / ".lint.pymarkdown.yaml"
LINT_YAMLLINT_CONFIG = REPO_ROOT / ".lint.yamllint.yaml"


def _load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


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


def _run_ruff() -> None:
    """Run ruff format and check."""
    uv_exe = _uv()
    _run_checked([uv_exe, "run", "ruff", "format", "."])
    _run_checked([uv_exe, "run", "ruff", "check", "--fix", "."])


def _run_mypy() -> None:
    """Run mypy type checking."""
    uv_exe = _uv()
    _run_checked([uv_exe, "run", "mypy"])


def _run_hadolint() -> None:
    """Run hadolint on Dockerfiles."""
    hadolint_exe = _hadolint()
    config = _load_yaml_config(LINT_HADOLINT_CONFIG)
    exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}
    dockerfiles = [
        path
        for path in REPO_ROOT.rglob("Dockerfile")
        if path.is_file() and not any(excluded in path.parents for excluded in exclude_dirs)
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


def _run_pymarkdown() -> None:
    """Run pymarkdown on Markdown files."""
    uv_exe = _uv()
    config = _load_yaml_config(LINT_PYMARKDOWN_CONFIG)
    targets = config.get("targets", [])
    excludes = config.get("excludes", [])
    pymarkdown_cmd = [
        uv_exe,
        "run",
        "pymarkdown",
        "-c",
        str(REPO_ROOT / ".pymarkdown.json"),
        "scan",
        "-r",
        *targets,
    ]
    for pattern in excludes:
        pymarkdown_cmd.extend(["-e", pattern])
    _run_checked(pymarkdown_cmd)


def _run_yamllint() -> None:
    """Run yamllint on YAML files."""
    uv_exe = _uv()
    config = _load_yaml_config(LINT_YAMLLINT_CONFIG)
    exclude_dirs = set(config.get("exclude_dirs", []))
    yaml_files = [
        str(path)
        for path in REPO_ROOT.rglob("*.yml")
        if path.is_file() and not any(excl in path.parts for excl in exclude_dirs)
    ]
    yaml_files.extend(
        str(path)
        for path in REPO_ROOT.rglob("*.yaml")
        if path.is_file() and not any(excl in path.parts for excl in exclude_dirs)
    )
    if yaml_files:
        yamllint_config = str(REPO_ROOT / ".yamllint.yaml")
        _run_checked([uv_exe, "run", "yamllint", "-c", yamllint_config, *yaml_files])


def _run_checkov() -> int:
    """Run checkov on OpenAPI schema. Returns 1 if schema is missing, 0 otherwise."""
    if not OPENAPI_SCHEMA.exists():
        print(
            f"OpenAPI schema missing at {OPENAPI_SCHEMA}. Run `uv run gen_openapi` first.",
            file=sys.stderr,
        )
        return 1
    uv_exe = _uv()
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
    return 0


# Map linter names to their runner functions
LINTER_RUNNERS: dict[str, Callable[[], int | None]] = {
    "ruff": _run_ruff,
    "mypy": _run_mypy,
    "hadolint": _run_hadolint,
    "pymarkdown": _run_pymarkdown,
    "yamllint": _run_yamllint,
    "checkov": _run_checkov,
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run the project lint suite.",
        epilog=f"Available linters: {', '.join(LINTER_NAMES)}",
    )
    parser.add_argument(
        "linters",
        nargs="*",
        choices=LINTER_NAMES,
        metavar="LINTER",
        help=f"Linter(s) to run. Options: {', '.join(LINTER_NAMES)}. "
        "If omitted, all linters run in order.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute linting steps and return a process exit code."""
    args = _parse_args()

    # Determine which linters to run (preserve order from LINTER_NAMES)
    if args.linters:
        linters_to_run = [name for name in LINTER_NAMES if name in args.linters]
    else:
        linters_to_run = LINTER_NAMES

    try:
        for linter in linters_to_run:
            print(f"\n{'=' * 60}")
            print(f"Running: {linter}")
            print("=" * 60)
            runner = LINTER_RUNNERS[linter]
            result = runner()
            # checkov returns int for missing schema case
            if result == 1:
                return 1

    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
