"""Root conftest for spec_manager tests.

Ensures ``get_project_root`` lru_cache is restored after tests that
clear or mock it, preventing cross-test state leakage.

Also injects the local Python AST analyzer as a test double for the
LLM-based ``code_analysis`` module so NO test makes real LLM calls.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from spec_manager.core.code_analysis import clear_cache
from spec_manager.core.project_root import get_project_root

# Capture these at import time, before any test can change them.
_REAL_CWD = os.getcwd()
_REAL_PROJECT_ROOT = get_project_root()


@pytest.fixture(autouse=True)
def _use_local_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject local Python AST analyzer globally so no test makes LLM calls."""
    from tests.unit.core.conftest import _local_python_analyzer

    monkeypatch.setattr(
        "spec_manager.core.code_analysis._default_analyzer",
        _local_python_analyzer,
    )
    clear_cache()


@pytest.fixture(autouse=True)
def _restore_project_root_cache() -> Generator[None]:
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
