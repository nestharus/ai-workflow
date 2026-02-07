# Implementation Plan: Wire branches/ into the Refinement Workflow Lifecycle

## Overview

Connect the `branches/` module (BranchManager facade) into the actual refinement workflow so that branch operations -- initialization, gap detection, compliance gating, promotion, and analysis generation -- execute as part of real workflow runs rather than only being importable via the lazy `WorkspaceManager.branches` property.

## Current State (Problems)

The `branches/` package provides a complete lifecycle via `BranchManager`:

- `initialize()` -- creates the `branches/algorithmic/`, `branches/architectural/`, `branches/analysis/` directory tree
- `register_atom()` / `list_atoms()` -- atom registry CRUD
- `collapse_codebase()` -- ingests existing code into Layer 1
- `GapDetector.scan_branch()` -- finds unimplemented comments, stubs, runtime errors in algorithmic code
- `ComplianceChecker.check_all()` -- runs 5 compliance gates before promotion
- `promote()` -- moves atoms from algorithmic to architectural branch via pins
- `regenerate_analysis()` -- computes lineage table, adjacency graph, drift report
- `save()` / `load()` -- persists all registries

**The integration gap**: `WorkspaceManager` lazily instantiates `BranchManager` on the `.branches` property (line 224 of `refinement/workspace/manager.py`), and `WorkspaceManager.initialize()` creates the `branches/` directory (line 280). However:

1. No workflow phase calls `branches.initialize()` to create the full branch subdirectory tree (algorithmic/architectural/analysis with their nested dirs)
2. No workflow phase calls `branches.collapse_codebase()` after edit-in-place analysis
3. No workflow phase calls `GapDetector.scan_branch()` after collapse
4. No workflow phase calls `branches.promote()` with compliance gating
5. No workflow phase calls `branches.regenerate_analysis()` to produce computed artifacts
6. No phase in the `Phase` enum covers branch lifecycle operations specifically
7. The `EDIT_IN_PLACE` phase exists in the enum but has no workflow implementation

**Key files involved**:

| File | Role |
|---|---|
| `scripts/spec_manager/spec_manager/branches/manager.py` | BranchManager facade (324 lines) |
| `scripts/spec_manager/spec_manager/branches/__init__.py` | Public exports including GapDetector, ComplianceChecker |
| `scripts/spec_manager/spec_manager/refinement/workspace/manager.py` | WorkspaceManager with lazy `.branches` property |
| `scripts/spec_manager/spec_manager/refinement/workspace/state.py` | Phase enum and WorkspaceState |
| `scripts/spec_manager/spec_manager/refinement/workflows/__init__.py` | Workflow module exports |
| `scripts/spec_manager/spec_manager/cli.py` | CLI commands |
| `scripts/spec_manager/spec_manager/core/edit_in_place_bridge.py` | Converts edit-in-place output to Gap/TrackedUnit |

## Target State

The branch lifecycle is integrated into the refinement workflow with the following operational flow:

```
[existing phases complete through EDIT_IN_PLACE]
    |
    v
BRANCH_INIT  -- BranchManager.initialize() + collapse_codebase()
    |
    v
BRANCH_GAPS  -- GapDetector.scan_branch() on algorithmic dir
    |
    v
BRANCH_COMPLY -- ComplianceChecker.check_all() gating
    |
    v
BRANCH_PROMOTE -- PromotionEngine.promote() + pin creation
    |
    v
BRANCH_ANALYZE -- AnalysisGenerator.regenerate_analysis()
    |
    v
[continues to AUDIT phase]
```

The CLI exposes `branches` subcommands for each operation, and each phase records results in WorkspaceState for traceability.

## Additional Info

### Design Decisions

1. **New Phase enum values vs. single BRANCH_LIFECYCLE**: Using separate Phase values for each branch step provides better granularity for resumption. If compliance gating fails, the user can fix the issue and resume from `BRANCH_COMPLY` without re-running collapse. Individual phases also enable clearer status reporting. The alternative (a single `BRANCH_LIFECYCLE` phase) would hide internal progress.

2. **Placement in phase order**: Branch operations come after `EDIT_IN_PLACE` because:
   - Collapse needs source code to exist (produced during implementation/edit-in-place)
   - Gap detection operates on the algorithmic branch (populated by collapse)
   - Compliance gating must run before architectural promotion
   - Analysis generation is the final computed artifact

