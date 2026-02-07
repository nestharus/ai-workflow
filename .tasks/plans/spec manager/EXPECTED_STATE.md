# Expected State: Phase 1 Completion

When Phase 1 (Consolidation & Implementation) is done, this is what the
spec_manager package should look like.

---

## Package Structure

```
spec_manager/
├── __init__.py              # Top-level exports (core types + entry points)
├── __main__.py              # Entry point
├── cli.py                   # CLI wiring layer (imports from all subsystems)
├── core/                    # Shared infrastructure (NO refinement dependency)
│   ├── agent_utils.py       # LLM agent runner [DONE]
│   ├── annotations.py       # Annotation parsing
│   ├── compat.py            # Python compat helpers
│   ├── context_index.py     # ContextIndex for Phase 2
│   ├── coverage.py          # Coverage tracking
│   ├── data_structures.py   # FileSections, FileTerms
│   ├── edit_in_place.py     # Plan 01: edit-in-place engine
│   ├── edit_in_place_bridge.py
│   ├── evidence_index.py    # EvidenceIndex for hollowed specs [DONE]
│   ├── evidence_pointers.py # Evidence pointer parsing [DONE]
│   ├── file_id_lookup.py    # File ID lookup builder [DONE]
│   ├── gap.py               # Gap types [DONE]
│   ├── gap_compat.py        # Gap compatibility
│   ├── gap_queue.py         # GapQueue [DONE]
│   ├── gaps.py              # GapSynthesizer v1 + Severity
│   ├── json_extraction.py   # JSON payload extraction [DONE]
│   ├── run_folder.py        # RunFolderStructure [DONE]
│   └── ...                  # id_registry, provenance, sections, etc.
│
├── refinement/              # 19-phase LLM pipeline (active system)
│   ├── workflows/           # Phase implementations
│   ├── workspace/           # WorkspaceManager + Phase enum
│   ├── interactive/         # Interactive ambiguity resolution
│   ├── hollowed_spec/       # Hollowed-out spec system
│   ├── evals/               # Eval framework
│   ├── formats.py           # LLM output parsing (re-exports from core)
│   └── ...
│
├── branches/                # Plan 04: Branch organization [CLEAN]
├── pin_functions/           # Plan 02: Pin-function management [CLEAN]
├── planning/                # Plan 03: Algorithmic planning [CLEAN]
├── compliance/              # Plans 05, 06, 08 [CLEAN]
│   ├── detection/           # Executable gap detection
│   ├── promotion/           # Promotion gates
│   └── coverage/            # Entity coverage
├── projection/              # Plan 09: Lineage + drift [CLEAN]
├── analysis/                # Plans 07, 11: Adjacency + generation [CLEAN]
├── strategies/              # Plan 10: Strategy evolution [ACCEPTABLE]
│   └── implementations/format_repair.py → refinement.repair (LLM-specific)
├── schemas/                 # Pydantic schemas [CLEAN]
├── decomposition/           # Decomposition utilities [CLEAN]
├── labyrinth/               # Eval labyrinth framework [CLEAN]
└── utils/                   # Misc utilities
```

---

## Import Rules (ACHIEVED)

### core/ imports NOTHING from refinement/ — DONE
### schemas/ imports NOTHING from refinement/ — DONE
### PDD modules import from core/ not refinement/ — DONE

All PDD modules are clean:
- `planning/` — 0 refinement imports
- `branches/` — 0 refinement imports
- `pin_functions/` — 0 refinement imports
- `projection/` — 0 refinement imports
- `analysis/` — 0 refinement imports
- `compliance/` — 0 refinement imports
- `decomposition/` — 0 refinement imports
- `labyrinth/` — 0 refinement imports

### Acceptable boundary imports:
- `cli.py` — top-level wiring layer, dispatches to all subsystems
- `strategies/implementations/format_repair.py` — wraps refinement LLM repair

### refinement/ CAN import from core/ and PDD modules — correct

---

## Remaining Work

### Cross-contamination: COMPLETE

All structural violations are resolved. The remaining refinement imports
in cli.py and format_repair.py are architecturally correct.

### Next: Verify implementations match plans

Each PDD module was built per its plan. Verify:
1. All plan requirements are implemented
2. No hardcoded values or reward hacking in tests
3. Tests test real behavior, not implementation details
4. No dead code or orphaned files
5. CLI commands work correctly

### Next: Check for dead code and unused files

Scan for:
- Functions defined but never called
- Files that are never imported
- Test files that don't test anything meaningful
- Re-exports that are no longer needed

---

## Test State

All tests must pass: `uv run python -m pytest scripts/spec_manager/tests/ -p no:randomly -x -q`
Current: 700 passed, 2 warnings

Tests should:
- Not import from deleted packages
- Not have hardcoded values that mask bugs
- Test actual behavior, not implementation details

---

## What "Done" Looks Like

Phase 1 is done when:
1. [x] Zero cross-contamination violations (core/, schemas/, PDD modules clean)
2. [x] All tests pass (700 passed)
3. [ ] All CLI commands work
4. [ ] No dead code, orphaned imports, or unused files
5. [ ] Package structure matches this document
6. [ ] CONSOLIDATION_LOG.md documents every change made
7. [ ] All PDD module implementations verified against plans
