#!/usr/bin/env python3
"""Check for forbidden spec import paths.

This script ensures no files under scripts/spec_manager/spec_manager/
contain imports from the old spec_refinement or spec_decomposition paths.

Exit codes:
    0: No forbidden imports found
    1: Forbidden imports detected
"""

import re
import sys
from pathlib import Path


def main() -> int:
    """Check for forbidden import patterns."""
    root = Path(__file__).resolve().parents[2]
    spec_manager_dir = root / "scripts" / "spec_manager" / "spec_manager"

    if not spec_manager_dir.exists():
        print(f"Error: {spec_manager_dir} does not exist")
        return 1

    forbidden_patterns = [
        re.compile(r"from\s+scripts\.spec_refinement"),
        re.compile(r"import\s+scripts\.spec_refinement"),
        re.compile(r"from\s+scripts\.spec_decomposition"),
        re.compile(r"import\s+scripts\.spec_decomposition"),
    ]

    violations = []

    for py_file in spec_manager_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), 1):
            for pattern in forbidden_patterns:
                if pattern.search(line):
                    violations.append(f"{py_file}:{line_num}: {line.strip()}")

    if violations:
        print("Forbidden import paths detected:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("\u2713 No forbidden import paths found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
