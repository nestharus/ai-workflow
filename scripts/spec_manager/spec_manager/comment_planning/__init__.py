"""Algorithmic planning for prototype-driven development.

Modules:
- models: Core data structures and CodeFile factory (parse_source/parse_file)
- inserter: Comment insertion engine
- adjacency: Call graph analysis and store-touch detection
- evidence_store: Integration with hollowed-out spec evidence
- gap_bridge: Bridge to existing gap detection system
- algo_cli: CLI commands for algorithmic planning operations
- workflow: Workflow integration with workspace/phase system
"""

from spec_manager.comment_planning.workflow import run_planning_v2_phase

__all__ = ["run_planning_v2_phase"]
