# TODO Tracker: PDD Workflow Alignment

Second-class document. The TODO comments in code are the plan.
This file logs WHERE each TODO is and WHY, for reassessment.

Reference: `.tasks/plans/spec manager/WORKFLOW_ANALYSIS.md`

---

## pdd_lifecycle.py — Top-level lifecycle orchestration

| Location | TODO Summary | Reason |
|----------|-------------|--------|
| `run()` | Restructure as per-slice iterative loop | Currently sequential Build→QA→Arch→Quality. Should be iterative per-slice with CI. QA/arch/quality are processes that run at EVERY promotion, not separate phases. |
| `build()` step 5 | Move worktree creation before implementation | Worktrees created after all phases complete. simpler.md says worktrees are where implementation HAPPENS — must exist before P9. |
| `build()` step 1 | Don't run full 11-phase pipeline as single pass | `orchestrator.run()` runs P0-P10 sequentially. Promotion 2 should be iterative: P3→P8→P9→tests→P4→P5→gates→CI per slice. |
| `_refine_libraries()` | Inline during implementation, not batch after | Ambiguity resolution should trigger when under-specification is HIT, not as a batch post-processing step. |
| `qa()` | Integrate into promotion loop | QA is a process at every promotion, not a separate lifecycle phase. Run as part of compliance gating. |
| `architecture()` | Integrate into L1→L2 promotion | Architecture emerges from promotion. Proposals should come from pin-function scan + atom promotion, not a separate phase. |
| `code_quality()` | Integrate as Promotion 3 (L2→L3) | Quality review IS Promotion 3. Should trigger demotion if logic issues found. |

## pdd_orchestrator.py — Phase execution engine

| Location | TODO Summary | Reason |
|----------|-------------|--------|
| `run()` | Support iterative per-slice mode | Single sequential pass through P0-P10. Should support: run P0 once (Promotion 1), then loop P3→P8→P9→P4→P5 per slice (Promotion 2). |
| `_run_compliance_clean()` | ~~Use TODO markers specifically for gaps~~ DONE | Implemented state-aware gap detection in `edit_in_place.py`. SPEC comments in implemented functions are NOT gaps. Only TODO markers and SPEC in stubs count as gaps. |
| `_run_implementation()` | ~~Actually write code~~ DONE | P9 now calls LLM agent (pdd-function-implementor) for each UNRESOLVED function, applies implementations via AST-based body replacement. 38/38 functions implemented in QA, 0 errors, all files parse. |
| `_run_extraction()` | Library quality validator after Promotion 1 | After P0 produces libraries, check spec-level overlap/isolation/completeness. Post-Promotion-1 gate before Promotion 2 begins. |
| `_run_spec_build()` | Wire demotion on gate failure | Promotion runs but if compliance gates fail, nothing happens. Should trigger demotion: trace back through pins, fix at L1, re-promote. |
| `_run_spec_build()` | Architectural implementation agent | After atoms promoted via pins, generate actual architectural code (services/events/middleware) from pin projections. Enforce NO_INLINED_ATOM_LOGIC gate. |
| `_run_task_planning()` | Wire under-specification → constraints flow | P8 produces plans but doesn't block on under-specification. Should check constraints, block if insufficient, source from human/research team. |
| `_run_task_planning()` | Layer 1 routing for incoming changes | Route new requirements/decisions/demoted algorithms to right library+function using vertical slice summaries. Same pattern as Phase 0. |
| Between P9 and P4 | Add small test generation step | simpler.md step 4: "write small tests to validate small units of work." No test generation exists. |

## branches/promotion.py — L1→L2 bridge

| Location | TODO Summary | Reason |
|----------|-------------|--------|
| `_project_atom()` | Smart projection routing | Always uses PASS_THROUGH. Should use atom metadata to select appropriate ProjectionType (EVENT_BRIDGE, MIDDLEWARE_WRAP, etc.). |
| `promote()` | Demotion on compliance failure | Returns skipped_atoms but doesn't trigger demotion. Should initiate DownwardFlowEngine trace to fix atoms at L1. |

---

## Language-Agnostic Violations (simpler.md lines 7-11)

**Root cause**: 31 files use Python-specific parsing (ast, tokenize, `#` comment delimiter,
`.py` filtering, `pass`/`NotImplementedError` stub patterns) violating the core constraint:
_"You cannot rely on anything hardcoding, word recognition, header recognition, or any other
kind of specific pattern recognition."_

