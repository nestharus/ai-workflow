#!/usr/bin/env python3
"""Script to automatically fix common mypy errors."""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent


def get_mypy_errors():
    """Get all mypy errors as a list."""
    result = subprocess.run(
        ["uv", "run", "lint", "mypy"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.stdout + result.stderr


def fix_dict_type_args(content: str) -> str:
    """Fix Missing type parameters for generic type \"dict\" errors."""
    # Replace dict() with dict[str, Any]() in function calls
    content = re.sub(r"\bdict\(\)", "dict[str, Any]()", content)

    # Replace = dict with = dict[str, Any] for return type annotations
    # But be careful not to replace dict[...] patterns
    content = re.sub(r":\s*dict\s*=", ": dict[str, Any] =", content)

    # Replace -> dict with -> dict[str, Any] for return type annotations
    content = re.sub(r"->\s*dict\s*:", "-> dict[str, Any]:", content)
    content = re.sub(r"->\s*dict\s*$", "-> dict[str, Any]", content, flags=re.MULTILINE)

    return content


def fix_list_type_args(content: str) -> str:
    """Fix Missing type parameters for generic type \"list\" errors."""
    # Replace = list with = list[Any] for assignments
    content = re.sub(r":\s*list\s*=", ": list[Any] =", content)

    # Replace -> list with -> list[Any] for return type annotations
    content = re.sub(r"->\s*list\s*:", "-> list[Any]:", content)
    content = re.sub(r"->\s*list\s*$", "-> list[Any]", content, flags=re.MULTILINE)

    return content


def add_any_import_if_needed(content: str) -> str:
    """Add 'Any' import if we used it but it's not imported."""
    if "dict[str, Any]" in content or "list[Any]" in content:
        # Check if Any is already imported
        if not re.search(r"from typing import.*\bAny\b", content):
            # Find the typing import line and add Any
            def add_any_to_import(match):
                imports = match.group(1)
                if "Any" not in imports:
                    # Add Any to the import list
                    return f"from typing import {imports}, Any"
                return match.group(0)

            content = re.sub(r"from typing import ([^;\n]+)", add_any_to_import, content, count=1)

    return content


def process_file(file_path: Path) -> bool:
    """Process a single file and return True if changes were made."""
    content = file_path.read_text()
    original = content

    content = fix_dict_type_args(content)
    content = fix_list_type_args(content)
    content = add_any_import_if_needed(content)

    if content != original:
        file_path.write_text(content)
        return True
    return False


def main():
    """Main entry point."""
    errors = get_mypy_errors()

    # Extract files with type-arg errors
    files_to_fix = set()
    for line in errors.split("\n"):
        if "[type-arg]" in line and (
            'Missing type parameters for generic type "dict"' in line
            or 'Missing type parameters for generic type "list"' in line
        ):
            match = re.match(r"^(.+?):\d+:", line)
            if match:
                file_path = REPO_ROOT / match.group(1)
                if file_path.exists():
                    files_to_fix.add(file_path)

    print(f"Found {len(files_to_fix)} files with type-arg errors")

    fixed_count = 0
    for file_path in sorted(files_to_fix):
        if process_file(file_path):
            print(f"Fixed: {file_path.relative_to(REPO_ROOT)}")
            fixed_count += 1

    print(f"\nFixed {fixed_count} files")


if __name__ == "__main__":
    main()
