# Core

**Classification**: Utility (shared primitives)
**Package**: `spec_manager/core/`
**Files**: 25+
**Role**: Shared foundational utilities. LLM invocation, source code analysis, gap data structures, ID generation, registries, file I/O. Depended on by 12 packages.

---

## Key Modules

### Agent Utils
**Module**: `agent_utils.py`
**Purpose**: LLM invocation wrapper. All LLM calls go through here.
**Surface API**:
- `run_agent(prompt, model_id) -> AgentOutput`

### Code Analysis
**Module**: `code_analysis.py`
**Purpose**: Source code analysis (functions, comments). Language-agnostic via LLM.
**Surface API**:
- `analyze_source(content, filepath) -> SourceAnalysis`
- `SourceAnalysis.functions: list[RawFunctionInfo]`
- `SourceAnalysis.comments: list[RawCommentInfo]`
**Note**: Test double `_local_python_analyzer` injected via root conftest.py.

### Gap Structures
**Modules**: `gap.py`, `gap_queue.py`
**Purpose**: Gap data structures and priority queue.
**Surface API**:
- `Gap`, `GapType`, `GapEvidence`, `GapSynthesizer`
- `GapQueue` — priority queue for gaps

### IDs & Registries
**Modules**: `ids.py`, `library_registry.py`, `pin_registry.py`
**Purpose**: ID generation, library index, pin lookup.
**Surface API**:
- `EntityId`, `PinId`, etc.
- `LibraryRegistry` — PDD library index
- `PinRegistryIndex` — O(1) lookups by name, ID, pin_func_id, arch_location
- `PinRegistryIndex.get_importers()`, `.get_pin_functions_for_arch()`, `.resolve_micro_address()`, `.get_affected_locations()`

### JSON Extraction
**Module**: `json_extraction.py`
**Purpose**: Robust JSON extraction from LLM output.
**Surface API**:
- `_extract_json_payload(text) -> dict | list`

### Sections
**Module**: `sections.py`
**Purpose**: Section parsing from spec documents.
**Surface API**:
- Section parsing utilities

### Run Folder
**Module**: `run_folder.py`
**Purpose**: Run directory management.

### Annotations
**Module**: `annotations.py`
**Purpose**: Spec annotation parsing (element IDs like `[=CON-LIB-001]`).

### Data Structures
**Module**: `data_structures.py`
**Purpose**: Common data structures shared across packages.

---

## Consumers

Used by ALL packages: orchestration, planner, refinement, compliance, projection, analysis, branches, strategies, planning, schemas, pin_functions, intake, labyrinth.
