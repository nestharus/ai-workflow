# Implementation Plan: Merge `planning_v2/` into `planning/`

## Overview

Merge the 9-module `planning_v2/` package into the existing 2-module `planning/` package, rewriting all import paths, CLI registrations, and test locations so the codebase has a single unified `planning` module with no `_v2` suffix.

## Current State (Problems)

1. **Two disjoint planning packages** exist side-by-side:
   - `spec_manager/planning/` (2 files): Legacy DISCOVERY phase operations -- ID comparison, sequence checking, batch creation. Exports `run_planning()`.
   - `spec_manager/planning_v2/` (10 files): Algorithmic pseudocode-comment planning -- code parsing, comment insertion, reverse translation, adjacency/call-graph analysis, evidence store, gap bridge, workflow integration, CLI. Exports nothing at package level.

2. **Zero interaction** between the two packages -- they share no types, no imports, no CLI surface.

3. **Confusing naming**: `plan-v2` CLI subcommand alongside `plan`, `planning_v2` import paths, `"planning_v2.gap_bridge"` detector strings, `"planning_v2"` invariant family strings.

4. **No Phase enum entry** for `PLANNING_V2` in `refinement/workspace/state.py` (the v2 workflow uses `run_planning_v2_phase()` standalone, not the phase system).

5. **No tests** exist for the old `planning/` module (no `tests/planning/` directory).

## Target State

- Single `spec_manager/planning/` package containing **all** modules (legacy + v2).
- All imports use `spec_manager.planning.*` (no `_v2`).
- CLI exposes `plan` (legacy DISCOVERY) and `plan-algo` (algorithmic planning, renamed from `plan-v2`).
- Tests live in `tests/planning/` with both legacy and algorithmic test files.
- `planning_v2/` directory is deleted.
- Detector/invariant strings updated from `"planning_v2.*"` to `"planning.*"`.

## Additional Info

### What `planning/operations.py` does (and what stays)

`operations.py` implements the DISCOVERY phase used by the existing `plan` CLI command and `WorkspaceManager`:
- `IdComparison`, `SequenceIssue`, `Batch`, `PlanningResult` dataclasses
- `compare_ids()`, `find_missing_in_registry()`, `find_missing_in_libraries()`, `check_sequences()`, `create_batches()`, `run_planning()`
- Called from `cli.py:cmd_plan()`, `__init__.py:run_planning`, and `spec_manager/__init__.py`

This module is **fully retained** in its current location. It has a completely different domain (ID management / batch decomposition) from the v2 modules (pseudocode comment manipulation). No merging of functionality is needed -- they simply coexist in the same package.

### Module mapping: `planning_v2/X` to `planning/X`

| Source (v2)                  | Destination (planning)            | Notes                        |
|------------------------------|-----------------------------------|------------------------------|
| `planning_v2/__init__.py`    | Merge docstring into `planning/__init__.py` | Combine both docstrings      |
| `planning_v2/models.py`      | `planning/models.py`              | Move as-is                   |
| `planning_v2/code_parser.py` | `planning/code_parser.py`         | Move as-is                   |
| `planning_v2/inserter.py`    | `planning/inserter.py`            | Move as-is                   |
| `planning_v2/reverser.py`    | `planning/reverser.py`            | Move as-is                   |
| `planning_v2/adjacency.py`   | `planning/adjacency.py`           | Move as-is                   |
| `planning_v2/evidence_store.py` | `planning/evidence_store.py`   | Move as-is                   |
| `planning_v2/gap_bridge.py`  | `planning/gap_bridge.py`          | Move + update detector strings |
| `planning_v2/workflow.py`    | `planning/workflow.py`            | Move as-is                   |
| `planning_v2/cli.py`         | `planning/algo_cli.py`            | Rename to distinguish from legacy CLI entry |

### Import path rewrites needed

**Total: 37 `from spec_manager.planning_v2.*` imports across 18 files.**

#### Within the package itself (7 source files):

1. `planning/code_parser.py` (was `planning_v2/code_parser.py`):
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`

2. `planning/inserter.py` (was `planning_v2/inserter.py`):
   - `from spec_manager.planning_v2.code_parser import ...` -> `from spec_manager.planning.code_parser import ...`
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`
   - TYPE_CHECKING: `from spec_manager.planning_v2.evidence_store import ...` -> `from spec_manager.planning.evidence_store import ...`

3. `planning/reverser.py` (was `planning_v2/reverser.py`):
   - `from spec_manager.planning_v2.code_parser import ...` -> `from spec_manager.planning.code_parser import ...`
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`

4. `planning/adjacency.py` (was `planning_v2/adjacency.py`):
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`

