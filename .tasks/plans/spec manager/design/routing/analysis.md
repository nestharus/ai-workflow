# Analysis

**Classification**: Business (adjacency + restructuring)
**Package**: `spec_manager/analysis/`
**Files**: 9
**Role**: Adjacency detection for algorithmic dependencies and library restructuring suggestions.

---

## Systems

### Adjacency
**Module**: `adjacency/` (graph.py, detector.py, adapters.py, extractors/, runner.py)
**Purpose**: Constructs unified dependency graph (call + event + store-touch + co-occurrence) to reveal missed dependencies between atoms.
**Surface API**:
- `AdjacencyGraph.build(atoms) -> Graph`
- `detect_disconnected_components(graph) -> ComponentReport`
- `run_adjacency_analysis(config) -> AdjacencyReport`
- `cooccurrence_from_atom_sections()`, `store_touch_from_definitions()`, `graph_to_atom_adjacency()`
**Dependencies**: `discovery.cooccurrence`, `core.code_analysis`
**Consumers**: `analysis.generator`, `refinement_engine.detector`

### Generator & Operations
**Modules**: `generator.py`, `operations.py`, `report_renderer.py`, `resolver.py`
**Purpose**: Detects library restructuring patterns (divergence, convergence), generates structured analysis artifacts.
**Surface API**:
- `generate_analysis_file(bundle) -> Path`
- `run_analysis(libraries) -> AnalysisReport`
- `detect_divergence()`, `detect_convergence()`, `analyze_references()`
- `suggest_restructuring()`
- `read_analysis_json()`, `write_analysis_json()`
**Dependencies**: `analysis.adjacency`, `schemas.architecture`
**Consumers**: `orchestration.promotion_loop.AnalyzeStep`, `orchestration.architecture`