3. **Optional vs. mandatory**: Branch phases should be optional. Not every workflow needs branch organization. The `get_next_phase()` method should skip branch phases if the branch system is not initialized. This matches the existing pattern where `EDIT_IN_PLACE` is in the enum but not in `get_next_phase()`'s `phase_order` list.

4. **Collapse source**: The collapse engine takes a `source_dir: Path`. For the integration, this should be the `repo_root` (the implementation target), not the spec snapshot. The edit-in-place bridge already produces `ProjectTranslationState` which maps to `TrackedUnit` objects -- these should feed into atom registration after collapse.

5. **Interaction with edit_in_place_bridge.py**: The bridge converts edit-in-place `SpecComment` and `FunctionInfo` into `Gap` and `TrackedUnit`. After collapse, atoms extracted by `CollapseEngine` should be registered in the `AtomRegistry`, and the bridge's `TrackedUnit` outputs can be cross-referenced to establish lineage.

### Phase Enum Placement

The `Phase` enum in `state.py` currently has `EDIT_IN_PLACE` as the last value. The new phases insert between `EDIT_IN_PLACE` and the end (or they come after `AUDIT` as post-processing). Since `EDIT_IN_PLACE` is not in `get_next_phase()`'s ordered list, and neither will the branch phases be (they are invoked explicitly), placement at the end of the enum is cleanest.

### Existing Patterns to Follow

- `run_phase_02_clean()` in `phase_02_clean.py` shows the pattern: instantiate `WorkspaceManager`, check prerequisites, call `start_phase()`, do work, call `complete_phase()` with outputs dict, handle errors with `fail_phase()`.
- `finalize_run()` in `finalize.py` shows how a late-stage phase checks prerequisite phases and generates reports.
- `cmd_scan_source()` in `cli.py` shows the edit-in-place analysis CLI pattern.

## Plans

### Plan 1: Add Branch Phase Enum Values and Update State Machine

Add four new Phase values to the enum and keep them out of `get_next_phase()` (they will be invoked explicitly via CLI, matching the pattern for `EDIT_IN_PLACE`).

**Changes**:

1. **`scripts/spec_manager/spec_manager/refinement/workspace/state.py`**:
   - Add four new Phase enum values after `EDIT_IN_PLACE`:
     ```python
     BRANCH_INIT = "branch_init"
     BRANCH_GAPS = "branch_gaps"
     BRANCH_PROMOTE = "branch_promote"
     BRANCH_ANALYZE = "branch_analyze"
     ```
   - Do NOT add them to `get_next_phase()`'s `phase_order` list (they are explicitly invoked, not auto-sequenced)

2. **`scripts/spec_manager/spec_manager/refinement/workspace/state.py`** `__post_init__`:
   - No changes needed -- the existing loop `for phase in Phase` already initializes PhaseResult for all enum members.

**Files modified**:
- `scripts/spec_manager/spec_manager/refinement/workspace/state.py`

**Test additions**:
- Unit test asserting the new Phase values exist and have correct string representations
- Unit test asserting `get_next_phase()` does NOT return any `BRANCH_*` phase (they are opt-in)

### Plan 2: Implement Branch Workflow Module

Create a new workflow module `branch_lifecycle.py` in the workflows directory that implements the four branch phase operations. Each operation follows the established pattern of `WorkspaceManager.start_phase()` / `complete_phase()` / `fail_phase()`.

**Changes**:

1. **`scripts/spec_manager/spec_manager/refinement/workflows/branch_lifecycle.py`** (new file):

   ```python
   """Branch lifecycle workflow for spec refinement.

   Provides four phase functions that wire the branches/ module
   into the refinement workflow:

   - run_branch_init: Initialize branch layout + collapse codebase
   - run_branch_gaps: Scan algorithmic branch for gaps
   - run_branch_promote: Compliance gate + promote to architectural
   - run_branch_analyze: Regenerate analysis branch
   """
   ```

   Functions to implement:

   a. `run_branch_init(run_id: str, source_dir: Path | None = None) -> dict[str, Any]`:
      - Instantiate `WorkspaceManager` with `run_id`
      - Check prerequisites: workspace initialized
      - Call `manager.branches.initialize()`
      - If `source_dir` is provided and exists, call `manager.branches.collapse_codebase(source_dir)`
      - Register all extracted atoms (from `CollapseResult`) into `manager.branches.atom_registry`
      - Call `manager.branches.save()` to persist registries
      - Record phase outputs: directory count, atom count by kind, collapse warnings

   b. `run_branch_gaps(run_id: str) -> dict[str, Any]`:
      - Instantiate `WorkspaceManager` with `run_id`
      - Check prerequisites: `BRANCH_INIT` completed
      - Instantiate `GapDetector`
      - Call `gap_detector.scan_branch(manager.branches.layout.algorithmic_dir())`
      - Convert `GapItem` results to JSON and write to `branches/analysis/gap_report.json`
      - Record phase outputs: total gaps, gaps by type, gap file path

   c. `run_branch_promote(run_id: str, skip_compliance: bool = False, atom_ids: list[str] | None = None) -> dict[str, Any]`:
      - Instantiate `WorkspaceManager` with `run_id`
      - Check prerequisites: `BRANCH_INIT` completed (gaps check is advisory, not blocking)
      - Call `manager.branches.promote(atom_ids=atom_ids, skip_compliance=skip_compliance)`
      - Call `manager.branches.save()` to persist pin registry updates
      - Record phase outputs: promoted count, skipped count, compliance result, new pin IDs

   d. `run_branch_analyze(run_id: str) -> dict[str, Any]`:
      - Instantiate `WorkspaceManager` with `run_id`
      - Check prerequisites: `BRANCH_INIT` completed
      - Call `manager.branches.regenerate_analysis()`
      - Record phase outputs: atom count, orphaned count, subgraph count, artifact paths

