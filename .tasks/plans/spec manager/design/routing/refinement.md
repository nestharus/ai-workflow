# Refinement

**Classification**: Business (execution engine)
**Package**: `spec_manager/refinement/`
**Files**: 155 (largest package)
**Role**: Execution engine for spec refinement, implementation, and evaluation. Contains workspace management, evidence indexing, interactive research, and the full evaluation framework.

---

## Systems

### Workspace
**Module**: `workspace/` (manager.py, state.py)
**Purpose**: Workspace state management for spec refinement. Tracks phases (P0-P10), results per phase, folder structure.
**Surface API**:
- `WorkspaceManager(run_id, input_folder)`
- `initialize()`, `get_phase_folder(phase) -> Path`
- `WorkspaceState` — current_phase, phase_results, folder_structure
**Dependencies**: `core.run_folder`
**Consumers**: All orchestration lifecycle components

### Hollowed Spec (Evidence Store)
**Module**: `hollowed_spec/` (extractor.py, indexer.py, searcher.py)
**Purpose**: Evidence store for needle-in-haystack research. Extracts evidence passages from spec, builds searchable index.
**Surface API**:
- `hollow_out_spec(spec_text) -> HollowedSpec`
- `build_evidence_index(spec) -> EvidenceIndex`
- `EvidenceSearcher.search(query, top_k=5) -> list[Evidence]`
**Dependencies**: `core.annotations`, `core.code_analysis`
**Consumers**: `planner.tools.evidence_tool`, interactive steering

### Interactive (Research + Steering)
**Module**: `interactive/` (research/, steering/)
**Purpose**: Interactive spec refinement with ambiguity detection and steering.
**Surface API**:
- `ResearchCoordinator.run_research(query, context) -> ResearchResult`
- `SteeringEngine.apply_steering_decision(signal, decision)`
**Dependencies**: `refinement.hollowed_spec`, `orchestration.coordination.signals`
**Consumers**: `planner.tools.research_tool`, `orchestration.pdd_lifecycle`

### Formats
**Module**: `formats.py`
**Purpose**: Text processing utilities for LLM output.
**Surface API**:
- `_strip_code_fences(text) -> str`
- `_fix_single_quote_json(text) -> str`
**Dependencies**: None
**Consumers**: Multiple refinement modules, orchestration

### Evals (Evaluation Framework)
**Module**: `evals/` (inputs/, judges/, planner/, phase_evals/, baselines/)
**Purpose**: Deterministic evaluation framework. Sequence specs with ground truth, metrics, judge infrastructure.

**Sub-systems**:

**Judges** (`evals/judges/`):
- `JudgeClient` — run_agent → parse → validate
- `JudgeCache` — disk-backed caching by `JudgeCacheKey`
- `ArchitectureQualityJudge` — architecture quality scoring
- `CodeQualityJudge` — samples K files for code quality
- `SpecFidelityJudge` — spec fidelity scoring
- `PairwiseArchJudge`, `PairwiseCodeJudge` — pairwise comparison

**Planner Eval** (`evals/planner/`):
- `GroundTruth` — 10 dataclasses, YAML/JSON load/save
- `TraceLoader` — TraceEntry, LoadedTrace, filter, stats
- 4 capability scorers + base
- `PlannerReporter` — 5 hard gates, 12 soft signals
- `PlannerEvalHarness` — e2e/slice/replay modes
- `GroundTruthExporter`

**Inputs** (`evals/inputs/`):
- Fixture management and ground truth loading
- 5 artifact types: manifest, source, ground truth, Phase 0 output, PDD skeletons

**Dependencies**: `core.agent_utils`, `schemas` (judge schemas)
**Consumers**: `orchestration.quality_scoring`, `orchestration.comparison`, CLI

### Core Refinement Modules
**Modules**: Various modules in `refinement/core/`, `refinement/evaluation/`, `refinement/workflows/`
**Purpose**: Phase-specific refinement logic, evaluation orchestration, workflow management.
**Dependencies**: `core`, `schemas`, `compliance`
**Consumers**: `orchestration.pdd_orchestrator`
