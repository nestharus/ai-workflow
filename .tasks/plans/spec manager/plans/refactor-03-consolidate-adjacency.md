# Implementation Plan

## Overview

Consolidate the duplicate adjacency graph implementations by removing `analysis/adjacency_builder.py` (the simpler, legacy module) and rewiring its sole consumer (`analysis/generator.py`) to use the comprehensive `analysis/adjacency/` submodule. This also requires a thin adapter to bridge the `AdjacencyGraph` output from `adjacency/` into the `AtomAdjacency` Pydantic model consumed by the generator's `AnalysisFileSchema`.

## Current State (Problems)

Two independent implementations exist for building adjacency graphs:

### `analysis/adjacency_builder.py` (legacy, 117 lines)

| Aspect | Detail |
|---|---|
| **File** | `scripts/spec_manager/spec_manager/analysis/adjacency_builder.py` |
| **Functions** | `build_co_occurrence_edges()`, `build_store_touch_edges()`, `build_adjacency_graph()` |
| **Input format** | `atom_to_section: dict[str, dict[str, str]]` (atom_id -> {section_id, file_id, sha256}), `atom_registry: dict[str, dict[str, Any]]`, `store_definitions: dict[str, list[str]]` |
| **Output format** | `dict[str, AtomAdjacency]` -- flat Pydantic model with `co_occurrence_edges: list[str]` and `store_touch_edges: list[str]` |
| **Co-occurrence logic** | Inverts `atom_to_section` to `section_id -> [atom_ids]`, builds pairwise edges for atoms sharing a section. Section identity comes from pre-built trace indexes. |
| **Store-touch logic** | Takes `store_definitions: dict[store_id, list[atom_id]]`, builds pairwise edges for atoms sharing a store. Filters atoms not in `atom_registry`. |
| **Consumers** | `analysis/generator.py` line 16, line 89-93 |
| **Tests** | `tests/spec_manager/analysis/test_adjacency_builder.py` (3 test classes, 7 test methods) |
| **Edge type** | Unweighted string lists (just atom_id neighbors) |

### `analysis/adjacency/` submodule (comprehensive, ~900+ lines across 7 source files)

| Aspect | Detail |
|---|---|
| **Package** | `scripts/spec_manager/spec_manager/analysis/adjacency/` |
| **Core graph** | `graph.py` -- `AdjacencyGraph` class with weighted, signal-typed edges (`EdgeSignal`, `SignalType`, `NodeInfo`), serialization, connected components, subgraph, union, filter |
| **Extractors** | 4 extractors in `extractors/`: `call_graph.py` (AST call analysis), `event_graph.py` (pub/sub detection), `store_graph.py` (AST store-touch detection), `cooccurrence.py` (spec annotation co-occurrence) |
| **Detector** | `detector.py` -- `build_unified_graph()`, `detect_disconnected_components()`, isolation classification |
| **Runner** | `runner.py` -- `run_adjacency_analysis()` end-to-end pipeline with `AdjacencyAnalysisConfig` |
| **Consumers** | `analysis/__init__.py` (lines 17-18), `cli.py` (line 955) |
| **Tests** | 6 test files in `adjacency/tests/` covering graph, call_graph, event_graph, store_graph, cooccurrence, detector, runner |
| **Edge type** | Weighted `EdgeSignal` with `SignalType` enum, details dict, total_weight computation |

### Functional comparison

| Capability | `adjacency_builder.py` | `adjacency/` submodule |
|---|---|---|
| Co-occurrence from pre-built atom_to_section index | Yes (simple dict inversion) | No -- uses spec markdown parsing via `AnnotationParser`/`SectionExtractor` |
| Co-occurrence from spec annotations | No | Yes (`extractors/cooccurrence.py`) |
| Store-touch from pre-built store_definitions dict | Yes (simple pairwise) | No -- uses AST analysis of Python source files |
| Store-touch from AST analysis | No | Yes (`extractors/store_graph.py`) |
| Call graph | No | Yes (`extractors/call_graph.py`) |
| Event graph | No | Yes (`extractors/event_graph.py`) |
| Weighted edges | No (unweighted string lists) | Yes (`EdgeSignal` with configurable weights) |
| Disconnected component detection | No | Yes (`detector.py`) |
| Graph union/filter/subgraph | No | Yes (`AdjacencyGraph` class methods) |
| Output to `AtomAdjacency` Pydantic model | Yes (direct) | No -- outputs `AdjacencyGraph` dataclass |

### Key gap

