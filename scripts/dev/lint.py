"""Run the project lint suite including formatting, type checks, and security scans."""

import argparse
import contextlib
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Linter names in execution order
LINTER_NAMES = [
    "scripts",
    "ruff",
    "mypy",
    "hadolint",
    "pymarkdown",
    "yamllint",
    "actionlint",
    "dotenvlint",
    "checkov",
    "detect-secrets",
    "trivy",
]
OPENAPI_SCHEMA = REPO_ROOT / "openapi" / "openapi.json"
CHECKOV_CONFIG = REPO_ROOT / ".checkov.yaml"
HADOLINT_CONFIG = REPO_ROOT / ".hadolint.yaml"
SECRETS_BASELINE = REPO_ROOT / ".secrets.baseline"
UV_CLI_REQUIRED = "uv CLI required to run lint"
HADOLINT_CLI_REQUIRED = "hadolint CLI required to run lint"
DOTENV_LINTER_CLI_REQUIRED = "dotenv-linter CLI required to run lint"
TRIVY_CLI_REQUIRED = "trivy CLI required to run lint"
DOCKER_CLI_REQUIRED = "docker CLI required for trivy image scanning"

# Lint script config file paths
LINT_SCRIPTS_CONFIG = REPO_ROOT / ".lint.scripts.yaml"
LINT_HADOLINT_CONFIG = REPO_ROOT / ".lint.hadolint.yaml"
LINT_PYMARKDOWN_CONFIG = REPO_ROOT / ".lint.pymarkdown.yaml"
LINT_YAMLLINT_CONFIG = REPO_ROOT / ".lint.yamllint.yaml"
LINT_DOTENVLINT_CONFIG = REPO_ROOT / ".lint.dotenvlint.yaml"
LINT_DETECT_SECRETS_CONFIG = REPO_ROOT / ".lint.detect-secrets.yaml"
LINT_ACTIONLINT_CONFIG = REPO_ROOT / ".lint.actionlint.yaml"
ACTIONLINT_CLI_REQUIRED = "actionlint CLI required to run lint"
LINT_TRIVY_CONFIG = REPO_ROOT / ".lint.trivy.yaml"


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


def _dotenv_linter() -> str:
    """Locate the dotenv-linter executable on PATH."""
    dotenv_linter_exe = shutil.which("dotenv-linter")
    if dotenv_linter_exe is None:
        raise RuntimeError(DOTENV_LINTER_CLI_REQUIRED)
    return dotenv_linter_exe


def _actionlint() -> str:
    actionlint_exe = shutil.which("actionlint")
    if actionlint_exe is None:
        raise RuntimeError(ACTIONLINT_CLI_REQUIRED)
    return actionlint_exe


def _trivy() -> str:
    trivy_exe = shutil.which("trivy")
    if trivy_exe is None:
        raise RuntimeError(TRIVY_CLI_REQUIRED)
    return trivy_exe


def _docker() -> str:
    docker_exe = shutil.which("docker")
    if docker_exe is None:
        raise RuntimeError(DOCKER_CLI_REQUIRED)
    return docker_exe


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
    targets = files if files is not None else ["."]
    # Filter to only Python files if files are specified
    if files is not None:
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
    if files is not None:
        py_files = [f for f in files if f.endswith(".py")]
        if not py_files:
            print("No Python files to check with mypy")
            return
        # Filter out common test directories to avoid unnecessary mypy runs.
        # This is a performance optimization; mypy applies its full exclude rules regardless.
        filtered_files = [
            f for f in py_files if not (f.startswith("tests/") or f.startswith("scripts/tests/"))
        ]
        if not filtered_files:
            print("All Python files are excluded from mypy checking")
            return
        _run_checked([uv_exe, "run", "mypy", *filtered_files])
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

    if files is not None:
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

    if files is not None:
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

    if files is not None:
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


def _run_actionlint(files: list[str] | None = None) -> None:
    """Run actionlint on GitHub Actions workflow files.

    Args:
        files: Optional list of files to check. If None, checks all workflow files.
    """
    actionlint_exe = _actionlint()
    config = _load_yaml_config(LINT_ACTIONLINT_CONFIG)
    ignore_patterns: list[str] = config.get("ignore", [])
    exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

    workflows_dir = REPO_ROOT / ".github" / "workflows"

    if files is not None:
        # Filter to only workflow YAML files in .github/workflows/
        workflow_files = [
            f
            for f in files
            if (f.endswith(".yml") or f.endswith(".yaml"))
            and (REPO_ROOT / f).resolve().is_relative_to(workflows_dir.resolve())
            and not _is_path_excluded((REPO_ROOT / f).resolve(), exclude_dirs)
        ]
        if not workflow_files:
            print("No GitHub Actions workflow files to check with actionlint")
            return
        targets = workflow_files
    else:
        if not workflows_dir.exists():
            print("No .github/workflows/ directory found for actionlint scan")
            return
        # Enumerate workflow files, respecting exclude_dirs
        workflow_files = [
            str(path)
            for path in workflows_dir.rglob("*.yml")
            if path.is_file() and not _is_path_excluded(path, exclude_dirs)
        ]
        workflow_files.extend(
            str(path)
            for path in workflows_dir.rglob("*.yaml")
            if path.is_file() and not _is_path_excluded(path, exclude_dirs)
        )
        if not workflow_files:
            print("No workflow files found for actionlint scan")
            return
        targets = workflow_files

    cmd = [actionlint_exe]
    for pattern in ignore_patterns:
        cmd.extend(["-ignore", pattern])
    cmd.extend(targets)

    _run_checked(cmd)


