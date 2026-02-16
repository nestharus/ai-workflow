"""Language-agnostic configuration for source code processing.

All language-specific assumptions are centralized here. Modules that need
to discover source files, detect comments, or identify language constructs
import from this module instead of hardcoding Python-specific values.

To support a new language, update these constants or make them configurable
via RunConfig.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

#: File extensions treated as source code.
SOURCE_EXTENSIONS: frozenset[str] = frozenset({".py"})

#: Glob patterns for source file discovery (derived from SOURCE_EXTENSIONS).
SOURCE_GLOBS: list[str] = [f"*{ext}" for ext in sorted(SOURCE_EXTENSIONS)]

#: Recursive glob patterns.
SOURCE_RGLOBS: list[str] = [f"**/*{ext}" for ext in sorted(SOURCE_EXTENSIONS)]

#: Package marker files (directories containing these are packages).
PACKAGE_MARKERS: frozenset[str] = frozenset({"__init__.py"})

#: Directories to exclude from source scanning.
EXCLUDE_DIRS: frozenset[str] = frozenset({"__pycache__", ".git", "node_modules", ".tox", ".venv"})

# ---------------------------------------------------------------------------
# Syntax conventions
# ---------------------------------------------------------------------------

#: Single-line comment prefix.
COMMENT_PREFIX: str = "# "

#: Standard indentation width (spaces).
INDENT_SIZE: int = 4

#: Prefix for private/internal names.
PRIVATE_PREFIX: str = "_"

#: Dunder (magic method) pattern.
DUNDER_RE: re.Pattern[str] = re.compile(r"^__[a-zA-Z_]+__$")

# ---------------------------------------------------------------------------
# Function/class detection keywords (for heuristic scanning)
# ---------------------------------------------------------------------------

#: Keywords that start a function definition line.
FUNCTION_KEYWORDS: frozenset[str] = frozenset({"def "})

#: Keywords that start a class definition line.
CLASS_KEYWORDS: frozenset[str] = frozenset({"class "})

#: Keywords that start an import line.
IMPORT_KEYWORDS: frozenset[str] = frozenset({"import ", "from "})

#: Error-raising keyword pattern.
RAISE_PATTERN: re.Pattern[str] = re.compile(r"^\s*raise\s+", re.MULTILINE)

#: Decorator prefix.
DECORATOR_PREFIX: str = "@"

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

#: Test file naming patterns (basename globs).
TEST_FILE_PATTERNS: list[str] = ["test_*.py", "*_test.py"]

#: Path segments that indicate test code.
TEST_PATH_SEGMENTS: frozenset[str] = frozenset({"test", "tests"})

#: Function name prefixes that identify test functions.
TEST_FUNCTION_PREFIXES: list[str] = ["test_"]

#: Qualified-name prefixes that identify test classes or suites.
TEST_QUALIFIED_PREFIXES: list[str] = ["Test"]

#: Test configuration files that indicate a test framework.
TEST_CONFIG_FILES: list[str] = ["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"]

#: Default test command.
DEFAULT_TEST_COMMAND: list[str] = ["pytest", "-x", "--tb=short"]

#: Default smoke-test command (syntax + import-graph smoke).
DEFAULT_SMOKE_COMMAND: str = (
    "uv run python -m compileall -q . && "
    "uv run python -c 'import importlib,pathlib;pkgs=sorted({p.parent.name for p in "
    'pathlib.Path(".").glob("*/__init__.py") if p.parent.name not in {"tests","test"}});'
    "[importlib.import_module(name) for name in pkgs];"
    'print("import-smoke:", ", ".join(pkgs) if pkgs else "none")\''
)

# ---------------------------------------------------------------------------
# Linting / infrastructure comment markers
# ---------------------------------------------------------------------------

#: Patterns matching infrastructure comments (linter directives, type ignores).
INFRASTRUCTURE_COMMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^type:\s*ignore"),
    re.compile(r"^noqa"),
    re.compile(r"^pragma:\s*no\s*cover"),
    re.compile(r"^pylint:\s*(disable|enable)"),
    re.compile(r"^fmt:\s*(on|off)"),
    re.compile(r"^isort:\s*(skip|on|off)"),
    re.compile(r"^mypy:\s*"),
    re.compile(r"^ruff:\s*"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_source_file(path_suffix: str) -> bool:
    """Check if a file suffix matches a source extension."""
    return path_suffix in SOURCE_EXTENSIONS


def is_package_marker(filename: str) -> bool:
    """Check if a filename is a package marker."""
    return filename in PACKAGE_MARKERS


def is_excluded_dir(dirname: str) -> bool:
    """Check if a directory name should be excluded from scanning."""
    return dirname in EXCLUDE_DIRS


def is_test_file(filename: str) -> bool:
    """Check if a filename matches test file naming patterns."""
    import fnmatch

    return any(fnmatch.fnmatch(filename, pat) for pat in TEST_FILE_PATTERNS)


def is_test_path(path: str) -> bool:
    """Check if a path indicates test code via path segments or filename patterns."""
    normalized = str(path or "").replace("\\", "/").strip("/")
    if not normalized:
        return False
    parts = [segment.lower() for segment in normalized.split("/") if segment]
    if any(segment in TEST_PATH_SEGMENTS for segment in parts):
        return True
    return is_test_file(parts[-1])


def is_test_symbol(name: str, qualified_name: str = "") -> bool:
    """Check if function/class naming indicates a test symbol."""
    normalized_name = str(name or "").strip().lower()
    normalized_qualified = str(qualified_name or "").strip().lower()
    if any(normalized_name.startswith(prefix.lower()) for prefix in TEST_FUNCTION_PREFIXES):
        return True
    return any(
        normalized_qualified.startswith(prefix.lower()) for prefix in TEST_QUALIFIED_PREFIXES
    )


def is_private_name(name: str) -> bool:
    """Check if a name is private (starts with underscore, not dunder)."""
    return name.startswith(PRIVATE_PREFIX) and not DUNDER_RE.match(name)


def is_dunder(name: str) -> bool:
    """Check if a name is a dunder (magic method)."""
    return bool(DUNDER_RE.match(name))


def source_rglob(directory: Path) -> list[Path]:
    """Recursively find all source files in a directory, excluding markers and cache dirs."""
    results: list[Path] = []
    for ext in sorted(SOURCE_EXTENSIONS):
        for p in directory.rglob(f"*{ext}"):
            if any(is_excluded_dir(part) for part in p.parts):
                continue
            results.append(p)
    return sorted(results)


def source_rglob_no_markers(directory: Path) -> list[Path]:
    """Like source_rglob but also excludes package markers."""
    return [p for p in source_rglob(directory) if not is_package_marker(p.name)]
