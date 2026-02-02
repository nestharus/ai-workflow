"""Spec refinement package for refining and executing large specs."""

from __future__ import annotations

import sys
from pathlib import Path

_SPEC_MANAGER_ROOT = (Path(__file__).resolve().parent.parent / "spec_manager").resolve()
if _SPEC_MANAGER_ROOT.exists() and str(_SPEC_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPEC_MANAGER_ROOT))

__version__ = "0.1.0"