def _run_dotenvlint(files: list[str] | None = None) -> None:
    """Run dotenv-linter on .env files.

    Args:
        files: Optional list of files to check. If None, checks configured targets.
    """
    dotenv_linter_exe = _dotenv_linter()
    config = _load_yaml_config(LINT_DOTENVLINT_CONFIG)
    exclude_dirs = {REPO_ROOT / d for d in config.get("exclude_dirs", [])}

    if files:
        # Filter to only .env files
        env_files = [f for f in files if Path(f).name.startswith(".env")]
        if not env_files:
            print("No .env files to check with dotenv-linter")
            return
        targets = env_files
    else:
        # Find all .env files based on configured targets
        targets_config = config.get("targets", [".env", ".env.*"])
        exclude_patterns = config.get("exclude_patterns", [])
        env_files = []
        for pattern in targets_config:
            for path in REPO_ROOT.glob(pattern):
                if path.is_file() and not _is_path_excluded(path, exclude_dirs):
                    # Check exclude patterns
                    excluded = any(path.match(ep) for ep in exclude_patterns)
                    if not excluded:
                        env_files.append(str(path))
        targets = env_files

    if not targets:
        print("No .env files found for dotenv-linter scan")
    else:
        _run_checked([dotenv_linter_exe, "check", *targets])


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


def _run_detect_secrets(files: list[str] | None = None) -> int:
    """Run detect-secrets to scan for secrets.

    Args:
        files: Optional list of files to scan. If None, scans all tracked files.

    Returns:
        0 if no new secrets found, 1 if baseline missing.
        Raises CalledProcessError if detect-secrets finds new secrets.
    """
    if not SECRETS_BASELINE.exists():
        print(
            f"Secrets baseline missing at {SECRETS_BASELINE}. "
            "Run `uv run detect-secrets scan > .secrets.baseline` first.",
            file=sys.stderr,
        )
        return 1

    uv_exe = _uv()
    if files is not None:
        # Load exclusion config from .lint.detect-secrets.yaml
        config = _load_yaml_config(LINT_DETECT_SECRETS_CONFIG)
        excluded_extensions = set(config.get("excluded_extensions", []))
        excluded_names = set(config.get("excluded_names", []))

        scannable_files = [
            f
            for f in files
            if not any(f.endswith(ext) for ext in excluded_extensions)
            and Path(f).name not in excluded_names
        ]

        if not scannable_files:
            print("No scannable files for detect-secrets")
            return 0

        # Use detect-secrets-hook for file-based scanning
        _run_checked(
            [
                uv_exe,
                "run",
                "detect-secrets-hook",
                "--baseline",
                str(SECRETS_BASELINE),
                *scannable_files,
            ]
        )
    else:
        # Scan all files and compare against baseline
        _run_checked(
            [
                uv_exe,
                "run",
                "detect-secrets",
                "scan",
                "--baseline",
                str(SECRETS_BASELINE),
            ]
        )
    return 0


def _run_trivy_fs(trivy_exe: str, config: dict[str, Any]) -> int:
    """Run Trivy filesystem scan on uv.lock.

    Args:
        trivy_exe: Path to trivy executable.
        config: Configuration dictionary from .lint.trivy.yaml.

    Returns:
        0 if scan passes, 1 if vulnerabilities found or errors occur.
    """
    fs_target = config.get("fs_target", "uv.lock")
    lockfile_path = REPO_ROOT / fs_target
    skip_if_missing = config.get("skip_fs_if_no_lockfile", False)

    if not lockfile_path.exists():
        if skip_if_missing:
            print(f"Warning: {fs_target} not found, skipping filesystem scan")
            return 0
        else:
            print(f"Error: {fs_target} not found", file=sys.stderr)
            return 1

    # Run trivy fs scan from REPO_ROOT
    result = subprocess.call(
        [trivy_exe, "fs", "--config", ".trivy.yaml", str(fs_target)],
        cwd=str(REPO_ROOT),
    )
    return 0 if result == 0 else 1