The `adjacency/` submodule does **not** accept the pre-built dict inputs (`atom_to_section`, `store_definitions`) that `adjacency_builder.py` consumes. Its extractors work from raw source files and spec markdown. The `generator.py` workflow provides these dicts from upstream pipeline stages (import scanner, trace indexing) and does not have raw file paths at that point.

Therefore, `adjacency/` needs two thin adapter functions that accept the same dict inputs as `adjacency_builder.py` and return `AdjacencyGraph` objects with the appropriate `SignalType` edges.

## Target State

- `adjacency_builder.py` is deleted
- `generator.py` imports from `analysis.adjacency` instead
- Two thin adapter functions exist in `adjacency/` to convert pre-built dicts into `AdjacencyGraph` objects
- A conversion function produces `dict[str, AtomAdjacency]` from an `AdjacencyGraph` for `AnalysisFileSchema` compatibility
- All existing tests pass; legacy tests are migrated or replaced
- No other files in the codebase import from `adjacency_builder`

## Additional Info

- The `AtomAdjacency` Pydantic model in `schemas/lineage.py` (lines 35-46) is a simple flat model: `atom_id`, `co_occurrence_edges: list[str]`, `store_touch_edges: list[str]`. It is used by `AtomAnalysisEntry.adjacency` (line 80) and must remain unchanged for backward compatibility.
- `generator.py` calls `build_adjacency_graph(atom_to_section or {}, atom_registry, store_definitions)` at line 89-93 and uses the resulting `dict[str, AtomAdjacency]` at line 114.
- The `adjacency/` submodule is already exposed via `analysis/__init__.py` (lines 17-18) with `AdjacencyReport` and `run_adjacency_analysis`.
- The CLI at `cli.py:955` uses `adjacency.runner.run_adjacency_analysis` (the comprehensive pipeline), so it is unaffected.

## Plans

### Plan 1: Add dict-based adapter functions to `adjacency/`

Add a new file `scripts/spec_manager/spec_manager/analysis/adjacency/adapters.py` with two functions that accept the legacy dict inputs and return `AdjacencyGraph` objects:

1. **`cooccurrence_from_atom_sections(atom_to_section: dict[str, dict[str, str]]) -> AdjacencyGraph`**
   - Replicates the logic of `adjacency_builder.build_co_occurrence_edges()` but outputs an `AdjacencyGraph` with `SignalType.CO_OCCURRENCE` edges.
   - Inverts `atom_to_section` to `section_id -> [atom_ids]`, creates pairwise edges with `EdgeSignal(signal_type=SignalType.CO_OCCURRENCE, weight=0.3)`.
   - Adds `NodeInfo` for each atom (node_type="algorithm").

2. **`store_touch_from_definitions(atom_registry: dict[str, dict[str, Any]], store_definitions: dict[str, list[str]]) -> AdjacencyGraph`**
   - Replicates the logic of `adjacency_builder.build_store_touch_edges()` but outputs an `AdjacencyGraph` with `SignalType.STORE_TOUCH` edges.
   - Iterates `store_definitions`, filters atoms not in `atom_registry`, creates pairwise edges with `EdgeSignal(signal_type=SignalType.STORE_TOUCH, weight=0.5)`.
   - Adds `NodeInfo` for each atom (node_type="algorithm", file_path from registry).

3. **`graph_to_atom_adjacency(graph: AdjacencyGraph, all_atom_ids: set[str]) -> dict[str, AtomAdjacency]`**
   - Converts an `AdjacencyGraph` into `dict[str, AtomAdjacency]` for `AnalysisFileSchema` compatibility.
   - For each atom_id, collects neighbors by signal type: `CO_OCCURRENCE` -> `co_occurrence_edges`, `STORE_TOUCH` -> `store_touch_edges`.
   - Returns sorted edge lists to match legacy behavior.

4. Export new functions from `adjacency/__init__.py`.

**Files changed:**
- New: `scripts/spec_manager/spec_manager/analysis/adjacency/adapters.py`
- Edit: `scripts/spec_manager/spec_manager/analysis/adjacency/__init__.py` (add exports)

### Plan 2: Rewire `generator.py` and delete `adjacency_builder.py`

1. **Update `generator.py` imports** (line 16):
   - Remove: `from spec_manager.analysis.adjacency_builder import build_adjacency_graph`
   - Add: `from spec_manager.analysis.adjacency.adapters import cooccurrence_from_atom_sections, store_touch_from_definitions, graph_to_atom_adjacency`
   - Add: `from spec_manager.analysis.adjacency.detector import build_unified_graph`

