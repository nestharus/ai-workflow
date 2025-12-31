"""Base linter interface and shared utilities."""

import concurrent.futures
import fnmatch
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class LintError:
    """A single lint error with structured information."""

    file: str
    line: int
    column: int
    code: str
    message: str
    context: str | None = None
    fix_available: bool = False
    fix_message: str | None = None


@dataclass
class LinterResult:
    """Result of running a linter."""

    success: bool
    message: str | None = None
    errors: list[LintError] = field(default_factory=list)

    def format_errors_yaml(self, linter_name: str) -> str:
        """Format errors as YAML for agent consumption.

        Args:
            linter_name: Name of the linter that produced these errors.

        Returns:
            YAML-formatted string with structured error information.
        """
        if not self.errors:
            return ""

        lines = [f"linter: {linter_name}", f"success: {self.success}", "errors:"]

        for error in self.errors:
            lines.append(f"  - file: {error.file}")
            lines.append(f"    line: {error.line}")
            lines.append(f"    column: {error.column}")
            lines.append(f"    code: {error.code}")
            lines.append(f"    message: {error.message}")

            if error.context:
                # Use YAML literal block for multiline context
                lines.append("    context: |")
                for ctx_line in error.context.splitlines():
                    lines.append(f"      {ctx_line}")

            lines.append(f"    fix_available: {error.fix_available}")
            if error.fix_message:
                lines.append(f"    fix_message: {error.fix_message}")

        return "\n".join(lines)


class InvalidCommandError(TypeError):
    """Raised when a command argument is malformed."""

    def __init__(self) -> None:
        """Initialize with a standard validation message."""
        super().__init__("command must be a non-empty list of strings")


