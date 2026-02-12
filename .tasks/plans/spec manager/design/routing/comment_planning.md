# Comment Planning

**Classification**: Business (algorithmic planning)
**Package**: `spec_manager/comment_planning/`
**Files**: 5
**Role**: Algorithmic planning for PDD. Comment insertion, reverse translation (code to pseudocode), call graph analysis, workflow integration.

---

## System

### Planning V2
**Modules**: `models.py`, `adjacency.py`, `inserter.py`, `reverser.py`, `evidence_store.py`, `gap_bridge.py`, `workflow.py`, `algo_cli.py`
**Purpose**: Phase-specific algorithmic operations — inserting spec comments into code, reverse-translating code to pseudocode, analyzing call graph adjacency.
**Surface API**:
- `run_planning_v2_phase(phase, workspace) -> PhaseResult`
- `parse_source(filepath) -> CodeFile`
- `insert_comments(code, comments) -> PatchedCode`
- `reverse_translate(code) -> Pseudocode`
- `analyze_adjacency(atoms) -> AdjacencyReport`
**Dependencies**: `core.code_analysis`, `refinement.hollowed_spec`, `compliance.detection`
**Consumers**: `orchestration.promotion_loop` (planning phase), CLI

**Note**: This is the *algorithmic planning* module (Design #1 lineage), distinct from `planner/` which is the *planner decision authority* (Design #3).