2. **Update `generator.py` step 5** (lines 88-93):
   Replace the single `build_adjacency_graph()` call with:
   ```python
   # 5. Build adjacency graph.
   cooccurrence_graph = cooccurrence_from_atom_sections(atom_to_section or {})
   store_graph = (
       store_touch_from_definitions(atom_registry, store_definitions)
       if store_definitions
       else None
   )
   unified = build_unified_graph(
       cooccurrence_graph=cooccurrence_graph,
       store_graph=store_graph,
   )
   all_atom_ids = set(atom_to_section.keys()) | set(atom_registry.keys()) if atom_to_section else set(atom_registry.keys())
   adjacency_map = graph_to_atom_adjacency(unified, all_atom_ids)
   ```

3. **Delete `adjacency_builder.py`**:
   - Remove `scripts/spec_manager/spec_manager/analysis/adjacency_builder.py`

4. **Verify no other imports remain** by running grep to confirm no references to `adjacency_builder` in production code.

**Files changed:**
- Edit: `scripts/spec_manager/spec_manager/analysis/generator.py`
- Delete: `scripts/spec_manager/spec_manager/analysis/adjacency_builder.py`

### Plan 3: Migrate tests

1. **Add tests for adapters** in a new file `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_adapters.py`:
   - Port all 7 test methods from `test_adjacency_builder.py`, adapted to use the new adapter functions.
   - `TestCooccurrenceFromAtomSections`: test grouping, single-atom sections, empty input, three atoms (verify `AdjacencyGraph` edges with `SignalType.CO_OCCURRENCE`).
   - `TestStoreTouchFromDefinitions`: test shared access, unknown atoms ignored, empty definitions (verify `AdjacencyGraph` edges with `SignalType.STORE_TOUCH`).
   - `TestGraphToAtomAdjacency`: test conversion produces correct `AtomAdjacency` instances with both edge types, no duplicates, empty graph.

2. **Delete legacy test file**:
   - Remove `scripts/spec_manager/tests/spec_manager/analysis/test_adjacency_builder.py`

3. **Verify existing adjacency/ tests still pass** -- no changes expected since we are only adding, not modifying existing extractor code.

**Files changed:**
- New: `scripts/spec_manager/spec_manager/analysis/adjacency/tests/test_adapters.py`
- Delete: `scripts/spec_manager/tests/spec_manager/analysis/test_adjacency_builder.py`

## Execution Instructions

Execute plans sequentially: Plan 1, then Plan 2, then Plan 3. Each plan should be verified before proceeding.

After Plan 1:
```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
uv run python -c "from spec_manager.analysis.adjacency.adapters import cooccurrence_from_atom_sections, store_touch_from_definitions, graph_to_atom_adjacency; print('imports OK')"
```

After Plan 2:
```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
uv run python -c "from spec_manager.analysis.generator import generate_analysis_file; print('generator imports OK')"
# Verify no remaining references:
grep -rn "adjacency_builder" /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/ --include="*.py"
# Should return nothing
```

After Plan 3:
```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
# Run all adjacency tests
uv run pytest spec_manager/analysis/adjacency/tests/ -v -p no:randomly
# Run generator tests (if they exist)
uv run pytest tests/spec_manager/analysis/ -v -p no:randomly
# Confirm deleted test file is gone
test ! -f tests/spec_manager/analysis/test_adjacency_builder.py && echo "DELETED OK"
# Full test suite
uv run pytest -x -p no:randomly
```

## Success Criteria

1. `adjacency_builder.py` no longer exists in the repository
2. `test_adjacency_builder.py` no longer exists in the repository
3. `grep -rn "adjacency_builder" scripts/ --include="*.py"` returns zero matches
4. `generator.py` imports only from `analysis.adjacency` (no import of `adjacency_builder`)
5. All adapter tests pass: `uv run pytest spec_manager/analysis/adjacency/tests/test_adapters.py -v`
6. All existing adjacency submodule tests pass unchanged: `uv run pytest spec_manager/analysis/adjacency/tests/ -v`
7. Generator integration tests pass (if present): `uv run pytest tests/spec_manager/analysis/ -v`
8. Full test suite passes: `uv run pytest -x -p no:randomly`
9. The `AtomAdjacency` Pydantic model in `schemas/lineage.py` is unchanged
10. The `graph_to_atom_adjacency()` adapter produces output identical to the old `build_adjacency_graph()` for the same inputs (same atom_ids, same sorted edge lists)
