# Expansion Task: compliance/promotion/config.py (File 1 of 33)

## Context

You are implementing the single-layer refactoring for the spec_manager project.
This file is **#1 in dependency order** — it defines core enums and types that all
other files depend on.

## Authoritative references

1. **Proposal**: `.tasks/plans/spec manager/.research/single-layer-refinement/proposal.md`
   - Section 9.1: Three phases (Libraries → Architecture → Quality), forward-only
   - Section 10: Compliance gates reorganized for single-layer
   - Section 10.1: Aspect gate groups per phase
   - Section 10.2: What survives, converts, eliminates

2. **ALGORITHM block**: The `# ALGORITHM(single-layer):` comment at the top of the target file.

## Target file

`scripts/spec_manager/spec_manager/compliance/promotion/config.py`

## Instructions

1. **Read the target file completely** to understand the current code.

2. **Read proposal.md** Sections 9.1, 10.1, and 10.2 for the authoritative design.

3. **Read these dependency/consumer files** to understand what imports from config.py:
   - `scripts/spec_manager/spec_manager/compliance/promotion/__init__.py`
   - `scripts/spec_manager/spec_manager/compliance/promotion/result.py`
   - Run: `rg "from spec_manager.compliance.promotion.config import" scripts/spec_manager/ --files-with-matches`
   to find all consumers.

4. **Implement the ALGORITHM block changes:**

   a. **GateId enum changes:**
      - Remove: PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE, EDGE_REALIZATION, NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS, TEST_PIN_ALIGNMENT
      - Add: SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED
      - Merge TESTS_PASS into ALL_TESTS_PASS (remove TESTS_PASS, keep ALL_TESTS_PASS)

   b. **PhaseId type:** Add `PhaseId = Literal['libraries', 'architecture', 'quality']` if not already present.
      If it exists elsewhere (e.g., run_state.py or core/), note that but still ensure config.py
      can reference it.

   c. **Gate-to-phase mapping:** Add a mapping structure (dict or similar) that maps each GateId
      to the list of phases it applies to. Some gates (ALL_TESTS_PASS, contract verifiers) run
      in multiple phases. This replaces per-layer config.

   d. **Default gate specs:** Update `default()` to set:
      - CALL_GRAPH_CONNECTED → advisory/soft
      - NO_STUB_FUNCTIONS → advisory/soft
      - ALL_TESTS_PASS → hard/required (all phases)
      - SHAPE_VERIFIERS_PASS → hard/required
      - IMPORT_BOUNDARY_CHECK → hard/required
      - SHAPE_DRIFT_RESOLVED → hard/required

   e. **Remove per-layer config** if any exists (no separate L1/L2/L3 gate configs).

5. **Add IMPL notes** at key integration points using this format:
   ```python
   # IMPL(single-layer): <description of what changed and what consumers should know>
   ```
   Place these near:
   - The GateId enum (what was added/removed)
   - The PhaseId definition
   - The gate-to-phase mapping
   - Any removed functionality

6. **Do NOT remove the ALGORITHM block or TODO block** — those stay as documentation.

7. **Do NOT modify any other files** — only modify the target file. Consumer files
   will be updated in their own turn.

8. **Write the changes directly to the file.** This is an implementation task, not just analysis.

## Note format for downstream detection

Later files in the pipeline will `rg "IMPL(single-layer)"` to discover what changed
in their dependencies. Make your notes specific enough that a downstream file can
understand the interface change without reading the full diff. Example:

```python
# IMPL(single-layer): GateId enum — removed PIN_COVERAGE, PIN_CONSUMPTION_COVERAGE,
#   EDGE_REALIZATION, NO_INLINED_ATOM_LOGIC, ARCH_DRIFT_PASS, TEST_PIN_ALIGNMENT.
#   Added SHAPE_VERIFIERS_PASS, IMPORT_BOUNDARY_CHECK, SHAPE_DRIFT_RESOLVED.
#   Merged TESTS_PASS into ALL_TESTS_PASS.
```

## Quality constraints

- Keep the code clean and consistent with existing style.
- Do not add backwards-compatibility shims.
- Do not add docstrings or comments to code you didn't change.
- Preserve existing test infrastructure hooks (e.g., _default_test_command).
