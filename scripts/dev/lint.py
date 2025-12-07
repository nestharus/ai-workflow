"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Linter names in execution order
LINTER_NAMES = [
    "scripts",
    "markdown-restriction",
    "ruff",
    "mypy",
    "hadolint",
    "pymarkdown",
    "yamllint",
    "yamldocs",
    "checkov",
]
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
UV_CLI_REQUIRED = "uv CLI required to run lint"
HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"

# Lint script config file paths
LINT_SCRIPTS_CONFIG = REPO_ROOT / ".lint.scripts.yaml"
LINT_HADOLINT_CONFIG = REPO_ROOT / ".lint.hadolint.yaml"
LINT_PYMARKDOWN_CONFIG = REPO_ROOT / ".lint.pymarkdown.yaml"
LINT_YAMLLINT_CONFIG = REPO_ROOT / ".lint.yamllint.yaml"
LINT_YAMLDOCS_CONFIG = REPO_ROOT / ".lint.yamldocs.yaml"
LINT_MARKDOWN_RESTRICTION_CONFIG = REPO_ROOT / ".lint.markdown-restriction.yaml"


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
    subprocess.check_call(command)


def _run_scripts() -> int:
    """Validate pyproject.toml script entry point naming conventions.

    Reads rules from .lint.scripts.yaml configuration file. Each rule maps
    a module prefix to the required script name prefix.

    Returns:
        0 if all scripts follow conventions, 1 otherwise.
    """
    # Load configuration
    config = _load_yaml_config(LINT_SCRIPTS_CONFIG)
    if not isinstance(config, dict):
        config = {}
    prefix_rules: dict[str, str] = config.get("prefix_rules", {})

    if not prefix_rules:
        print("No prefix_rules defined in .lint.scripts.yaml", file=sys.stderr)
        return 1

    pyproject_path = REPO_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        print("pyproject.toml not found", file=sys.stderr)
        return 1

    # Parse pyproject.toml - use simple parsing for [project.scripts]
    content = pyproject_path.read_text(encoding="utf-8")
    violations: list[str] = []

    # Find [project.scripts] section
    in_scripts_section = False
    for line in content.splitlines():
        line = line.strip()

        # Track section transitions
        if line.startswith("["):
            in_scripts_section = line == "[project.scripts]"
            continue

        if not in_scripts_section:
            continue

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Parse script entry: "name" = "module:func" or name = "module:func"
        if "=" not in line:
            continue

        parts = line.split("=", 1)
        if len(parts) != 2:
            continue

        script_name = parts[0].strip().strip('"').strip("'")
        module_path = parts[1].strip().strip('"').strip("'")

        # Extract module path (before the colon)
        if ":" in module_path:
            module_path = module_path.split(":")[0]

        # Check naming conventions against configured rules
        for module_prefix, required_name_prefix in prefix_rules.items():
            if module_path.startswith(module_prefix):
                if not script_name.startswith(required_name_prefix):
                    violations.append(
                        f"  '{script_name}' -> {module_path} "
                        f"(should be prefixed with '{required_name_prefix}')"
                    )
                break

    if violations:
        print("Script naming convention violations:", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        return 1

    print("All script entry points follow naming conventions.")
    return 0


def _run_ruff(files: list[str] | None = None) -> None:
    """Run ruff format and check.

    Args:
        files: Optional list of files to lint. If None, lints entire repo.
    """
    uv_exe = _uv()
    targets = files if files else ["."]
    # Filter to only Python files if files are specified
    if files:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            print("No Python files to lint with ruff")
            return
        targets = py_files
    _run_checked([uv_exe, "run", "ruff", "format", *targets])
    _run_checked([uv_exe, "run", "ruff", "check", "--fix", *targets])


def _run_mypy(files: list[str] | None = None) -> None:
    """Run mypy type checking.

    Args:
        files: Optional list of files to check. If None, checks entire repo.
    """
    uv_exe = _uv()
    if files:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            print("No Python files to check with mypy")
            return
        _run_checked([uv_exe, "run", "mypy", *py_files])
    else:
        _run_checked([uv_exe, "run", "mypy"])


def _run_hadolint(files: list[str] | None = None) -> None:
    """Run hadolint on Dockerfiles.

    Args:
        files: Optional list of files to check. If None, checks all Dockerfiles.
    """
    hadolint_exe = _hadolint()
    config = _load_yaml_config(LINT_HADOLINT_CONFIG)
    exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

    if files:
        # Filter to only Dockerfile files
        dockerfiles = [Path(f) for f in files if Path(f).name == "Dockerfile"]
    else:
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


def _run_pymarkdown(files: list[str] | None = None) -> None:
    """Run pymarkdown on Markdown files.

    Args:
        files: Optional list of files to check. If None, checks configured targets.
    """
    uv_exe = _uv()
    config = _load_yaml_config(LINT_PYMARKDOWN_CONFIG)
    excludes = config.get("excludes", [])

    if files:
        md_files = [f for f in files if f.endswith(".md")]
        if not md_files:
            print("No Markdown files to check with pymarkdown")
            return
        targets = md_files
        pymarkdown_cmd = [
            uv_exe,
            "run",
            "pymarkdown",
            "-c",
            str(REPO_ROOT / ".pymarkdown.json"),
            "scan",
            *targets,
        ]
    else:
        targets = config.get("targets", [])
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


def _is_path_excluded(path: Path, exclude_paths: set[Path]) -> bool:
    """Check if a path is under any excluded directory.

    Args:
        path: The file path to check.
        exclude_paths: Set of excluded directory paths (relative to REPO_ROOT).

    Returns:
        True if the path is under an excluded directory.
    """
    return any(excluded in path.parents for excluded in exclude_paths)


def _run_yamllint(files: list[str] | None = None) -> None:
    """Run yamllint on YAML files.

    Args:
        files: Optional list of files to check. If None, checks all YAML files.
    """
    uv_exe = _uv()
    config = _load_yaml_config(LINT_YAMLLINT_CONFIG)
    exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

    if files:
        yaml_files = [f for f in files if f.endswith(".yml") or f.endswith(".yaml")]
        if not yaml_files:
            print("No YAML files to check with yamllint")
            return
    else:
        yaml_files = [
            str(path)
            for path in REPO_ROOT.rglob("*.yml")
            if path.is_file() and not _is_path_excluded(path, exclude_dirs)
        ]
        yaml_files.extend(
            str(path)
            for path in REPO_ROOT.rglob("*.yaml")
            if path.is_file() and not _is_path_excluded(path, exclude_dirs)
        )
    if yaml_files:
        yamllint_config = str(REPO_ROOT / ".yamllint.yaml")
        _run_checked([uv_exe, "run", "yamllint", "-c", yamllint_config, *yaml_files])


def _run_yamldocs() -> int:
    """Run YAML documentation schema linter.

    Validates that YAML documentation files (identified by doc_id at root)
    follow the schema defined in general.yaml.schema-guidelines.yml.

    Returns:
        0 if all files pass, 1 if errors found.
    """
    from scripts.dev.lint_yaml_docs import lint_directory

    config = _load_yaml_config(LINT_YAMLDOCS_CONFIG)
    targets = config.get("targets", ["docs/"])
    exclude_dirs = set(config.get("exclude_dirs", []))

    total_errors = 0
    total_docs = 0

    for target in targets:
        target_path = REPO_ROOT / target
        if not target_path.exists():
            continue

        # Filter out excluded directories
        results, _, _ = lint_directory(target_path)

        # Filter results to exclude configured directories
        filtered_results = [
            r for r in results if not any(excl in r["file_path"] for excl in exclude_dirs)
        ]
        filtered_errors = sum(len(r["errors"]) for r in filtered_results)
        filtered_docs = sum(1 for r in filtered_results if r["is_doc_file"])

        total_errors += filtered_errors
        total_docs += filtered_docs

        # Print errors
        for result in filtered_results:
            if result["errors"]:
                print(f"\n{result['file_path']}:")
                for error in result["errors"]:
                    print(f"  {error['error_type']}: {error['message']}")

    if total_errors > 0:
        print(f"\nFound {total_errors} error(s) in {total_docs} documentation file(s)")
        return 1

    print(f"Checked {total_docs} documentation file(s). No errors found.")
    return 0


def _run_markdown_restriction() -> int:
    """Run markdown restriction linter.

    Validates that only README.md and AGENTS.md are allowed as markdown files
    in root, app/**, docs/**, scripts/**, and tests/** directories.

    Returns:
        0 if all files pass, 1 if violations found.
    """
    from scripts.dev.lint_markdown_restriction import (
        format_violations,
        lint_markdown_restriction,
    )

    violations, exit_code = lint_markdown_restriction(LINT_MARKDOWN_RESTRICTION_CONFIG)

    if violations:
        print(format_violations(violations), file=sys.stderr)
        print(
            f"\nFound {len(violations)} forbidden markdown file(s).",
            file=sys.stderr,
        )
    else:
        print("No forbidden markdown files found.")

    return exit_code


def _run_checkov() -> int:
    """Run checkov on OpenAPI schema. Returns 1 if schema is missing, 0 otherwise."""
    if not OPENAPI_SCHEMA.exists():
        print(
            f"OpenAPI schema missing at {OPENAPI_SCHEMA}. Run `uv run app.api.generate` first.",
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


# Map linter names to their runner functions (no file filtering support)
LINTER_RUNNERS_NO_FILES: dict[str, Callable[[], int | None]] = {
    "scripts": _run_scripts,
    "markdown-restriction": _run_markdown_restriction,
    "yamldocs": _run_yamldocs,
    "checkov": _run_checkov,
}

# Map linter names to their runner functions (with file filtering support)
LINTER_RUNNERS_WITH_FILES: dict[str, Callable[[list[str] | None], int | None]] = {
    "ruff": _run_ruff,
    "mypy": _run_mypy,
    "hadolint": _run_hadolint,
    "pymarkdown": _run_pymarkdown,
    "yamllint": _run_yamllint,
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
    parser.add_argument(
        "--files",
        nargs="+",
        metavar="FILE",
        help="Only lint the specified files. Paths should be relative to repo root.",
    )
    return parser.parse_args()


def main() -> int:
    """Execute linting steps and return a process exit code."""
    args = _parse_args()
    files: list[str] | None = args.files

    # Determine which linters to run (preserve order from LINTER_NAMES)
    if args.linters:
        linters_to_run = [name for name in LINTER_NAMES if name in args.linters]
    else:
        linters_to_run = LINTER_NAMES

    # If files are specified but only non-file-filtering linters are requested,
    # warn the user
    if files:
        file_filtering_linters = set(LINTER_RUNNERS_WITH_FILES.keys())
        requested_filterable = [l for l in linters_to_run if l in file_filtering_linters]
        if not requested_filterable:
            print(
                "Warning: --files specified but no file-filtering linters requested. "
                f"File filtering is supported by: {', '.join(file_filtering_linters)}",
                file=sys.stderr,
            )

    try:
        for linter in linters_to_run:
            print(f"\n{'=' * 60}")
            print(f"Running: {linter}")
            print("=" * 60)

            # Check if linter supports file filtering
            if linter in LINTER_RUNNERS_WITH_FILES:
                runner = LINTER_RUNNERS_WITH_FILES[linter]
                result = runner(files)
            elif linter in LINTER_RUNNERS_NO_FILES:
                runner_no_files = LINTER_RUNNERS_NO_FILES[linter]
                result = runner_no_files()
            else:
                print(f"Unknown linter: {linter}", file=sys.stderr)
                return 1

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
