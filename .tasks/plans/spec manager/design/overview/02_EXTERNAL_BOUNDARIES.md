# External Boundaries

What goes into and comes out of spec_manager.

---

## Inputs

### Spec Source Files

* **Format**: Markdown prose files (Phase 0 input) or PDD skeleton code files
  (L1 input)
* **Language**: Any language the spec dictates — Python, TypeScript, Rust,
  etc. (language-agnostic by design, currently Python-tested)
* **Structure**: No assumptions about structure. Phase 0 handles unstructured
  prose through LLM-based routing
* **Entry point**: `intake/run_phase0()` for prose; `WorkspaceManager` for PDD
  skeletons
* **Boundary re-entry inputs**: lifecycle owns the boundary gate and evaluates
  these signals before scheduling L1:
  * Intake queue state and change activity from the active run
  * `.pdd_runs/<run_id>/intake/phase0_state.json` checkpoint metadata
  * `system/intent.md` signature (`sha256` + `mtime`) compared to
    `system_intent_signature` in `phase0_state.json`
* **Re-entry contract (explicit)**:
  * If `system_intent_signature` changes, lifecycle sets `status=RERUN_REQUIRED`
    and re-runs Phase 0.
  * If checkpoint metadata is missing or invalid, lifecycle emits
    `status=BLOCKED` with an explicit reason and next-step plan before
    continuing.
  * If no trigger is detected, downstream stages do not rerun Phase 0 and
    consume `libraries/` as authoritative for routing.

### PDD Skeleton Files

* **Format**: Source code files with spec comments and `pass`/stub bodies
* **Content**: Function signatures with doc comments describing requirements
* **Example**: `chaotic_treasury_expanded_pdd/` — 8 Python files, 38
  functions, 52 spec comments
* **Entry point**: `WorkspaceManager.initialize()` ingests as spec_snapshot

### User Constraints

* **Format**: Natural language constraints provided via interactive mode
* **Purpose**: Guide tradeoff decisions when the spec is underspecified
* **Entry point**: `spec-manager intent questions` / `spec-manager intent answer`
  (`IntentAgentOrchestrator`) captures responses and forwards only translated
  answers to planner ingest.
* **Authority model**: Planner owns `ConstraintsStore` and decision writes; intent
  artifacts (`intent/answers.jsonl`, `intent/answer_translations/*.json`) are
  non-authoritative projections.

### Run Configuration

* **Format**: `RunConfig` dataclass
* **Content**: `enable_snapshots`, `enable_quality_scoring`, `max_workers`,
  `model_profile_name`
* **Entry point**: `RunStateManager` initializes from RunConfig

---

## Outputs

### Implementation (Primary Output)

* **What**: Fully implemented code in the clean worktree, ready for main
* **Where**: L3 clean worktree -> merge to main branch
* **Quality**: Passed all compliance gates at L1, L2, L3 + quality reviewers

### Reports

| Report | Generator | Content |
|--------|----------|---------|
| Run scorecard | `RunReporter` | 5 hard gates, 6 soft signals |
| Quality scorecard | `QualityReporter` | Architecture + code + spec quality |
| Final report | `FinalReportGenerator` | Combined summary |
| Planner review | `PlannerReporter` | FAIL/WARN/NeedsReview sections |
| Gap report | `format_gap_report()` | Remaining gaps per file |

### Snapshots

* **What**: Point-in-time capture of run state (files, analysis, scores)
* **Generator**: `snapshot_run()` in `orchestration/snapshot.py`
* **Gated by**: `RunConfig.enable_snapshots`

### Evidence Bundles

* **What**: Per-slice audit trail of decisions, findings, and references
* **Format**: `EvidenceBundle` with `Finding` objects and 18+ `Ref` sub-types
* **Purpose**: Traceability from implementation back to spec

### Coordination Artifacts

* **Signals**: `signals.json` — CoordinationSignals emitted during processing
* **Work items**: JSONL store of cross-slice dependency tracking
* **Wake events**: File-based queue of slice re-evaluation triggers
* **Monitor specs**: JSON DSL definitions for JIT monitors
* **Current answer-boundary streams**: `coordination/user_questions.jsonl`
  and `coordination/planner_updates.jsonl` (`constraint_saved`,
  `decision_recorded`, `problem_redefinition`).
* **Legacy doc drift note**: older boundary text still references
  `signals.json`; implementation evidence points to the run-specific JSONL streams
  above for user-question and planner-update channels.

### Intent skeleton and question boundary artifacts