5. `planning/evidence_store.py` (was `planning_v2/evidence_store.py`):
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`

6. `planning/gap_bridge.py` (was `planning_v2/gap_bridge.py`):
   - `from spec_manager.planning_v2.adjacency import ...` -> `from spec_manager.planning.adjacency import ...`
   - `from spec_manager.planning_v2.code_parser import ...` -> `from spec_manager.planning.code_parser import ...`
   - `from spec_manager.planning_v2.models import ...` -> `from spec_manager.planning.models import ...`

7. `planning/workflow.py` (was `planning_v2/workflow.py`):
   - 5 imports from `spec_manager.planning_v2.*` -> `spec_manager.planning.*`
   - 1 inline import from `spec_manager.planning_v2.adjacency` -> `spec_manager.planning.adjacency`

8. `planning/algo_cli.py` (was `planning_v2/cli.py`):
   - 10 inline imports from `spec_manager.planning_v2.*` -> `spec_manager.planning.*`

#### Outside the package (2 files):

9. `spec_manager/cli.py` (main CLI):
   - Line 1395: `from spec_manager.planning_v2.cli import setup_plan_v2_parser` -> `from spec_manager.planning.algo_cli import setup_plan_v2_parser`
   - Line 1441: `from spec_manager.planning_v2.cli import handle_plan_v2_command` -> `from spec_manager.planning.algo_cli import handle_plan_v2_command`

#### Test files (9 files in `tests/planning_v2/`):

All imports of `spec_manager.planning_v2.*` in test files must become `spec_manager.planning.*`:

10. `test_models.py`: 1 import
11. `test_code_parser.py`: 2 imports
12. `test_inserter.py`: 3 imports
13. `test_reverser.py`: 3 imports
14. `test_evidence_store.py`: 2 imports
15. `test_gap_bridge.py`: 4 imports
16. `test_cli.py`: 1 import (update to `from spec_manager.planning.algo_cli import ...`)
17. `test_workflow.py`: 1 import
18. `test_adjacency.py`: 2 imports

### Detector and invariant family string updates

In `planning/gap_bridge.py` (3 locations):
- `invariant_family="planning_v2"` -> `invariant_family="planning"`
- `detector="planning_v2.gap_bridge"` -> `detector="planning.gap_bridge"`

In `tests/planning_v2/test_gap_bridge.py` (1 location):
- `assert gaps[0].evidence[0].detector == "planning_v2.gap_bridge"` -> `"planning.gap_bridge"`

### Phase enum

No changes needed. The Phase enum in `refinement/workspace/state.py` has `EDIT_IN_PLACE = "edit_in_place"` but no `PLANNING_V2` entry, and the v2 workflow (`run_planning_v2_phase`) operates standalone without the phase system. This remains unchanged.

### CLI subcommand

The `plan-v2` subcommand name is kept for now to avoid breaking any scripts/docs that reference it. A future rename to `plan-algo` can be done as a separate change. The internal file is renamed to `algo_cli.py` for clarity within the package, but the user-facing command name stays `plan-v2` until explicitly deprecated.

## Plans

### Plan 1: Move v2 modules into `planning/` and rewrite intra-package imports

**Files changed**: 8 new files in `planning/`, 1 modified `planning/__init__.py`

Steps:
1. Copy `planning_v2/models.py` -> `planning/models.py`
2. Copy `planning_v2/code_parser.py` -> `planning/code_parser.py`
3. Copy `planning_v2/inserter.py` -> `planning/inserter.py`
4. Copy `planning_v2/reverser.py` -> `planning/reverser.py`
5. Copy `planning_v2/adjacency.py` -> `planning/adjacency.py`
6. Copy `planning_v2/evidence_store.py` -> `planning/evidence_store.py`
7. Copy `planning_v2/gap_bridge.py` -> `planning/gap_bridge.py`
8. Copy `planning_v2/workflow.py` -> `planning/workflow.py`
9. Copy `planning_v2/cli.py` -> `planning/algo_cli.py`
10. In each of the 9 new files, find-and-replace `spec_manager.planning_v2` with `spec_manager.planning` for all import statements.
11. In `planning/gap_bridge.py`, update the 3 detector/invariant strings:
    - `invariant_family="planning_v2"` -> `invariant_family="planning"`
    - `detector="planning_v2.gap_bridge"` -> `detector="planning.gap_bridge"`
12. Update `planning/__init__.py` to merge the v2 module docstring with the existing one. Add exports for the key v2 entry points:
    ```python
    from spec_manager.planning.workflow import run_planning_v2_phase
    ```
    Add `"run_planning_v2_phase"` to `__all__`.

**Verification**: `python -c "from spec_manager.planning.models import CommentKind; print('OK')"` should succeed.

### Plan 2: Update external imports (main CLI)

**Files changed**: `scripts/spec_manager/spec_manager/cli.py`

Steps:
1. Line 1395: Change `from spec_manager.planning_v2.cli import setup_plan_v2_parser` to `from spec_manager.planning.algo_cli import setup_plan_v2_parser`
2. Line 1441: Change `from spec_manager.planning_v2.cli import handle_plan_v2_command` to `from spec_manager.planning.algo_cli import handle_plan_v2_command`

**Verification**: `python -c "from spec_manager.cli import main; print('OK')"` should succeed.

### Plan 3: Move and update test files

**Files changed**: 10 test files moved from `tests/planning_v2/` to `tests/planning/`

Steps:
1. Create directory `scripts/spec_manager/tests/planning/` if it does not exist.
2. Create `scripts/spec_manager/tests/planning/__init__.py` (empty).
3. Move (copy then delete) all test files from `tests/planning_v2/` to `tests/planning/`:
   - `test_models.py`
   - `test_code_parser.py`
   - `test_inserter.py`
   - `test_reverser.py`
   - `test_evidence_store.py`
   - `test_gap_bridge.py`
   - `test_cli.py`
   - `test_workflow.py`
   - `test_adjacency.py`
4. In each moved test file, find-and-replace `spec_manager.planning_v2` with `spec_manager.planning` for all imports.
5. In `test_cli.py`, update the import path:
   - `from spec_manager.planning_v2.cli import ...` -> `from spec_manager.planning.algo_cli import ...`
6. In `test_gap_bridge.py`, update the assertion:
   - `assert gaps[0].evidence[0].detector == "planning_v2.gap_bridge"` -> `assert gaps[0].evidence[0].detector == "planning.gap_bridge"`

**Verification**: `cd scripts/spec_manager && uv run pytest tests/planning/ -v` should pass all tests.

### Plan 4: Delete `planning_v2/` directory and `tests/planning_v2/` directory

**Files changed**: Delete 10 source files + 10 test files + 2 `__init__.py` files

Steps:
1. Delete `scripts/spec_manager/spec_manager/planning_v2/` directory entirely.
2. Delete `scripts/spec_manager/tests/planning_v2/` directory entirely.
3. Verify no remaining references: `grep -r "planning_v2" scripts/spec_manager/` should return zero results.

**Verification**: `grep -r "planning_v2" scripts/spec_manager/` returns nothing.

### Plan 5: Documentation and README updates

**Files changed**: `scripts/spec_manager/README.md`, any docs referencing `planning_v2`

Steps:
1. Search for `planning_v2` references in `scripts/spec_manager/README.md` and other documentation files.
2. Update any references from `planning_v2` to `planning`.
3. Update the `planning/__init__.py` docstring to describe the full unified module:
   - Legacy operations: ID comparison, sequence checking, batch creation
   - Algorithmic operations: code parsing, comment insertion, reverse translation, adjacency analysis, evidence store, gap bridge, workflow

**Verification**: `grep -r "planning_v2" scripts/spec_manager/` and `grep -r "planning_v2" .tasks/` return nothing relevant.

## Execution Instructions

Execute Plans 1 through 5 sequentially. Each plan builds on the previous one. After Plan 1, the new `planning/` module is functional but old paths still work. After Plan 2, the CLI works. After Plan 3, tests pass from the new location. Plan 4 is the cleanup step (must come after 1-3). Plan 5 is cosmetic.

Run the full test suite after each plan to catch regressions:

```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
uv run pytest tests/ -v -p no:randomly
```

## Success Criteria

1. `grep -r "planning_v2" scripts/spec_manager/` returns zero results (no remaining references).
2. `uv run pytest tests/planning/ -v` passes all 9 test files (same test count as before).
3. `uv run pytest tests/ -v -p no:randomly` passes with no regressions in other test suites.
4. `python -c "from spec_manager.planning import run_planning; print('OK')"` succeeds (legacy).
5. `python -c "from spec_manager.planning.models import CommentKind; print('OK')"` succeeds (v2 types).
6. `python -c "from spec_manager.planning.algo_cli import setup_plan_v2_parser; print('OK')"` succeeds (CLI).
7. The `plan-v2` CLI subcommand still works: `uv run python -m spec_manager.cli plan-v2 --help`.
8. The `plan` CLI subcommand still works: `uv run python -m spec_manager.cli plan --help`.
9. No detector string contains `"planning_v2"` -- all use `"planning.gap_bridge"` and `invariant_family="planning"`.