def load_yaml_config(config_path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def run_checked(command: list[str], *, cwd: Path | None = None) -> None:
    """Invoke a subprocess command with error propagation.

    Args:
        command: Command and arguments to run.
        cwd: Optional working directory for the command.
    """
    if not (
        isinstance(command, list) and command and all(isinstance(part, str) for part in command)
    ):
        raise InvalidCommandError()
    subprocess.check_call(command, cwd=cwd)


def is_path_excluded(path: Path, exclude_paths: set[Path]) -> bool:
    """Check if a path is under any excluded directory or equals one.

    Args:
        path: The file path to check.
        exclude_paths: Set of excluded directory paths (relative to REPO_ROOT).

    Returns:
        True if the path is under an excluded directory or equals one.
    """
    return path in exclude_paths or any(excluded in path.parents for excluded in exclude_paths)


def get_executable(name: str, error_message: str) -> str:
    """Locate an executable on PATH.

    Args:
        name: Name of the executable to find.
        error_message: Error message if executable not found.

    Returns:
        Path to the executable.

    Raises:
        RuntimeError: If executable is not found.
    """
    exe = shutil.which(name)
    if exe is None:
        raise RuntimeError(error_message)
    return exe


class BaseLinter(ABC):
    """Base class for all linters.

    Attributes:
        name: Unique identifier for the linter.
        supports_file_filtering: Whether the linter can filter specific files.
        mutates_files: Whether the linter modifies source files in-place.
            Defaults to False (read-only). Set to True for linters that format,
            auto-fix, or otherwise modify files. Used by the parallel execution
            scheduler to sequence mutating linters before read-only linters.
    """

    name: str
    supports_file_filtering: bool = True
    mutates_files: bool = False

    @abstractmethod
    def run(self, files: list[str] | None = None) -> LinterResult:
        """Run the linter.

        Args:
            files: Optional list of files to lint. If None, lints entire repo.
                   Only used if supports_file_filtering is True.

        Returns:
            LinterResult indicating success/failure.
        """
        pass

    def test(self) -> LinterResult:
        """Run the linter's test suite (e.g., rule tests).

        This is optional - linters that have self-tests (like ast-grep rule tests)
        can override this method. By default, returns success with no-op.

        Returns:
            LinterResult indicating success/failure.
        """
        return LinterResult(success=True, message="No tests defined")


def match_glob_pattern(path: str, pattern: str) -> bool:
    """Match a path against a glob pattern.

    Supports:
    - * matches any characters except /
    - ** matches any characters including / (recursive)
    - !prefix negates the pattern

    Args:
        path: The file path to check (relative to repo root).
        pattern: The glob pattern to match against.

    Returns:
        True if the path matches the pattern.
    """
    # Handle negation patterns
    if pattern.startswith("!"):
        return not match_glob_pattern(path, pattern[1:])

    path_parts = path.split("/")
    pattern_parts = pattern.split("/")

    i = 0  # Index in path_parts
    j = 0  # Index in pattern_parts

    while j < len(pattern_parts):
        pattern_part = pattern_parts[j]

        if pattern_part == "**":
            # ** matches zero or more directories
            j += 1
            if j >= len(pattern_parts):
                # ** at end matches rest of path
                return True
            # Try to match remaining pattern at current or subsequent positions
            next_pattern = pattern_parts[j]
            while i < len(path_parts):
                if fnmatch.fnmatch(path_parts[i], next_pattern) and match_glob_pattern(
                    "/".join(path_parts[i:]), "/".join(pattern_parts[j:])
                ):
                    return True
                i += 1
            return False

        if i >= len(path_parts):
            return False

        if not fnmatch.fnmatch(path_parts[i], pattern_part):
            return False

        i += 1
        j += 1

    # All pattern parts consumed - path matches if we also consumed all parts
    return i == len(path_parts)


def filter_paths_by_glob(
    paths: list[str], glob_patterns: list[str], repo_root: Path | None = None
) -> list[str]:
    """Filter paths based on glob patterns following coderabbit path_filters semantics.

    Patterns are processed in order:
    - Patterns without ! prefix are inclusions
    - Patterns with ! prefix are exclusions (processed after inclusions)
    - A path is included if it matches any inclusion pattern AND no exclusion pattern

    Args:
        paths: List of file paths to filter (relative to repo root).
        glob_patterns: List of glob patterns (following coderabbit path_filters format).
        repo_root: Optional repo root for path normalization (unused, kept for API compat).

    Returns:
        Filtered list of paths matching the inclusion/exclusion rules.
    """
    included = []
    excluded_patterns = []

    for pattern in glob_patterns:
        if pattern.startswith("!"):
            excluded_patterns.append(pattern)
        else:
            # Check each path against this inclusion pattern
            for path in paths:
                if match_glob_pattern(path, pattern):
                    # Check if this path is excluded by any exclusion pattern
                    is_excluded = any(match_glob_pattern(path, excl) for excl in excluded_patterns)
                    if not is_excluded and path not in included:
                        included.append(path)

    return included


def is_path_included(path: str, glob_patterns: list[str]) -> bool:
    """Check if a path is included by glob patterns.

    Args:
        path: The file path to check (relative to repo root).
        glob_patterns: List of glob patterns (following coderabbit path_filters format).

    Returns:
        True if the path is included by the patterns.
    """
    excluded = False
    included = False

    for pattern in glob_patterns:
        if pattern.startswith("!"):
            if match_glob_pattern(path, pattern[1:]):
                excluded = True
        else:
            if match_glob_pattern(path, pattern):
                included = True

    # Path is included only if it matches at least one inclusion pattern
    # and is not excluded by any exclusion pattern
    return included and not excluded


def _validate_list_config(
    config: dict[str, Any], key: str, linter_name: str
) -> tuple[list[str], LinterResult | None]:
    """Validate a list config value from the config dict.

    Args:
        config: The parsed config dictionary.
        key: The config key to validate (e.g., "included_paths", "excluded_paths").
        linter_name: Name of the linter (for error messages).

    Returns:
        A tuple of (value_or_empty_list, error_result). If error_result is not None,
        the caller should return it immediately. Otherwise, use the returned list.
    """
    value = config.get(key, [])
    if value is not None and not isinstance(value, list):
        type_name = type(value).__name__
        print(f"Invalid {key} in {linter_name} config: expected list, got {type_name}")
        return [], LinterResult(success=False, message=f"Invalid {key} config")
    return value if value is not None else [], None


def filter_files_with_config(
    py_files: list[str],
    config_path: Path,
    linter_name: str,
) -> tuple[list[str], LinterResult | None]:
    """Load config and filter Python files by included_paths.

    This is a shared helper for linters that need to filter files based on
    included_paths from their config YAML. Files must match at least one
    inclusion pattern to pass the filter.

    Empty-match behavior: When no files match the included_paths patterns,
    the function prints a diagnostic message and returns ([], None). This is treated
    as a valid empty result (not a failure), and callers should proceed accordingly
    rather than treating it as an exception. An empty list with None error_result
    indicates "no files matched the filter" and the caller may skip linting.

    Args:
        py_files: List of Python files to filter.
        config_path: Path to the linter's YAML config file.
        linter_name: Name of the linter (for error messages).

    Returns:
        A tuple of (filtered_files, error_result). If error_result is not None,
        the caller should return it immediately (indicates a real error like
        missing config or parse failure). If error_result is None, use filtered_files
        (which may be empty if no files matched the patterns - this is valid).
    """
    try:
        config = load_yaml_config(config_path)
    except FileNotFoundError:
        print(f"{linter_name.capitalize()} config file not found: {config_path}")
        return [], LinterResult(success=False, message="Config file not found")
    except PermissionError as e:
        print(f"Permission denied reading {linter_name} config {config_path}: {e}")
        return [], LinterResult(success=False, message=f"Config permission error: {e}")
    except yaml.YAMLError as e:
        print(f"Failed to parse {linter_name} config {config_path}: {e}")
        return [], LinterResult(success=False, message=f"Config parse error: {e}")

    included_paths, error = _validate_list_config(config, "included_paths", linter_name)
    if error is not None:
        return [], error

    if included_paths:
        filtered = [f for f in py_files if is_path_included(f, included_paths)]
        if not filtered:
            print(f"No Python files match {linter_name} included_paths filter")
            return [], None
        return filtered, None

    return py_files, None


def calculate_fileset(linter: BaseLinter, files: list[str] | None) -> set[str] | None:
    """Calculate the set of files a linter will process.

    This function extracts and centralizes the file filtering logic from all linters,
    enabling the parallel scheduler to skip linters with empty filesets and determine
    file conflicts for optimization.

    Examples:
        >>> from scripts.dev.linter.linters.ruff import RuffLinter
        >>> linter = RuffLinter()
        >>>
        >>> # Whole-repo scan
        >>> calculate_fileset(linter, None)
        None
        >>>
        >>> # Filtered scan with matching files
        >>> calculate_fileset(linter, ["app/main.py", "README.md"])
        {"app/main.py"}
        >>>
        >>> # Filtered scan with no matching files
        >>> calculate_fileset(linter, ["README.md", "Dockerfile"])
        set()

    Args:
        linter: The linter instance to calculate fileset for.
        files: Optional list of files to filter. If None, indicates whole-repo scan.

    Returns:
        - None: Indicates whole-repo scan (when files=None input)
        - Empty set: No files match the linter's criteria
        - Populated set: The actual files the linter will process
    """
    if files is None:
        return None

    # Dispatch to linter-specific filtering based on linter name
    dispatch: dict[str, Callable[[list[str]], set[str]]] = {
        "ruff": _calculate_fileset_ruff,
        "mypy": _calculate_fileset_mypy,
        "astgrep": _calculate_fileset_astgrep,
        "shellcheck": _calculate_fileset_shellcheck,
        "yamllint": _calculate_fileset_yamllint,
        "hadolint": _calculate_fileset_hadolint,
        "pymarkdown": _calculate_fileset_pymarkdown,
        "actionlint": _calculate_fileset_actionlint,
        "dotenvlint": _calculate_fileset_dotenvlint,
        "detect-secrets": _calculate_fileset_detect_secrets,
        "gitleaks": _calculate_fileset_gitleaks,
        "scripts": _calculate_fileset_scripts,
        "trivy": _calculate_fileset_trivy,
        "checkov": _calculate_fileset_checkov,
    }

    handler = dispatch.get(linter.name)
    if handler is not None:
        return handler(files)

    # Unknown linter - return all files as fallback
    return set(files)


def _calculate_fileset_ruff(files: list[str]) -> set[str]:
    """Calculate fileset for ruff linter.

    Filters for .py files and applies included_paths from .lint.ruff.yaml config.
    On config error, returns all .py files so the linter runs and surfaces the error.
    """
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return set()

    config_path = REPO_ROOT / ".lint.ruff.yaml"
    filtered, error = filter_files_with_config(py_files, config_path, "ruff")
    if error is not None:
        return set(py_files)
    return set(filtered)


def _calculate_fileset_mypy(files: list[str]) -> set[str]:
    """Calculate fileset for mypy linter.

    Filters for .py files and applies included_paths from .lint.mypy.yaml config.
    On config error, returns all .py files so the linter runs and surfaces the error.
    """
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return set()

    config_path = REPO_ROOT / ".lint.mypy.yaml"
    filtered, error = filter_files_with_config(py_files, config_path, "mypy")
    if error is not None:
        return set(py_files)
    return set(filtered)


def _calculate_fileset_astgrep(files: list[str]) -> set[str]:
    """Calculate fileset for astgrep linter.

    Filters for .py/.pyi files and applies included_paths from .lint.astgrep.yaml config.
    Uses custom glob matching logic.
    """
    config_path = REPO_ROOT / ".lint.astgrep.yaml"
    included_paths: list[str] = []

    if config_path.exists():
        try:
            config = load_yaml_config(config_path)
            raw_paths = config.get("included_paths", [])
            if isinstance(raw_paths, str):
                included_paths = [raw_paths]
            elif isinstance(raw_paths, list):
                included_paths = [p for p in raw_paths if isinstance(p, str)]
        except (OSError, yaml.YAMLError):
            return set()

    result = set()
    for f in files:
        if not f.endswith((".py", ".pyi")):
            continue
        # Check inclusion patterns
        if included_paths and not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_shellcheck(files: list[str]) -> set[str]:
    """Calculate fileset for shellcheck linter.

    Filters for .sh files and applies included_paths from .lint.shellcheck.yaml config.
    """
    config_path = REPO_ROOT / ".lint.shellcheck.yaml"
    included_paths: list[str] = []

    if config_path.exists():
        try:
            config = load_yaml_config(config_path)
            if isinstance(config, dict):
                included_paths = config.get("included_paths", [])
        except (OSError, yaml.YAMLError):
            return set()

    result = set()
    for f in files:
        if not f.endswith(".sh"):
            continue
        if included_paths and not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_yamllint(files: list[str]) -> set[str]:
    """Calculate fileset for yamllint linter.

    Filters for .yaml/.yml files and applies included_paths from .lint.yamllint.yaml config.
    On config error, returns all .yaml/.yml files so the linter runs and surfaces the error.
    """
    yaml_files = {f for f in files if f.endswith(".yaml") or f.endswith(".yml")}
    if not yaml_files:
        return set()

    config_path = REPO_ROOT / ".lint.yamllint.yaml"
    try:
        config = load_yaml_config(config_path)
        included_paths = config.get("included_paths", [])
    except (OSError, yaml.YAMLError):
        return yaml_files

    result = set()
    for f in yaml_files:
        if not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_hadolint(files: list[str]) -> set[str]:
    """Calculate fileset for hadolint linter.

    Filters for Dockerfile files and applies included_paths from .lint.hadolint.yaml config.
    On config error, returns all Dockerfile files so the linter runs and surfaces the error.
    """
    dockerfile_files = {f for f in files if Path(f).name == "Dockerfile"}
    if not dockerfile_files:
        return set()

    config_path = REPO_ROOT / ".lint.hadolint.yaml"
    try:
        config = load_yaml_config(config_path)
        included_paths = config.get("included_paths", [])
    except (OSError, yaml.YAMLError):
        return dockerfile_files

    result = set()
    for f in dockerfile_files:
        if not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_pymarkdown(files: list[str]) -> set[str]:
    """Calculate fileset for pymarkdown linter.

    Filters for .md files and applies included_paths from .lint.pymarkdown.yaml config.
    On config error, returns all .md files so the linter runs and surfaces the error.
    """
    md_files = {f for f in files if f.endswith(".md")}
    if not md_files:
        return set()

    config_path = REPO_ROOT / ".lint.pymarkdown.yaml"
    try:
        config = load_yaml_config(config_path)
        included_paths = config.get("included_paths", [])
    except (OSError, yaml.YAMLError):
        return md_files

    result = set()
    for f in md_files:
        if not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_actionlint(files: list[str]) -> set[str]:
    """Calculate fileset for actionlint linter.

    Filters for .yml/.yaml files and applies included_paths from .lint.actionlint.yaml config.
    On config error, returns all .yml/.yaml files so the linter runs and surfaces the error.
    """
    yaml_files = {f for f in files if f.endswith(".yml") or f.endswith(".yaml")}
    if not yaml_files:
        return set()

    config_path = REPO_ROOT / ".lint.actionlint.yaml"
    try:
        config = load_yaml_config(config_path)
        included_paths = config.get("included_paths", [])
    except (OSError, yaml.YAMLError):
        return yaml_files

    result = set()
    for f in yaml_files:
        if not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_dotenvlint(files: list[str]) -> set[str]:
    """Calculate fileset for dotenvlint linter.

    Filters for .env* files and applies included_paths from .lint.dotenvlint.yaml config.
    On config error, returns all .env* files so the linter runs and surfaces the error.
    """
    env_files = {f for f in files if Path(f).name.startswith(".env")}
    if not env_files:
        return set()

    config_path = REPO_ROOT / ".lint.dotenvlint.yaml"
    try:
        config = load_yaml_config(config_path)
        included_paths = config.get("included_paths", [])
    except (OSError, yaml.YAMLError):
        return env_files

    result = set()
    for f in env_files:
        if not is_path_included(f, included_paths):
            continue
        result.add(f)
    return result


def _calculate_fileset_detect_secrets(files: list[str]) -> set[str]:
    """Calculate fileset for detect-secrets linter.

    Applies included_paths, excluded_extensions, and excluded_names from
    .lint.detect-secrets.yaml config.
    On config error, returns all files so the linter runs and surfaces the error.
    """
    config_path = REPO_ROOT / ".lint.detect-secrets.yaml"
    try:
        config = load_yaml_config(config_path)
    except (OSError, yaml.YAMLError):
        return set(files)

    excluded_extensions = set(config.get("excluded_extensions", []))
    excluded_names = set(config.get("excluded_names", []))
    included_paths = config.get("included_paths", [])

    result = set()
    for f in files:
        # Check inclusion via glob patterns
        if included_paths and not is_path_included(f, included_paths):
            continue
        # Check extension exclusion
        if any(f.endswith(ext) for ext in excluded_extensions):
            continue
        # Check name exclusion
        if Path(f).name in excluded_names:
            continue
        result.add(f)
    return result


def _calculate_fileset_gitleaks(files: list[str]) -> set[str]:
    """Calculate fileset for gitleaks linter.

    Applies included_paths, excluded_extensions, and excluded_names from
    .lint.gitleaks.yaml config.
    On config error, returns all files so the linter runs and surfaces the error.
    """
    config_path = REPO_ROOT / ".lint.gitleaks.yaml"
    config: dict[str, Any] = {}

    if config_path.exists():
        try:
            config = load_yaml_config(config_path)
        except (OSError, yaml.YAMLError):
            return set(files)

    excluded_extensions = set(config.get("excluded_extensions", []))
    excluded_names = set(config.get("excluded_names", []))
    included_paths = config.get("included_paths", [])

    result = set()
    for f in files:
        # Check inclusion via glob patterns
        if included_paths and not is_path_included(f, included_paths):
            continue
        # Check extension exclusion
        if any(f.endswith(ext) for ext in excluded_extensions):
            continue
        # Check name exclusion
        if Path(f).name in excluded_names:
            continue
        result.add(f)
    return result


def _calculate_fileset_scripts(files: list[str]) -> set[str]:
    """Calculate fileset for scripts linter.

    Only includes pyproject.toml if it's in the files list.
    """
    result = set()
    for f in files:
        if f == "pyproject.toml" or f.endswith("/pyproject.toml"):
            result.add(f)
    return result


def _calculate_fileset_trivy(files: list[str]) -> set[str]:
    """Calculate fileset for trivy linter.

    Only includes uv.lock and Dockerfile files if they're in the files list.
    """
    result = set()
    for f in files:
        if f.endswith("uv.lock") or f.endswith("Dockerfile") or "Dockerfile" in f:
            result.add(f)
    return result


def _calculate_fileset_checkov(files: list[str]) -> set[str]:
    """Calculate fileset for checkov linter.

    Only includes files ending with openapi.json if they're in the files list.
    """
    result = set()
    for f in files:
        if f.endswith("openapi.json"):
            result.add(f)
    return result


def schedule_linters(
    linters: list[BaseLinter],
    files: list[str] | None = None,
) -> list[list[str]]:
    """Schedule linters into execution phases for optimal parallelism.

    Groups linters into phases based on:
    - File mutation behavior (mutating linters run sequentially first)
    - Fileset availability (linters with empty filesets are skipped)

    Execution strategy:
    - Phase 1..N: Each mutating linter runs alone (sequential phases)
    - Phase N+1: All read-only linters run together (parallel phase)

    Args:
        linters: List of linter instances to schedule.
        files: Optional list of files to filter. If None, indicates whole-repo scan.

    Returns:
        List of phases, where each phase is a list of linter names that can run in parallel.
        Empty list if all linters have empty filesets.

    Examples:
        >>> from scripts.dev.linter.linters import LINTERS
        >>>
        >>> # Whole-repo scan: all linters active
        >>> phases = schedule_linters(LINTERS, None)
        >>> # Phase 1: ["ruff"] (mutating)
        >>> # Phase 2: ["scripts", "astgrep", "mypy", ...] (read-only, parallel)
        >>>
        >>> # Filtered scan: only Python files
        >>> phases = schedule_linters(LINTERS, ["app/main.py"])
        >>> # Phase 1: ["ruff"] (mutating, has Python files)
        >>> # Phase 2: ["astgrep", "mypy", "detect-secrets", "gitleaks"] (read-only, match Python)
        >>> # Other linters skipped (empty filesets)
    """
    # Calculate filesets for each linter and filter out those with empty filesets
    mutating_linters: list[str] = []
    read_only_linters: list[str] = []

    for linter in linters:
        fileset = calculate_fileset(linter, files)
        # None means whole-repo scan (include linter)
        # Empty set means no files match (skip linter)
        if fileset is not None and len(fileset) == 0:
            continue

        if linter.mutates_files:
            mutating_linters.append(linter.name)
        else:
            read_only_linters.append(linter.name)

    # Build phases: mutating linters run sequentially, then all read-only in parallel
    phases: list[list[str]] = []

    # Each mutating linter gets its own phase
    for name in mutating_linters:
        phases.append([name])

    # All read-only linters run together in one phase
    if read_only_linters:
        phases.append(read_only_linters)

    return phases


def _run_linter_safe(
    linter: BaseLinter,
    files: list[str] | None,
) -> LinterResult:
    """Run a linter with exception handling.

    This is the worker function for parallel execution. It catches all exceptions
    and converts them to LinterResult to prevent executor failures.

    Args:
        linter: The linter instance to run.
        files: Optional list of files to filter.

    Returns:
        LinterResult indicating success or failure with error details.
    """
    try:
        if linter.supports_file_filtering:
            return linter.run(files)
        return linter.run()
    except subprocess.CalledProcessError as exc:
        return LinterResult(success=False, message=f"Process error: {exc}")
    except RuntimeError as exc:
        return LinterResult(success=False, message=str(exc))
    except OSError as exc:
        return LinterResult(success=False, message=f"OS error: {exc}")
    except yaml.YAMLError as exc:
        return LinterResult(success=False, message=f"YAML error: {exc}")
    except Exception as exc:
        return LinterResult(success=False, message=f"Unexpected error: {exc}")


def _execute_single_linter(
    linter_name: str,
    files: list[str] | None,
) -> dict[str, LinterResult]:
    """Execute a single linter sequentially.

    Args:
        linter_name: Name of the linter to run.
        files: Optional list of files to filter.

    Returns:
        Dictionary with single entry mapping linter name to result.
    """
    # Import here to avoid circular imports
    from scripts.dev.linter.linters import LINTER_MAP

    linter = LINTER_MAP.get(linter_name)
    if linter is None:
        return {linter_name: LinterResult(success=False, message=f"Unknown linter: {linter_name}")}

    result = _run_linter_safe(linter, files)
    return {linter_name: result}


def _execute_parallel_linters(
    linter_names: list[str],
    files: list[str] | None,
) -> dict[str, LinterResult]:
    """Execute multiple linters in parallel using ThreadPoolExecutor.

    Args:
        linter_names: List of linter names to run in parallel.
        files: Optional list of files to filter.

    Returns:
        Dictionary mapping linter names to their results.
    """
    # Import here to avoid circular imports
    from scripts.dev.linter.linters import LINTER_MAP

    results: dict[str, LinterResult] = {}
    future_to_linter: dict[concurrent.futures.Future[LinterResult], str] = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(linter_names)) as executor:
        for linter_name in linter_names:
            linter = LINTER_MAP.get(linter_name)
            if linter is None:
                results[linter_name] = LinterResult(
                    success=False, message=f"Unknown linter: {linter_name}"
                )
                continue

            future = executor.submit(_run_linter_safe, linter, files)
            future_to_linter[future] = linter_name

        for future in concurrent.futures.as_completed(future_to_linter):
            linter_name = future_to_linter[future]
            results[linter_name] = future.result()

    return results


def execute_phase(
    phase: list[str],
    files: list[str] | None = None,
) -> dict[str, LinterResult]:
    """Execute a phase of linters, running them in parallel if multiple.

    Args:
        phase: List of linter names to run in this phase.
        files: Optional list of files to filter. If None, indicates whole-repo scan.

    Returns:
        Dictionary mapping linter names to their LinterResult.

    Examples:
        >>> from scripts.dev.linter.linters import LINTER_MAP
        >>>
        >>> # Single linter (sequential)
        >>> results = execute_phase(["ruff"], None)
        >>> results["ruff"].success
        True
        >>>
        >>> # Multiple linters (parallel)
        >>> results = execute_phase(["mypy", "astgrep", "hadolint"], None)
        >>> len(results)
        3
    """
    if not phase:
        return {}

    if len(phase) == 1:
        return _execute_single_linter(phase[0], files)

    return _execute_parallel_linters(phase, files)
