# Test & Fix: orchestration/run_state.py (File 2 of 33)

## What changed

`scripts/spec_manager/spec_manager/orchestration/run_state.py` was refactored for single-layer:

1. RunState gains: active_phase (PhaseId), phase_iteration_counts, stagnation tracking, convergence state
2. RunStateManager gains: increment_phase_iteration(), record_verifier_progress(), advance_phase(), update_phase_convergence(), is_phase_converged()
3. Forward-only phase transitions (libraries → architecture → quality)
4. Corrupt run_state.json recovery with backup

## Your task

1. Run the run_state test:
   ```
   cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow && uv run pytest scripts/spec_manager/tests/unit/orchestration/test_e2e_pipeline.py -x -v -p no:randomly 2>&1 | head -80
   ```

2. Also run any run_state-specific tests:
   ```
   cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow && uv run pytest scripts/spec_manager/tests/ -k "run_state" -x -v -p no:randomly 2>&1 | head -80
   ```

3. If tests fail due to the changes (e.g., referencing removed layer fields or missing new fields),
   update the tests to match the new RunState/RunStateManager interface.

4. After fixing, re-run the tests to confirm they pass.

## Constraints

- Only modify test files and run_state.py if needed.
- Do NOT modify other source files.
- Do NOT add backwards-compatibility shims.
