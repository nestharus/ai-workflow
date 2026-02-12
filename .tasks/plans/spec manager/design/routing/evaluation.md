# Evaluation

**Classification**: Business (quality assessment)
**Package**: `spec_manager/evaluation/`
**Files**: 9
**Role**: Quality scoring, model comparison, and reporting.

---

## Systems

### Mechanical Scoring
**Module**: `scoring.py`
**Purpose**: Hard gates + soft signals for pipeline quality.
**Surface API**:
- `RunReporter.score(bundle) -> Scorecard`
**Dependencies**: `compliance.promotion`, `orchestration.evidence`
**Consumers**: `orchestration.pdd_lifecycle`

### Quality Scoring
**Module**: `quality.py`
**Purpose**: LLM judge-based quality assessment (mechanical + judge blend).
**Surface API**:
- `QualityReporter.score(bundle) -> QualityScorecard`
**Dependencies**: `refinement.evals.judges`, `evaluation.digests`
**Consumers**: `orchestration.pdd_lifecycle`, `evaluation.multi_model`

### Digests
**Module**: `digests.py`
**Purpose**: Architecture and code summaries for judges.
**Surface API**:
- `build_architecture_digest()`, `build_code_digest()`
**Dependencies**: `refinement.workspace`
**Consumers**: `evaluation.quality`, `evaluation.multi_model`, CLI

### Report Generation
**Module**: `report.py`
**Purpose**: End-of-run report generation.
**Surface API**:
- `FinalReportGenerator.generate() -> Report`
**Dependencies**: `evaluation.scoring`, `orchestration.evidence`
**Consumers**: `orchestration.pdd_lifecycle`

### Multi-Model Runner
**Module**: `multi_model.py`
**Purpose**: Parallel runs across different model profiles.
**Surface API**:
- `MultiModelRunner.run(profiles) -> list[RunResult]`
**Dependencies**: `evaluation.model_profile`, `evaluation.quality`, `evaluation.snapshot`
**Consumers**: CLI (`compare` command)

### Comparison
**Module**: `comparison.py`
**Purpose**: Canonical alignment + pairwise comparison of runs.
**Surface API**:
- `ComparisonRunner.compare(results) -> ComparisonReport`
**Dependencies**: `evaluation.multi_model`
**Consumers**: CLI (`compare` command)

### Model Profile
**Module**: `model_profile.py`
**Purpose**: Role-based model routing (different models for different tasks).
**Surface API**:
- `ModelProfile` dataclass
**Dependencies**: None
**Consumers**: `evaluation.multi_model`, `orchestration.run_state`

### Cost Ledger
**Module**: `cost_ledger.py`
**Purpose**: LLM call cost tracking.
**Surface API**:
- `CostLedger` + `LLMCallRecord`
**Dependencies**: None
**Consumers**: `evaluation.multi_model`

### Snapshot
**Module**: `snapshot.py`
**Purpose**: Run artifact preservation.
**Surface API**:
- `snapshot_run()`
**Dependencies**: `refinement.workspace`
**Consumers**: `orchestration.pdd_lifecycle`, `evaluation.multi_model`