2. **`scripts/spec_manager/spec_manager/refinement/workflows/__init__.py`**:
   - Add imports for the four new functions
   - Add them to `__all__`

**Files modified**:
- `scripts/spec_manager/spec_manager/refinement/workflows/branch_lifecycle.py` (new)
- `scripts/spec_manager/spec_manager/refinement/workflows/__init__.py`

**Test additions**:
- Test `run_branch_init` with a temp directory containing Python files -- verify branch layout created, atoms registered
- Test `run_branch_init` without source_dir -- verify layout created, no collapse, no error
- Test `run_branch_gaps` after init -- verify gap report written
- Test `run_branch_promote` after init + atom registration -- verify promotion result
- Test `run_branch_analyze` after init -- verify analysis artifacts written
- Test prerequisite checks -- verify each function fails gracefully when prerequisites not met

### Plan 3: Add CLI Commands for Branch Operations

Add a `branches` subcommand group to the CLI with subcommands for each branch lifecycle operation. Follow the pattern of the existing `evidence-store` subcommand group.

**Changes**:

1. **`scripts/spec_manager/spec_manager/cli.py`**:

   Add a `branches` subcommand group with four subcommands:

   a. `spec-manager branches init <run_id> [--source-dir PATH] [--force]`:
      - Calls `run_branch_init(run_id, source_dir)`
      - Prints initialization summary and collapse results

   b. `spec-manager branches gaps <run_id>`:
      - Calls `run_branch_gaps(run_id)`
      - Prints gap summary by type

   c. `spec-manager branches promote <run_id> [--skip-compliance] [--atom-ids ID ...]`:
      - Calls `run_branch_promote(run_id, skip_compliance, atom_ids)`
      - Prints promotion result (promoted, skipped, compliance gate status)

   d. `spec-manager branches analyze <run_id>`:
      - Calls `run_branch_analyze(run_id)`
      - Prints analysis summary (atoms, orphaned, subgraphs)

   e. `spec-manager branches status <run_id>`:
      - Reads BranchManager state and prints a status overview
      - Shows: initialized (yes/no), atom count, pin count, slice count, last analysis timestamp

   f. `spec-manager branches run <run_id> [--source-dir PATH] [--skip-compliance]`:
      - Convenience command that runs all four phases in sequence: init -> gaps -> promote -> analyze
      - Stops on failure at any phase

   Implementation pattern (following `cmd_evidence_store`):
   ```python
   def cmd_branches(args: argparse.Namespace) -> int:
       branches_commands = {
           "init": cmd_branches_init,
           "gaps": cmd_branches_gaps,
           "promote": cmd_branches_promote,
           "analyze": cmd_branches_analyze,
           "status": cmd_branches_status,
           "run": cmd_branches_run,
       }
       return branches_commands[args.branches_command](args)
   ```

2. **Parser registration** in `main()`:
   - Add `branches` parser with subparsers
   - Register each subcommand with appropriate arguments
   - Add `"branches"` to the command dispatch (or handle as subgroup like `evidence-store`)

**Files modified**:
- `scripts/spec_manager/spec_manager/cli.py`

**Test additions**:
- Test CLI argument parsing for each subcommand
- Integration test: `branches run` with a temp workspace containing Python files
- Test `branches status` on uninitialized workspace returns clean output

