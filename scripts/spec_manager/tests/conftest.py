"""Root conftest for spec_manager tests.

Ensures ``get_project_root`` lru_cache is restored after tests that
clear or mock it, preventing cross-test state leakage.
"""

from __future__ import annotations

import os
from typing import Generator

import pytest

from spec_manager.core.project_root import get_project_root

# Capture these at import time, before any test can change them.
_REAL_CWD = os.getcwd()
_REAL_PROJECT_ROOT = get_project_root()


@pytest.fixture(autouse=True)
def _restore_project_root_cache() -> Generator[None, None, None]:
    """Restore get_project_root cache and CWD after each test."""
    yield
    # Restore CWD if pyfakefs left it pointing to a non-existent path
    try:
        os.getcwd()
    except OSError:
        os.chdir(_REAL_CWD)
    # Re-seed cache if it was cleared
    if get_project_root.cache_info().currsize == 0:
        os.chdir(_REAL_CWD)
        try:
            get_project_root()
        except Exception:
            pass
