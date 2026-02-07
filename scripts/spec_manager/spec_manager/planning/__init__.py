"""Planning phase operations for spec management.

Goal: Decompose a large change into small, safe batches.

Legacy operations (DISCOVERY phase):
- compare_ids: Compare libs.md IDs against plan/library headers
- find_missing: Find IDs not in libs.md
- check_sequences: Detect numbering gaps/duplicates
- create_batches: Group changes into processable batches

Algorithmic planning (edit-in-place paradigm):
- models: Core data structures (PseudocodeComment, InsertionPoint, etc.)
- code_parser: Python-specific code parser using ast + tokenize
- inserter: Comment insertion engine with context-aware placement
- reverser: Reverse translation engine (code -> pseudocode comments)
- adjacency: Call graph analysis and store-touch detection
- evidence_store: Integration with hollowed-out spec evidence
- gap_bridge: Bridge to existing gap detection system
- algo_cli: CLI commands for algorithmic planning operations
- workflow: Workflow integration with workspace/phase system
"""

from __future__ import annotations

from spec_manager.planning.operations import (
    check_sequences,
    compare_ids,
    create_batches,
    find_missing_in_libraries,
    find_missing_in_registry,
    run_planning,
)
from spec_manager.planning.workflow import run_planning_v2_phase

__all__ = [
    "check_sequences",
    "compare_ids",
    "create_batches",
    "find_missing_in_libraries",
    "find_missing_in_registry",
    "run_planning",
    "run_planning_v2_phase",
]