### Plan 4: Wire Branch Init into Workspace Initialization

Optionally auto-initialize the branch layout during `WorkspaceManager.initialize()` so the branch directory structure is ready for use without a separate `branches init` call.

**Changes**:

1. **`scripts/spec_manager/spec_manager/refinement/workspace/manager.py`**:
   - In `initialize()`, after creating subdirectories (line 264-281) and before file enumeration, call `self.branches.initialize()` to create the full branch subdirectory tree (algorithmic/architectural/analysis with nested dirs)
   - This is safe because `BranchLayout.initialize()` uses `mkdir(parents=True, exist_ok=True)` and is idempotent
   - The lazy instantiation of `_branch_manager` will trigger on `self.branches` access, which is the desired behavior

2. **Conditional initialization**: Only call `branches.initialize()` if the `branches/` directory was just created (not on resume). Check with:
   ```python
   if not self.branches.is_initialized():
       self.branches.initialize()
   ```

**Files modified**:
- `scripts/spec_manager/spec_manager/refinement/workspace/manager.py`

**Test additions**:
- Test that `WorkspaceManager.initialize()` creates branch subdirectories
- Test that `WorkspaceManager.initialize()` on resume does not recreate branch structure
- Test that `manager.branches.is_initialized()` returns True after workspace init

### Plan 5: Connect Edit-in-Place Output to Branch Collapse

Create a workflow integration that takes the edit-in-place analysis output and feeds it into the branch collapse + atom registration pipeline, establishing the data flow between the two systems.

**Changes**:

1. **`scripts/spec_manager/spec_manager/refinement/workflows/branch_lifecycle.py`**:
   - Add function `run_branch_init_from_edit_in_place(run_id: str, project_state: ProjectTranslationState, source_dir: Path) -> dict[str, Any]`:
     - Calls `run_branch_init(run_id, source_dir)` for collapse
     - Uses `edit_in_place_bridge.function_info_to_tracked_unit()` to convert functions to TrackedUnits
     - Cross-references collapsed atoms with TrackedUnits by qualified name
     - Writes a lineage mapping (collapsed_atom_id -> tracked_unit_id) to `branches/analysis/eip_lineage.json`
     - Returns combined results

2. **`scripts/spec_manager/spec_manager/refinement/workflows/branch_lifecycle.py`**:
   - In `run_branch_gaps()`, after scanning the algorithmic branch, also incorporate gaps from the edit-in-place bridge:
     - Load `ProjectTranslationState` if available from the workspace
     - Call `project_state_to_gap_queue()` from `edit_in_place_bridge`
     - Merge edit-in-place gaps with branch gap detection results
     - Write combined gap report

3. **`scripts/spec_manager/spec_manager/cli.py`**:
   - Update `branches init` to accept `--from-scan PATH` that runs `scan-source` first, then feeds the result into `run_branch_init_from_edit_in_place()`

**Files modified**:
- `scripts/spec_manager/spec_manager/refinement/workflows/branch_lifecycle.py`
- `scripts/spec_manager/spec_manager/cli.py`

**Test additions**:
- Test `run_branch_init_from_edit_in_place` with a project containing stubs and comments
- Test that lineage mapping correctly links collapsed atoms to tracked units
- Test gap merging combines both edit-in-place gaps and branch gap detection results

### Plan 6: Add Tests for Full Branch Lifecycle Integration

Create a comprehensive test suite for the branch lifecycle workflow, covering the full cycle from init through analysis generation.

**Changes**:

1. **`scripts/spec_manager/tests/test_branch_lifecycle.py`** (new file):

   Test cases:

   a. **test_branch_init_creates_layout**: Initialize branches on a temp workspace, verify all expected directories exist (`branches/algorithmic/atoms/`, `branches/architectural/services/`, `branches/analysis/`, etc.)

   b. **test_branch_init_with_collapse**: Initialize with a source directory containing Python files, verify atoms are extracted and registered, verify CollapseResult is correct

   c. **test_branch_gaps_detects_stubs**: After init + collapse of a file with stub functions, verify gap detection finds them

   d. **test_branch_gaps_detects_comments**: After init + collapse of a file with spec comments, verify gap detection finds them

   e. **test_branch_promote_requires_compliance**: Attempt promotion without compliance, verify it fails when code has stubs (unless `skip_compliance=True`)

   f. **test_branch_promote_skip_compliance**: Promote with `skip_compliance=True`, verify atoms are promoted and pins created

   g. **test_branch_analyze_generates_artifacts**: After init + promote, run analysis and verify lineage_table.json, adjacency_graph.json, drift_report.md are written

   h. **test_branch_full_lifecycle**: End-to-end test: init -> collapse -> gaps -> promote (skip compliance) -> analyze -> save -> load -> verify state preserved

   i. **test_branch_status_uninitialized**: Verify status check returns clean result on uninitialized workspace

   j. **test_branch_phase_state_tracking**: Verify each phase operation correctly updates WorkspaceState (start_phase, complete_phase, fail_phase)

   k. **test_branch_resume_from_gaps**: Initialize and complete BRANCH_INIT, then verify BRANCH_GAPS can start without re-running init