* `intent/skeleton/analysis/intent/intent_snapshot.json`
* `intent/skeleton/analysis/intent/intent_snapshot.md`
* `intent/skeleton/analysis/intent/question_queue.json` (canonical queue persistence
  path).

### Phase 0 Boundary Outputs

* **Canonical decomposition artifacts**: `libraries/` and coverage artifacts are
  the authoritative Phase 0 output for routing scope in this run.
* **Boundary checkpoint**: `.pdd_runs/<run_id>/intake/phase0_state.json` stores
  trigger reasons, signatures, and run status for replayable re-entry decisions.
* **Boundary contract fields**:
  * `status`: one of `COMPLETED`, `SKIPPED`, `RERUN_REQUIRED`, `BLOCKED`
  * `reentry_required`: boolean
  * `trigger_reasons`: list of canonical reasons (`SYSTEM_INTENT_CHANGED`,
    `INTAKE_CHANGED`, `FORCED_REENTRY`, `VALIDATION_FAILURE`)
  * `system_intent_signature`: signed fingerprint snapshot used for diff checks
  * `input_snapshot_signature`: canonical intake fingerprint persisted each run
  * `updated_at`: ISO timestamp for deterministic replay ordering
* **Cross-boundary rule**: downstream orchestration and planning consume
  `libraries/` as authoritative unless lifecycle has set `status=RERUN_REQUIRED`
  and rehydrated the Phase 0 boundary checkpoint in the same run.

---

## LLM Call Sites

The system uses LLM agents at 30+ call sites across the pipeline. Key agents:

### Phase 0 Intake Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| spec-intake-summarize | GLM | Per-file routing hint summaries |
| spec-intake-discover-libraries | Opus | Library skeleton discovery |
| spec-intake-route | Opus | Source span routing to destinations |
| spec-intake-coverage-filter | GLM | Classify uncovered content as noise vs missed |

### Implementation Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| ImplementationRunner | GLM | Fill function bodies from spec comments |
| Architectural assembler | Opus | Assemble services/events from promoted atoms |
| Clean-code refactorer | Opus | Quality-preserving refactoring |

### Analysis and Review Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| opus-alignment-checker | Opus | POWER alignment (drift detection) |
| opus-overview-writer | Opus | Human review document generation |
| opus-architecture-proposer | Opus | Architecture proposals |
| chatgpt-*-reviewer (4x) | GPT | Code quality review (4 standards) |
| SourceAnalysisCache | LLM | analyze_source() for code understanding |

### Judge Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| ArchitectureQualityJudge | Judge model | Architecture quality scoring |
| CodeQualityJudge | Judge model | Code quality scoring (samples K files) |
| SpecFidelityJudge | Judge model | Spec requirement coverage |
| PairwiseArchJudge | Judge model | A/B architecture comparison |
| PairwiseCodeJudge | Judge model | A/B code quality comparison |

### Planning Agents

| Agent | Model | Purpose |
|-------|-------|---------|
| L1Planner | Opus | Function intentions + triage_signal |
| L2Planner | Opus | Architecture topology + wiring |
| L3Planner | Opus | Quality graph + refactor intentions |
| ResearchCoordinator | Multi-model | Opus + GPT + GLM + firecrawl research |

---

## File I/O Patterns

### Workspace Structure

```text
runs/<run_id>/
    spec_snapshot/          # Immutable input (SHA-256 baseline)
    libraries/              # Phase 0 output (assembled markdown)
    summaries/              # Phase 0 routing hints
    system/                 # System-level constraints
    reports/                # Generated reports
    evidence/               # Evidence bundles
    coordination/           # Signals, work items, monitors
```

### System-Internal Formats

| Format | Used By | Content |
|--------|---------|---------|
| JSON | Schemas, configs, evidence | Structured data with validation |
| JSONL | Route table, coverage ledger, work items | Append-friendly line records |
| Markdown | Spec files, reports, analysis docs | Human-readable documents |
| Python | PDD skeletons (current eval fixture) | Code-as-spec |

---

## Git Integration

All git operations go through `VcsOperations` Protocol (SM-CORE-002):

* **GitVcs**: Current implementation using git
* **WorktreeManager**: Creates dirty/clean/grandchild worktree hierarchy
* **Worktree operations**: `setup()`, `create_library_worktree()`,
  `promote_library()`, `rebase_root_on_clean()`, `cleanup()`
* **Abstraction**: Could be replaced with jj or any other VCS
  ("It could be jj. It could be git. We don't care." — simpler.md)
