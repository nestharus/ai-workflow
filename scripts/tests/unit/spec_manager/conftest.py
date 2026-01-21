"""Pytest configuration for spec_manager tests.

This conftest.py adds the spec_manager package to sys.path so that
imports like `from spec_manager.core.data_structures import ...` work
without requiring sys.path manipulation in individual test files.

The spec_manager is a standalone sub-project with its own pyproject.toml
located at scripts/spec_manager/. Tests import from the spec_manager
package namespace directly.
"""

import sys
from pathlib import Path

# Add scripts/spec_manager to sys.path so that `spec_manager` can be imported
_spec_manager_root = (Path(__file__).parent.parent.parent.parent / "spec_manager").resolve()
if str(_spec_manager_root) not in sys.path:
    sys.path.insert(0, str(_spec_manager_root))
