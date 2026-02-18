# GLM Task: Test & Fix — compliance/promotion/config.py (File 1 of 33)

## What changed

`scripts/spec_manager/spec_manager/compliance/promotion/config.py` was refactored:

1. **GateId enum**: Removed PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE, EDGE_REALIZATION,
   NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS, TEST_PIN_ALIGNMENT, TESTS_PASS.
   Added SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED.

2. **New types**: `PhaseId = Literal["libraries", "architecture", "quality"]`,
   `ALL_PHASES`, `GATE_PHASES` dict mapping gates to phases.

3. **Updated defaults**: `_default_severity()` and `default()` updated for new gate set.

## Your task

1. Run the config-specific test file:
   ```
   cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow && uv run pytest scripts/spec_manager/tests/unit/compliance/promotion/test_config.py -x -v 2>&1 | head -100
   ```

2. If tests fail because they reference removed GateId values (PIN_COVERAGE, etc.),
   **update the tests** to use the new gate set. Do NOT add backwards-compatibility shims.

3. If tests check the count of GateId members, update the count to match the new enum.

4. If tests verify default() behavior, update expected values to match new defaults.

5. After fixing, re-run the tests to confirm they pass.

6. Also run a quick import check on the main module:
   ```
   cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow && uv run python -c "from spec_manager.compliance.promotion.config import GateId, PhaseId, GATE_PHASES, ALL_PHASES; print('OK', len(GateId), len(GATE_PHASES))"
   ```

## Constraints

- Only modify `test_config.py` and the target `config.py` if needed.
- Do NOT modify other test files (test_pin_coverage.py, test_test_pin_gate.py, etc.) —
  those will be handled when their source modules are processed.
- Do NOT add backwards-compatibility shims or re-exports for removed gates.