2. **`scripts/spec_manager/tests/conftest.py`** (update if needed):
   - Add fixtures for temp workspace with branch structure
   - Add fixtures for sample Python source files (with stubs and comments)

**Files modified**:
- `scripts/spec_manager/tests/test_branch_lifecycle.py` (new)
- `scripts/spec_manager/tests/conftest.py` (possibly updated)

## Execution Instructions

Execute plans in order: Plan 1, Plan 2, Plan 3, Plan 4, Plan 5, Plan 6.

**Dependency chain**:
- Plan 1 (Phase enum) must be first -- all other plans depend on the new Phase values
- Plan 2 (workflow module) depends on Plan 1
- Plan 3 (CLI) depends on Plan 2
- Plan 4 (workspace init wiring) depends on Plan 1 only
- Plan 5 (edit-in-place connection) depends on Plan 2
- Plan 6 (tests) depends on Plans 1-5

**Safe parallel execution**:
- Phase A: Plan 1
- Phase B: Plans 2 and 4 (independent of each other, both depend on Plan 1)
- Phase C: Plans 3 and 5 (Plan 3 depends on Plan 2; Plan 5 depends on Plan 2)
- Phase D: Plan 6 (depends on all)

For each plan:
1. Read the target files and understand existing patterns
2. Implement changes
3. Run verification commands
4. Confirm imports and existing tests still pass

**Verification commands**:
```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager

# Check new Phase values exist
uv run python -c "
from spec_manager.refinement.workspace.state import Phase
for p in ['branch_init', 'branch_gaps', 'branch_promote', 'branch_analyze']:
    assert hasattr(Phase, p.upper()), f'Missing Phase.{p.upper()}'
print('Phase enum OK')
"

# Check branch lifecycle imports
uv run python -c "
from spec_manager.refinement.workflows.branch_lifecycle import (
    run_branch_init, run_branch_gaps, run_branch_promote, run_branch_analyze
)
print('Branch lifecycle imports OK')
"

# Check CLI parses branches subcommand
uv run python -m spec_manager.cli branches --help

# Check no import errors in full chain
uv run python -c "
from spec_manager.branches import BranchManager
from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.core.edit_in_place_bridge import project_state_to_gap_queue
print('All imports OK')
"

# Run existing tests (no branch tests yet, but ensure nothing breaks)
uv run pytest -x --tb=short -p no:randomly

# Run new branch lifecycle tests
uv run pytest tests/test_branch_lifecycle.py -v --tb=short
```

## Success Criteria

1. Four new `Phase` enum values (`BRANCH_INIT`, `BRANCH_GAPS`, `BRANCH_PROMOTE`, `BRANCH_ANALYZE`) exist in `state.py` and do NOT appear in `get_next_phase()` auto-sequence
2. `branch_lifecycle.py` workflow module implements all four phase functions following the `start_phase/complete_phase/fail_phase` pattern
3. CLI exposes `branches` subcommand group with `init`, `gaps`, `promote`, `analyze`, `status`, and `run` subcommands
4. `WorkspaceManager.initialize()` auto-initializes the branch directory structure
5. `run_branch_init` with a source directory successfully collapses code and registers atoms
6. `run_branch_gaps` detects stubs and comments in the algorithmic branch
7. `run_branch_promote` enforces compliance gates (or skips them on flag) and creates pins
8. `run_branch_analyze` writes `lineage_table.json`, `adjacency_graph.json`, and `drift_report.md` to the analysis branch
9. Each phase records outputs in `WorkspaceState` and is visible via `branches status`
10. Edit-in-place output can be fed into branch collapse via `--from-scan` flag
11. Full lifecycle test passes: init -> collapse -> gaps -> promote -> analyze -> save -> load -> verify
12. All existing tests continue to pass (no regressions)
13. No circular import dependencies between `branches/`, `refinement/workflows/`, and `core/`