def _run_trivy_image(trivy_exe: str, config: dict[str, Any]) -> int:
    """Run Trivy image scan on temporary Docker image.

    Builds the Docker image without a tag, using --iidfile to capture the unique
    image ID. This avoids clobbering existing tags and ensures cleanup only
    removes the image we just built.

    Args:
        trivy_exe: Path to trivy executable.
        config: Configuration dictionary from .lint.trivy.yaml.

    Returns:
        0 if scan passes, 1 if vulnerabilities found or errors occur.
    """
    skip_if_no_dockerfile = config.get("skip_image_if_no_dockerfile", True)

    dockerfile_path = REPO_ROOT / "Dockerfile"
    if not dockerfile_path.exists():
        if skip_if_no_dockerfile:
            print("Warning: Dockerfile not found, skipping image scan")
            return 0
        else:
            print("Error: Dockerfile not found", file=sys.stderr)
            return 1

    # Only check for Docker after confirming we need to build
    docker_exe = _docker()  # Raises if docker not installed

    # Build image without tag, using --iidfile to capture the unique image ID.
    # This avoids clobbering existing tags and ensures we only remove our image.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".iid", delete=False) as iid_file:
        iid_file_path = iid_file.name

    print("Building temporary image...")
    build_result = subprocess.call(
        [docker_exe, "build", "--iidfile", iid_file_path, "."],
        cwd=str(REPO_ROOT),
    )

    if build_result != 0:
        print("Error: Docker build failed", file=sys.stderr)
        # Clean up iid file if build failed
        Path(iid_file_path).unlink(missing_ok=True)
        return 1

    # Read the image ID from the iidfile
    # Initialize image_id before try block so cleanup can attempt to read it if needed
    image_id: str | None = None
    try:
        image_id = Path(iid_file_path).read_text().strip()

        if not image_id:
            print("Error: Failed to get image ID from build", file=sys.stderr)
            return 1

        # Run trivy image scan
        print(f"Scanning image: {image_id[:12]}...")
        scan_result = subprocess.call(
            [trivy_exe, "image", "--config", ".trivy.yaml", image_id],
            cwd=str(REPO_ROOT),
        )
        return 0 if scan_result == 0 else 1
    finally:
        # If image_id is not set (read failed), try to read it again for cleanup.
        # We read into a local and reassign to avoid issues with contextlib.suppress
        # not allowing assignment expressions within the with block.
        if not image_id:
            recovered_id: str | None = None
            with contextlib.suppress(OSError):
                recovered_id = Path(iid_file_path).read_text().strip()
            image_id = recovered_id

        # Clean up temp image if we have an ID
        if image_id:
            print(f"Removing temporary image: {image_id[:12]}...")
            cleanup_result = subprocess.call(
                [docker_exe, "rmi", image_id],
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if cleanup_result != 0:
                print(
                    f"Warning: Failed to remove temporary image {image_id[:12]}",
                    file=sys.stderr,
                )

        # Clean up IID file after image cleanup is complete
        Path(iid_file_path).unlink(missing_ok=True)


def _run_trivy() -> int:
    """Run Trivy security scans for filesystem and Docker image.

    Runs two scan modes (controlled by enable_fs_scan and enable_image_scan):
    1. Filesystem scan: Scans uv.lock for Python dependency vulnerabilities
    2. Image scan: Builds temporary Docker image and scans for vulnerabilities

    Note: The filesystem scan runs first. If it fails (vulnerabilities found
    or errors), the function returns immediately and the image scan is skipped.
    This short-circuit behavior avoids running Docker operations when dependency
    vulnerabilities already need attention.

    Returns:
        0 if all scans pass, 1 if vulnerabilities found or errors occur.
    """
    trivy_exe = _trivy()  # Raises if trivy not installed
    config = _load_yaml_config(LINT_TRIVY_CONFIG)

    # Check which scans are enabled (both default to True for backward compatibility)
    enable_fs_scan = config.get("enable_fs_scan", True)
    enable_image_scan = config.get("enable_image_scan", True)

    # Filesystem scan (runs first, short-circuits on failure)
    if enable_fs_scan:
        fs_result = _run_trivy_fs(trivy_exe, config)
        if fs_result != 0:
            return fs_result
    else:
        print("Filesystem scan disabled via enable_fs_scan: false")

    # Image scan (only runs if filesystem scan passes or is disabled)
    if enable_image_scan:
        image_result = _run_trivy_image(trivy_exe, config)
        return image_result
    else:
        print("Image scan disabled via enable_image_scan: false")

    return 0


# Map linter names to their runner functions (no file filtering support)
LINTER_RUNNERS_NO_FILES: dict[str, Callable[[], int | None]] = {
    "scripts": _run_scripts,
    "checkov": _run_checkov,
    "trivy": _run_trivy,
}

# Map linter names to their runner functions (with file filtering support)
LINTER_RUNNERS_WITH_FILES: dict[str, Callable[[list[str] | None], int | None]] = {
    "ruff": _run_ruff,
    "mypy": _run_mypy,
    "hadolint": _run_hadolint,
    "pymarkdown": _run_pymarkdown,
    "yamllint": _run_yamllint,
    "actionlint": _run_actionlint,
    "dotenvlint": _run_dotenvlint,
    "detect-secrets": _run_detect_secrets,
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
    if files is not None:
        file_filtering_linters = set(LINTER_RUNNERS_WITH_FILES.keys())
        requested_filterable = [
            linter for linter in linters_to_run if linter in file_filtering_linters
        ]
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
    except OSError as exc:
        print(f"OS error: {exc}", file=sys.stderr)
        return 1
    except yaml.YAMLError as exc:
        print(f"YAML configuration error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
