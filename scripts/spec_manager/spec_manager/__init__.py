"""Spec Manager - specification management library.

The system consists of:
1. Refinement Pipeline: 19-phase LLM orchestration for spec refinement
2. PDD Modules: Standalone packages for prototype-driven development
   - branches: Branch lifecycle management
   - pin_functions: Pin-function management
   - planning: Algorithmic planning (code parser, inserter, reverser)
   - compliance: Detection, promotion, and coverage analysis
   - projection: Lineage tracking and drift detection
   - analysis: Adjacency detection and analysis generation
"""

from __future__ import annotations

import sys
from pathlib import Path

_SPEC_MANAGER_ROOT = Path(__file__).resolve().parent.parent
if str(_SPEC_MANAGER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPEC_MANAGER_ROOT))
