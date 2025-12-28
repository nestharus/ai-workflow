"""Find the test file for an implementation file.

Locates the corresponding test file using path mapping and fallback search.

Usage:
    uv run pr find-test-file app/services/auth.py
    uv run pr find-test-file app/services/auth.py --root /path/to/repo
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _is_test_file(path: Path) -> bool:
    """Check if a path is already a test file.

    Args:
        path: Path to check.

    Returns:
        True if this is a test file.
    """
    path_str = str(path)

    # Check if in test directories
    if "/tests/" in path_str or "/scripts/tests/" in path_str:
        return True

    # Check for test_ prefix in filename
    if path.name.startswith("test_"):
        return True

    # Check for _test suffix
    return bool(path.stem.endswith("_test"))


def _get_canonical_test_path(impl_path: Path, root: Path) -> Path | None:
    """Get the canonical test file path for an implementation file.

    Mapping rules:
    - app/foo/bar.py -> tests/unit/app/foo/test_bar.py
    - scripts/foo/bar.py -> scripts/tests/foo/test_bar.py

    Args:
        impl_path: Path to implementation file (relative to root).
        root: Repository root.

    Returns:
        Canonical test path, or None if mapping doesn't apply.
    """
    # Normalize to relative path
    try:
        rel_path = impl_path.relative_to(root)
    except ValueError:
        rel_path = impl_path

    parts = rel_path.parts

    if not parts:
        return None

    # app/... -> tests/unit/app/.../test_*.py
    if parts[0] == "app":
        test_parts = [*("tests", "unit"), *parts[:-1], f"test_{parts[-1]}"]
        return root / Path(*test_parts)

    # scripts/... (but not scripts/tests/...) -> scripts/tests/.../test_*.py
    if parts[0] == "scripts" and (len(parts) < 2 or parts[1] != "tests"):
        # scripts/foo/bar.py -> scripts/tests/foo/test_bar.py
        test_parts = [*("scripts", "tests"), *parts[1:-1], f"test_{parts[-1]}"]
        return root / Path(*test_parts)

    return None


def _search_for_test_file(impl_path: Path, root: Path) -> list[Path]:
    """Search for test files that reference the implementation.

    Uses grep to find test files that import or reference the module.

    Args:
        impl_path: Path to implementation file.
        root: Repository root.

    Returns:
        List of potential test file paths.
    """
    # Get module path for searching
    try:
        rel_path = impl_path.relative_to(root)
    except ValueError:
        rel_path = impl_path

    # Convert to module path: app/services/auth.py -> app.services.auth
    module_path = str(rel_path.with_suffix("")).replace("/", ".").replace("\\", ".")
    module_name = rel_path.stem  # Just the filename without extension

    candidates: set[Path] = set()

    # Search patterns
    patterns = [
        # Import patterns
        f"from {module_path} import",
        f"import {module_path}",
        # Partial module path (last two segments)
        f"from.*{module_name} import",
        # Mock/patch patterns
        f'"{module_path}"',
        f"'{module_path}'",
    ]

    # Search in test directories
    test_dirs = [root / "tests", root / "scripts" / "tests"]

    for test_dir in test_dirs:
        if not test_dir.exists():
            continue

        for pattern in patterns:
            try:
                result = subprocess.run(
                    ["grep", "-rl", "-E", pattern, str(test_dir)],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if line and line.endswith(".py"):
                            candidates.add(Path(line))
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue

    return sorted(candidates)


def find_test_file_command(file_path: str, root: str | None = None) -> int:
    """Find the test file for an implementation file.

    Outputs JSON with the result:
    - {"found": true, "test_file": "...", "method": "canonical|search|input"}
    - {"found": false, "reason": "...", "candidates": [...]}

    Args:
        file_path: Path to the implementation file.
        root: Repository root (defaults to cwd).

    Returns:
        Exit code (0 for success, 1 for not found).
    """
    root_path = Path(root) if root else Path.cwd()
    impl_path = Path(file_path)

    # Make absolute if relative
    if not impl_path.is_absolute():
        impl_path = root_path / impl_path

    # Check if file exists
    if not impl_path.exists():
        print(
            json.dumps(
                {
                    "found": False,
                    "path": file_path,
                    "reason": "file does not exist",
                    "candidates": [],
                }
            )
        )
        return 1

    # Check if input is already a test file
    if _is_test_file(impl_path):
        print(
            json.dumps(
                {
                    "found": True,
                    "path": file_path,
                    "test_file": str(impl_path),
                    "method": "input",
                    "reason": "input is already a test file",
                }
            )
        )
        return 0

    # Try canonical mapping
    canonical_path = _get_canonical_test_path(impl_path, root_path)
    if canonical_path and canonical_path.exists():
        print(
            json.dumps(
                {
                    "found": True,
                    "path": file_path,
                    "test_file": str(canonical_path),
                    "method": "canonical",
                }
            )
        )
        return 0

    # Fallback: search for test files
    candidates = _search_for_test_file(impl_path, root_path)

    if len(candidates) == 1:
        print(
            json.dumps(
                {
                    "found": True,
                    "path": file_path,
                    "test_file": str(candidates[0]),
                    "method": "search",
                }
            )
        )
        return 0

    if len(candidates) > 1:
        print(
            json.dumps(
                {
                    "found": False,
                    "path": file_path,
                    "reason": "multiple candidates found",
                    "candidates": [str(c) for c in candidates],
                }
            )
        )
        return 1

    # No test file found
    # Include where we expected to find it
    expected = str(canonical_path) if canonical_path else None
    print(
        json.dumps(
            {
                "found": False,
                "path": file_path,
                "reason": "no test file found",
                "expected_path": expected,
                "candidates": [],
            }
        )
    )
    return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run pr find-test-file <file_path> [--root <dir>]", file=sys.stderr)
        sys.exit(1)

    file_arg = sys.argv[1]
    root_arg = None

    if "--root" in sys.argv:
        idx = sys.argv.index("--root")
        if idx + 1 < len(sys.argv):
            root_arg = sys.argv[idx + 1]

    sys.exit(find_test_file_command(file_arg, root_arg))
