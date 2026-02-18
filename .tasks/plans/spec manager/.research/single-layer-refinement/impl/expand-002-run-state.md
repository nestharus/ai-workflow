# Expansion Task: orchestration/run_state.py (File 2 of 33)

## Context

You are implementing the single-layer refactoring for the spec_manager project.
This file is **#2 in dependency order** — it manages run state including phase tracking.

## Authoritative references

1. **Proposal**: `.tasks/plans/spec manager/.research/single-layer-refinement/proposal.md`
   - Section 9.1: Three phases (Libraries → Architecture → Quality), forward-only
   - Section 9.5: Explicit iteration bounds
   - Section 9.6: Per-phase convergence

2. **ALGORITHM block**: The `# ALGORITHM(single-layer):` comment at the top of the target file.

3. **Dependency changes**: Search for `# IMPL(single-layer):` in already-implemented files:
   - `scripts/spec_manager/spec_manager/compliance/promotion/config.py` — PhaseId, GATE_PHASES, new GateId enum

## Target file

`scripts/spec_manager/spec_manager/orchestration/run_state.py`

## Instructions

1. **Read the target file completely** to understand the current code.

2. **Read proposal.md** Sections 9.1, 9.5, and 9.6 for the authoritative design.

3. **Read the IMPL notes** in config.py to understand what PhaseId/GATE_PHASES look like:
   ```
   rg "IMPL\(single-layer\)" scripts/spec_manager/spec_manager/compliance/promotion/config.py
   ```

4. **Find all consumers** of run_state.py:
   ```
   rg "from spec_manager.orchestration.run_state import" scripts/spec_manager/ --files-with-matches
   ```

5. **Implement the ALGORITHM block changes:**

   a. **Import PhaseId from config.py** (or define locally if already defined there).
      Use `from spec_manager.compliance.promotion.config import PhaseId` if appropriate.

   b. **Phase tracking**: Add `active_phase: PhaseId` field to RunState (or equivalent).
      Default to `"libraries"` (first phase).

   c. **Iteration bounds state**: Add fields for tracking per-phase iteration counts,
      stagnation detection per Section 9.5:
      - `phase_iterations: dict[PhaseId, int]` or similar
      - `stagnation_counter: int` or per-verifier tracking

   d. **Phase transition**: Add method/logic for advancing phase forward-only
      (libraries → architecture → quality). No backwards transitions.

   e. **Convergence state**: Track per-phase convergence criteria per Section 9.6.

   f. **Remove layer-specific state** if any exists (L1/L2/L3 tracking).

6. **Add IMPL notes** at key integration points:
   ```python
   # IMPL(single-layer): <description>
   ```

7. **Do NOT remove the ALGORITHM block or TODO block.**

8. **Do NOT modify any other files** — only the target file.

9. **Write the changes directly to the file.**

## Quality constraints

- Keep the code clean and consistent with existing style.
- Do not add backwards-compatibility shims.
- Do not add docstrings or comments to code you didn't change.
- Import PhaseId from config.py rather than redefining it.