**Allowed**: Regex for system-defined annotations (e.g. `TODO:` label content, markdown `##` headers).
**Not allowed**: `#` as comment delimiter, `ast.parse()`, `tokenize`, `.py` extension, Python stub patterns.

### Category 1: AST/tokenize usage (CRITICAL — 27 files)

| File | Violations | Required Fix |
|------|-----------|-------------|
| `core/edit_in_place.py` | ast, tokenize, `#` stripping, stub detection | LLM-based comment extraction, structure analysis, stub detection |
| `compliance/detection/comment_scanner.py` | ast, tokenize, `#` stripping, `#!` shebang | LLM-based comment extraction |
| `compliance/detection/stub_scanner.py` | ast, `pass`/`Ellipsis`/`NotImplementedError` | LLM-based stub detection |
| `compliance/detection/coverage_analyzer.py` | ast, `#` comment detection | LLM-based coverage analysis |
| `compliance/detection/call_graph.py` | ast, `.py` filtering | LLM-based call analysis |
| `planning/code_parser.py` | ast, tokenize, `#` comments, stub patterns | LLM-based code parsing |
| `planning/reverser.py` | ast, `#` comment detection | LLM-based reverse engineering |
| `branches/collapse.py` | ast | LLM-based branch collapse |
| `branches/gap_detection.py` | ast, stub pattern strings | LLM-based gap detection |
| `compliance/promotion/pin_coverage.py` | ast, `#` comment detection | LLM-based pin coverage |
| `compliance/promotion/introduction_checker.py` | ast, `#` stripping | LLM-based introduction checking |
| `compliance/promotion/architectural_quality.py` | ast, `#` skipping | LLM-based quality analysis |
| `compliance/promotion/algorithmic_gates.py` | ast, `#` comments, stub patterns | LLM-based algorithmic gates |
| `analysis/ast_extractor.py` | ast, `#` comments, `def ` detection | LLM-based code extraction |
| `analysis/import_graph.py` | ast | LLM-based import analysis |
| `analysis/import_scanner.py` | ast | LLM-based import detection |
| `analysis/data_flow.py` | ast | LLM-based data flow analysis |
| `analysis/projection_classifier.py` | ast | LLM-based projection classification |
| `analysis/adjacency/extractors/call_graph.py` | ast | LLM-based call extraction |
| `analysis/adjacency/extractors/event_graph.py` | ast | LLM-based event extraction |
| `analysis/adjacency/extractors/store_graph.py` | ast | LLM-based store extraction |
| `projection/lineage/import_graph.py` | ast | LLM-based dependency analysis |
| `projection/lineage/builder.py` | ast | LLM-based lineage building |
| `projection/lineage/test_pin_discovery.py` | ast | LLM-based test pin discovery |
| `projection/lineage/test_pin_baseline.py` | ast | LLM-based test pin baseline |

### Category 2: Non-AST language-specific patterns (6 files)

| File | Violations | Required Fix |
|------|-----------|-------------|
| `core/gaps.py` | `#` comment detection | LLM-based comment extraction |
| `strategies/implementations/stub_promotion.py` | `#` comment, `NotImplementedError` regex | LLM-based stub detection |
| `compliance/hardcoding_scanner.py` | `#` comment detection | LLM-based comment extraction |
| `compliance/detection/runtime_detector.py` | `.py` filtering, `NotImplementedError` | Language-agnostic runtime detection |
| `planning/gap_bridge.py` | `#`, `pass`, `def `, `NotImplementedError` | LLM-based gap bridging |
| `orchestration/pdd_orchestrator.py` | `.py` filtering, import detection, body replacement | LLM-based code manipulation |

---

## Assessment Notes

**Biggest gap**: ~~P9 doesn't write code.~~ DONE — P9 implemented. BUT implementation uses
AST-based body replacement (language-specific). Needs LLM-based code manipulation.

**Second biggest**: The lifecycle is sequential (Build→QA→Arch→Quality) but should
be an iterative per-slice loop where these are processes at each promotion, not phases.

**Third**: Under-specification → planning → constraints blocking flow is not wired.
Planning module exists but doesn't block and source constraints.

**Fourth (NEW)**: 31 files use Python-specific parsing violating simpler.md's core constraint.
All must be replaced with LLM-based analysis for language-agnostic operation.
