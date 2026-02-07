# Implementation Plan: Hollowed-Out Spec Evidence Store

## Overview

Build a system that hollow-outs complete specifications into a searchable evidence store, enabling agents to perform needle-in-haystack research when they encounter ambiguities during translation, and to flag genuine spec gaps when no answer is found.

## Current State (Problems)

1. **No spec-aware evidence store.** The current evidence system (`evidence_expansion.py`, `evidence_builder.py`) maps library charters to file sections via LLM agents. It does not index or search the full text of complete specs. When a spec is "complete," its detailed content is not reusable as evidence for future ambiguity resolution.

2. **Research is web-only.** The `ResearchCoordinator` in `interactive/research/coordinator.py` resolves ambiguities exclusively via web search (Firecrawl). It has no mechanism to search within existing spec artifacts. This means agents cannot answer questions using knowledge already captured in the project's own specifications.

3. **Adjacent detail discovery is manual.** Section 8 of the design document describes using call graph + store touch analysis to proactively surface related evidence. No such proactive mechanism exists. The current `spotcheck_evidence` function in `evidence_expansion.py` is a reactive audit, not a proactive discovery system.

4. **Ambiguity-to-spec feedback loop is missing.** When an ambiguity cannot be resolved, there is no structured path to flag it as a genuine spec gap requiring expansion. The `AmbiguityDetector` and `AutoResponder` do not integrate with the gap queue (`GapQueue`) used by spec building.

## Target State

1. A **hollow-out pipeline** that extracts a structured skeleton (sections, entities, keywords) from any complete `spec.md`, storing the full text as searchable paragraphs.

2. A **searchable evidence index** over hollowed-out specs that supports keyword, entity, and section-heading queries with ranked results.

3. An **ambiguity research path** that queries the evidence store before (or instead of) web search, producing `SteeringResponse` objects compatible with the existing interactive workflow.

4. An **expansion trigger** that creates `Gap` entries in the `GapQueue` when evidence-store research fails, marking them as genuine spec gaps requiring human/agent expansion.

5. A **proactive adjacency scanner** that uses call graph and store-touch signals to pre-fetch related evidence from the store when translation begins on a new section.

## Additional Info

- The evidence store is intentionally **not embedding-based**. Embeddings require a vector database dependency and introduce non-deterministic retrieval. The design uses structured keyword + entity indexing that is deterministic, testable, and inspectable.
- The hollow-out process runs as a **post-completion hook** after `spec_building` or `spec_stabilization` completes for a library. It does not block spec building.
- The evidence index is a JSON artifact per workspace, regenerated on demand. It is a computed artifact (like the analysis file in Section 13 of the design doc), never manually maintained.
- All new modules live under `scripts/spec_manager/spec_manager/refinement/` to stay consistent with the existing package structure.
- Pydantic models are used for all new data structures, consistent with the existing `schemas/` package.

## Plans

### Plan 1: Hollow-Out Data Structures and Pipeline

**Goal:** Define the data model for hollowed-out specs and implement the extraction pipeline that converts a complete `spec.md` into a structured, indexable skeleton.

#### Files to Create

**`scripts/spec_manager/spec_manager/schemas/hollowed_spec.py`**

```python
"""Schemas for hollowed-out spec evidence store."""

from __future__ import annotations

import re
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class ParagraphKind(str, Enum):
    """Classification of a paragraph within a spec section."""
    PROSE = "PROSE"           # Narrative description
    BULLET_LIST = "BULLET_LIST"  # Bulleted requirements/items
    CODE_BLOCK = "CODE_BLOCK"    # Code or pseudocode
    TABLE = "TABLE"              # Tabular data
    HEADING = "HEADING"          # Section heading text


class HollowedParagraph(BaseModel):
    """A single searchable paragraph from a hollowed-out spec.

    Attributes:
        paragraph_id: Unique ID (HPARA-{lib_id}-{ordinal:04d})
        section_path: Dot-separated section hierarchy (e.g. "Details.Authentication")
        kind: Classification of content type
        text: Full text of the paragraph
        keywords: Extracted keywords for search
        entity_refs: Entity IDs referenced in this paragraph
        line_start: Start line in the original spec.md
        line_end: End line in the original spec.md
    """
    paragraph_id: str
    section_path: str
    kind: ParagraphKind
    text: str
    keywords: list[str] = Field(default_factory=list)
    entity_refs: list[str] = Field(default_factory=list)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)


class HollowedSection(BaseModel):
    """A section skeleton from the hollowed-out spec.

    Attributes:
        section_id: Section identifier
        heading: Section heading text
        level: Heading level (1-6)
        summary: One-sentence summary of the section
        paragraph_ids: IDs of paragraphs in this section
        child_section_ids: IDs of nested subsections
    """
    section_id: str
    heading: str
    level: int = Field(ge=1, le=6)
    summary: str = ""
    paragraph_ids: list[str] = Field(default_factory=list)
    child_section_ids: list[str] = Field(default_factory=list)


class HollowedSpec(BaseModel):
    """A hollowed-out complete spec with searchable evidence.

    Attributes:
        schema_version: Schema version
        lib_id: Library ID this spec belongs to
        spec_hash: SHA-256 of the original spec.md content
        hollowed_at: ISO8601 timestamp
        sections: Ordered list of section skeletons
        paragraphs: All paragraphs indexed by paragraph_id
        entity_index: Mapping of entity name -> list of paragraph_ids
        keyword_index: Mapping of keyword -> list of paragraph_ids
    """
    schema_version: str = "1.0"
    lib_id: str
    spec_hash: str
    hollowed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    sections: list[HollowedSection] = Field(default_factory=list)
    paragraphs: dict[str, HollowedParagraph] = Field(default_factory=dict)
    entity_index: dict[str, list[str]] = Field(default_factory=dict)
    keyword_index: dict[str, list[str]] = Field(default_factory=dict)
```

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/__init__.py`**

```python
"""Hollowed-out spec evidence store for needle-in-haystack research."""

from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.hollowed_spec.indexer import build_evidence_index
from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher
```

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/extractor.py`**

```python
"""Extract hollowed-out structure from a complete spec.md."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from spec_manager.schemas.hollowed_spec import (
    HollowedParagraph,
    HollowedSection,
    HollowedSpec,
    ParagraphKind,
)


def hollow_out_spec(lib_id: str, spec_content: str) -> HollowedSpec:
    """Parse a complete spec.md into a HollowedSpec with sections and paragraphs.

    Args:
        lib_id: Library ID (e.g. "LIB-0001")
        spec_content: Full text of the spec.md file

    Returns:
        HollowedSpec with populated sections, paragraphs, and indexes
    """
    ...


def _parse_sections(content: str) -> list[dict[str, Any]]:
    """Parse markdown headings into a section hierarchy."""
    ...


def _classify_paragraph(text: str) -> ParagraphKind:
    """Classify a text block by its structural type."""
    ...


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a paragraph.

    Uses a stop-word filter and extracts multi-word noun phrases
    that appear in technical specification contexts.
    """
    ...


def _extract_entity_refs(text: str) -> list[str]:
    """Extract entity references (ENT-####) from paragraph text."""
    ...
```

#### Implementation Details

- `hollow_out_spec` parses the markdown heading hierarchy (levels 1-4), splits body text into paragraphs at blank-line boundaries, classifies each paragraph by kind, extracts keywords using a stop-word filtered tokenizer, and extracts entity references matching `ENT-\d{4}`.
- Keywords are lowercased, deduplicated, and limited to terms >= 3 characters.
- The function builds both `entity_index` and `keyword_index` as inverted maps from the paragraph data.
- The `spec_hash` uses SHA-256 to detect when re-hollowing is needed after spec changes.

#### Tests

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_extractor.py`**

- `test_hollow_out_basic_spec`: Parse a simple spec with 2 sections, verify section hierarchy and paragraph extraction.
- `test_paragraph_classification`: Verify prose, bullet list, code block, and table detection.
- `test_keyword_extraction`: Verify stop-word filtering and multi-word phrase extraction.
- `test_entity_ref_extraction`: Verify ENT-#### pattern extraction from text.
- `test_spec_hash_changes_on_content_change`: Verify spec_hash differs for different content.
- `test_empty_spec_produces_empty_hollowed_spec`: Edge case for empty input.

---

### Plan 2: Evidence Index and Search Engine

**Goal:** Build the inverted index and search API that allows querying the hollowed-out spec store with context from translation ambiguities.

#### Files to Create

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/indexer.py`**

```python
"""Build and manage the evidence index over hollowed-out specs."""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.schemas.hollowed_spec import HollowedSpec


class EvidenceIndex:
    """Composite index over multiple hollowed-out specs.

    Provides unified keyword and entity search across all indexed libraries.

    Attributes:
        specs: Mapping of lib_id -> HollowedSpec
        global_keyword_index: keyword -> list of (lib_id, paragraph_id)
        global_entity_index: entity_name -> list of (lib_id, paragraph_id)
    """

    def __init__(self) -> None: ...

    def add_spec(self, spec: HollowedSpec) -> None:
        """Add a hollowed spec to the index."""
        ...

    def remove_spec(self, lib_id: str) -> None:
        """Remove a spec from the index (for re-indexing)."""
        ...

    def save(self, path: Path) -> None:
        """Persist the index to a JSON file."""
        ...

    @classmethod
    def load(cls, path: Path) -> EvidenceIndex:
        """Load an index from a JSON file."""
        ...


def build_evidence_index(workspace_root: Path) -> EvidenceIndex:
    """Scan workspace for hollowed specs and build a unified index.

    Args:
        workspace_root: Root of the run workspace

    Returns:
        Populated EvidenceIndex
    """
    ...
```

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/searcher.py`**

```python
"""Search the evidence store for ambiguity resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spec_manager.schemas.hollowed_spec import HollowedParagraph


@dataclass
class SearchResult:
    """A single search result from the evidence store.

    Attributes:
        lib_id: Library containing the match
        paragraph: The matching paragraph
        score: Relevance score (0.0-1.0)
        matched_keywords: Keywords that matched the query
        matched_entities: Entities that matched the query
        section_path: Section hierarchy path
    """
    lib_id: str
    paragraph: HollowedParagraph
    score: float
    matched_keywords: list[str]
    matched_entities: list[str]
    section_path: str


class EvidenceSearcher:
    """Search the hollowed-out spec evidence store.

    Supports three search modes:
    1. Keyword search: match query terms against keyword index
    2. Entity search: match entity names/IDs against entity index
    3. Hybrid search: combine keyword + entity with weighted scoring
    """

    def __init__(self, index: "EvidenceIndex") -> None: ...

    def search(
        self,
        query: str,
        *,
        entity_names: list[str] | None = None,
        max_results: int = 10,
        min_score: float = 0.1,
        exclude_lib_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the evidence store.

        Args:
            query: Free-text query (split into keywords)
            entity_names: Optional entity names to boost matches
            max_results: Maximum results to return
            min_score: Minimum relevance score threshold
            exclude_lib_ids: Libraries to exclude from results

        Returns:
            Ranked list of SearchResult objects
        """
        ...

    def search_for_ambiguity(
        self,
        ambiguity_text: str,
        ambiguity_question: str,
        context_section: str = "",
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Search specifically for ambiguity resolution.

        Combines the ambiguity text, question, and context section
        into a weighted query optimized for finding spec answers.

        Args:
            ambiguity_text: The ambiguous text
            ambiguity_question: The question to resolve
            context_section: Surrounding context from the translation
            max_results: Maximum results to return

        Returns:
            Ranked list of SearchResult objects
        """
        ...
```

#### Implementation Details

- **Scoring algorithm**: For each query term, compute `tf = occurrences_in_paragraph / total_terms_in_paragraph`. Score per paragraph = `sum(tf * idf)` where `idf = log(total_paragraphs / paragraphs_containing_term)`. Entity matches receive a 2x boost. Results are normalized to 0.0-1.0.
- **`EvidenceIndex`** merges per-spec keyword and entity indexes into global inverted indexes. The global index maps `keyword -> [(lib_id, paragraph_id), ...]`.
- **Persistence**: The index is stored at `{workspace}/workspace/indexes/evidence_store_index.json`. It is a computed artifact regenerated from hollowed specs.
- **`search_for_ambiguity`** extracts keywords from both the ambiguity text and question, deduplicates, and runs a hybrid search. It also extracts any entity references from the ambiguity context.

#### Tests

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_indexer.py`**

- `test_build_index_from_single_spec`: Build index, verify keyword and entity entries.
- `test_build_index_from_multiple_specs`: Verify cross-library search works.
- `test_remove_and_rebuild`: Remove a spec, verify its entries are gone.
- `test_index_persistence_roundtrip`: Save and load, verify equality.

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_searcher.py`**

- `test_keyword_search_basic`: Search for a known keyword, verify results.
- `test_entity_search_boost`: Verify entity matches are scored higher.
- `test_exclude_lib_ids`: Verify exclusion works.
- `test_search_for_ambiguity`: End-to-end ambiguity search with context.
- `test_no_results_returns_empty`: Query with no matches returns [].
- `test_min_score_filters`: Verify low-scoring results are filtered.

---

### Plan 3: Ambiguity Research Integration

**Goal:** Wire the evidence store into the existing ambiguity resolution flow so agents check local specs before (or instead of) web search, and flag genuine gaps when nothing is found.

#### Files to Create

**`scripts/spec_manager/spec_manager/refinement/interactive/research/evidence_store_researcher.py`**

```python
"""Evidence store researcher - searches hollowed-out specs for ambiguity answers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher, SearchResult
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

logger = logging.getLogger(__name__)

# Minimum score threshold for evidence store results to be considered "found"
EVIDENCE_FOUND_THRESHOLD = 0.4


class EvidenceStoreResearcher:
    """Searches the hollowed-out spec evidence store for ambiguity resolution.

    Integrates with the existing research flow as a pre-filter before web search.
    When the evidence store has a high-confidence answer, web search is skipped.
    When no answer is found, the ambiguity is flagged as a potential spec gap.
    """

    def __init__(self, index: EvidenceIndex) -> None: ...

    def research(
        self,
        ambiguity: Ambiguity,
        workspace: Path,
    ) -> SteeringResponse | None:
        """Search the evidence store for an answer to the ambiguity.

        Args:
            ambiguity: The ambiguity to research.
            workspace: Working directory.

        Returns:
            SteeringResponse if a sufficient answer was found, None otherwise.
        """
        ...

    def _format_response(
        self,
        ambiguity: Ambiguity,
        results: list[SearchResult],
    ) -> SteeringResponse:
        """Format search results into a SteeringResponse."""
        ...

    def flag_as_spec_gap(
        self,
        ambiguity: Ambiguity,
        workspace: Path,
    ) -> None:
        """Flag an unresolved ambiguity as a genuine spec gap.

        Creates a Gap entry in the workspace's gap queue for the
        spec building phase to address.
        """
        ...
```

#### Files to Modify

**`scripts/spec_manager/spec_manager/refinement/interactive/research/coordinator.py`**

Add evidence store search as the first step in the research flow, before web search.

```python
# Modified research method signature stays the same:
def research(self, ambiguity: Ambiguity, workspace: Path) -> SteeringResponse:
    # NEW Step 0: Search evidence store
    evidence_response = self._search_evidence_store(ambiguity, workspace)
    if evidence_response is not None:
        return evidence_response

    # Existing Step 1: Extract search signals
    ...

    # NEW Step 4: Flag as spec gap if web search also fails
    if response.response_text == "" or response confidence < threshold:
        self._flag_spec_gap(ambiguity, workspace)
```

**`scripts/spec_manager/spec_manager/refinement/interactive/research/__init__.py`**

Add `EvidenceStoreResearcher` to exports.

**`scripts/spec_manager/spec_manager/refinement/interactive/steering/auto_responder.py`**

Modify `_research_respond` to first try evidence store before falling back to the full `ResearchCoordinator` flow.

#### Integration Points

1. **`ResearchCoordinator.research()`** gains a new first step that queries the evidence store. The method in `coordinator.py` at line 26 is extended.
2. **`AutoResponder._research_respond()`** in `auto_responder.py` at line 52 gains an evidence-store-first path.
3. **`SteeringResponse.source`** gains a new value `"evidence_store"` to distinguish evidence-store answers from web research and steering scripts.
4. **Gap creation** uses `GapQueue` from `spec_manager.refinement.core.gap_queue` and `Gap` from `spec_manager.refinement.core.gap` (same classes used by `spec_building.py`).

#### Tests

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_evidence_store_researcher.py`**

- `test_research_finds_answer_in_store`: Mock index with matching content, verify SteeringResponse returned.
- `test_research_no_answer_returns_none`: Empty store, verify None returned.
- `test_flag_as_spec_gap_creates_gap`: Verify Gap entry created with correct type and evidence.
- `test_response_source_is_evidence_store`: Verify source field is set correctly.

**`scripts/spec_manager/tests/refinement/interactive/test_coordinator_with_evidence_store.py`**

- `test_coordinator_skips_web_when_evidence_found`: Verify web search agents are not called when evidence store has an answer.
- `test_coordinator_falls_through_to_web_search`: Verify web search is used when evidence store returns None.

---

### Plan 4: Post-Completion Hollow-Out Hook

**Goal:** Automatically hollow out specs when they reach completion, and register the hollowed spec in the evidence index.

#### Files to Create

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/hooks.py`**

```python
"""Post-completion hooks for hollowing out specs."""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.refinement.hollowed_spec.extractor import hollow_out_spec
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex, build_evidence_index
from spec_manager.refinement.workspace import WorkspaceManager

logger = logging.getLogger(__name__)


def on_spec_completed(
    lib_id: str,
    manager: WorkspaceManager,
) -> None:
    """Hook called when a library spec reaches completion.

    Hollows out the spec and updates the evidence index.

    Args:
        lib_id: Library ID whose spec was completed
        manager: Workspace manager
    """
    ...


def rebuild_evidence_index(manager: WorkspaceManager) -> int:
    """Rebuild the evidence index from all hollowed specs in the workspace.

    Args:
        manager: Workspace manager

    Returns:
        Number of specs indexed
    """
    ...
```

#### Files to Modify

**`scripts/spec_manager/spec_manager/refinement/workspace/manager.py`**

Add a property to `RunFolderStructure` for the evidence store directory:

```python
@property
def evidence_store_dir(self) -> Path:
    """Path to the hollowed-out spec evidence store directory."""
    return self.workspace_dir / "evidence_store"

@property
def evidence_index_path(self) -> Path:
    """Path to the evidence store index file."""
    return self.workspace_dir / "indexes" / "evidence_store_index.json"
```

**`scripts/spec_manager/spec_manager/refinement/workflows/spec_building.py`**

At the point where a library spec is marked complete (after successful convergence in the iteration loop), call the hollow-out hook:

```python
# After spec is written and converged:
from spec_manager.refinement.hollowed_spec.hooks import on_spec_completed
on_spec_completed(lib_id, manager)
```

**`scripts/spec_manager/spec_manager/refinement/workflows/spec_stabilization.py`**

Similarly, after spec stabilization completes for a library, call the hollow-out hook so the stabilized (potentially improved) version replaces the earlier hollowed version.

#### Workspace Layout

```
runs/<run_id>/
  workspace/
    evidence_store/
      LIB-0001/
        hollowed_spec.json    # HollowedSpec serialized
      LIB-0002/
        hollowed_spec.json
    indexes/
      evidence_store_index.json  # EvidenceIndex serialized
```

#### Tests

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_hooks.py`**

- `test_on_spec_completed_creates_hollowed_spec`: Verify hollowed_spec.json is written.
- `test_on_spec_completed_updates_index`: Verify evidence index is updated.
- `test_rebuild_index_from_multiple_specs`: Verify rebuild scans all hollowed specs.
- `test_hook_is_idempotent`: Calling twice with same spec content produces same result.
- `test_hook_re_hollows_on_content_change`: Verify spec_hash check triggers re-hollow.

---

### Plan 5: Proactive Adjacency Scanner

**Goal:** Implement proactive evidence pre-fetching using call graph and store touch analysis so agents have related context before they encounter ambiguities.

#### Files to Create

**`scripts/spec_manager/spec_manager/refinement/hollowed_spec/adjacency.py`**

```python
"""Proactive adjacency scanning using call graph and store touch analysis."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher, SearchResult
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex

logger = logging.getLogger(__name__)


@dataclass
class AdjacencyContext:
    """Pre-fetched evidence context for a translation unit.

    Attributes:
        target_lib_id: Library being translated
        target_section: Section being translated
        adjacent_evidence: Evidence from related sections/libraries
        store_touch_evidence: Evidence from sections touching shared stores
        call_graph_evidence: Evidence from sections in the call graph
    """
    target_lib_id: str
    target_section: str
    adjacent_evidence: list[SearchResult] = field(default_factory=list)
    store_touch_evidence: list[SearchResult] = field(default_factory=list)
    call_graph_evidence: list[SearchResult] = field(default_factory=list)

    @property
    def all_evidence(self) -> list[SearchResult]:
        """Return all evidence across all categories, deduplicated."""
        ...


class AdjacencyScanner:
    """Proactively scans the evidence store for related context.

    Uses three signals to find adjacent details:
    1. Entity co-occurrence: sections mentioning the same entities
    2. Store touches: sections describing reads/writes to the same store
    3. Call graph: sections describing functions that call each other
    """

    def __init__(self, index: EvidenceIndex) -> None: ...

    def scan(
        self,
        lib_id: str,
        section_heading: str,
        section_content: str,
        *,
        max_results_per_signal: int = 3,
    ) -> AdjacencyContext:
        """Scan for adjacent evidence proactively.

        Args:
            lib_id: Library being worked on
            section_heading: Current section heading
            section_content: Current section content
            max_results_per_signal: Max results per signal type

        Returns:
            AdjacencyContext with pre-fetched evidence
        """
        ...

    def _find_entity_co_occurrences(
        self,
        entity_refs: list[str],
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs mentioning the same entities."""
        ...

    def _find_store_touch_overlaps(
        self,
        section_content: str,
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs describing access to the same stores.

        Looks for store-related keywords (database, table, queue, cache,
        file, bucket) co-occurring with the same named store.
        """
        ...

    def _find_call_graph_neighbors(
        self,
        section_content: str,
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs describing functions that appear in the call graph.

        Extracts function names from the section content and searches
        for other paragraphs mentioning those same function names.
        """
        ...
```

#### Files to Modify

**`scripts/spec_manager/spec_manager/refinement/workflows/spec_building.py`**

In the spec building iteration loop, before generating the spec patch prompt for a library, call the adjacency scanner to pre-fetch context and include it in the prompt:

```python
# Before building the spec prompt:
adjacency_context = adjacency_scanner.scan(
    lib_id=lib_id,
    section_heading=current_section,
    section_content=current_section_text,
)
# Include adjacency_context.all_evidence summaries in the prompt
```

#### Integration Points

1. **`AdjacencyScanner.scan()`** is called from the spec building iteration loop in `spec_building.py`.
2. **`AdjacencyContext`** provides pre-fetched evidence that augments the spec patch prompt.
3. The scanner queries the same `EvidenceIndex` used by the `EvidenceSearcher`, ensuring consistency.
4. Store-touch detection uses keyword heuristics (not AST parsing) since specs are markdown prose, not code.
5. Call graph detection extracts function-like identifiers (`snake_case` and `camelCase` names) from section text and searches for those as keywords.

#### Tests

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_adjacency.py`**

- `test_entity_co_occurrence_finds_related`: Two specs with shared entity refs, verify discovery.
- `test_store_touch_finds_shared_store`: Two sections describing same "orders" table, verify match.
- `test_call_graph_finds_function_reference`: Section mentions `validate_payment`, verify it finds another section defining that function.
- `test_exclude_own_library`: Verify the scanner does not return results from the library being translated.
- `test_all_evidence_deduplicates`: Verify duplicate paragraphs across signals are deduplicated.
- `test_empty_index_returns_empty_context`: No indexed specs, verify empty AdjacencyContext.

---

### Plan 6: CLI Commands and End-to-End Integration

**Goal:** Add CLI commands for managing the evidence store and wire up the full end-to-end flow.

#### Files to Modify

**`scripts/spec_manager/spec_manager/cli.py`**

Add subcommands under a new `evidence-store` group:

```python
# New CLI commands:
# spec-manager evidence-store hollow --run-id <id> [--lib-id <id>]
# spec-manager evidence-store rebuild-index --run-id <id>
# spec-manager evidence-store search --run-id <id> --query <text> [--max-results N]
# spec-manager evidence-store status --run-id <id>
```

- `hollow`: Manually trigger hollow-out for one or all libraries.
- `rebuild-index`: Rebuild the evidence index from scratch.
- `search`: Interactive search for testing/debugging.
- `status`: Show index stats (number of specs, paragraphs, keywords, entities).

**`scripts/spec_manager/spec_manager/refinement/interactive/workflow.py`**

Modify `InteractiveWorkflow.__init__` to accept and propagate an `EvidenceIndex` to the `AutoResponder` when available:

```python
def __init__(
    self,
    workspace: Path,
    interactive: bool = True,
    steering_path: Path | None = None,
    use_research: bool = False,
    use_evidence_store: bool = False,  # NEW
    max_iterations: int = 5,
) -> None:
```

#### Files to Create

**`scripts/spec_manager/tests/refinement/hollowed_spec/__init__.py`**

Empty init file for the test package.

**`scripts/spec_manager/tests/refinement/hollowed_spec/test_end_to_end.py`**

- `test_full_pipeline_hollow_index_search`: Create a spec, hollow it, build index, search, verify results.
- `test_ambiguity_resolved_from_evidence_store`: Full flow: detect ambiguity -> evidence store search -> SteeringResponse.
- `test_ambiguity_not_resolved_creates_gap`: Full flow: detect ambiguity -> evidence store returns None -> Gap created.

#### Integration Summary

The full data flow is:

```
spec_building completes
  -> on_spec_completed hook fires
    -> hollow_out_spec() extracts HollowedSpec
    -> EvidenceIndex.add_spec() updates index
    -> index saved to workspace/indexes/evidence_store_index.json

Agent hits ambiguity during translation
  -> AmbiguityDetector.detect() finds ambiguities
  -> AutoResponder.respond() tries:
    1. Steering script (existing)
    2. EvidenceStoreResearcher.research() (NEW)
    3. ResearchCoordinator.research() with evidence-store-first (NEW)
  -> If resolved: SteeringResponse(source="evidence_store")
  -> If not resolved: flag_as_spec_gap() creates Gap in GapQueue

Next spec_building iteration picks up gap
  -> Adjacency scanner pre-fetches related evidence (NEW)
  -> Gap is included in spec patch prompt
  -> Spec is updated to address the gap
```

## Execution Instructions

Implement the plans in order (1 through 6). Each plan is independently testable:

- **Plan 1** has no dependencies on other plans. Test the extractor in isolation with sample spec markdown.
- **Plan 2** depends on Plan 1 schemas. Test the index and searcher with synthetic HollowedSpec objects.
- **Plan 3** depends on Plans 1 and 2. Test with mocked EvidenceIndex. Integration tests can use the real extractor.
- **Plan 4** depends on Plans 1 and 2. Test hooks with a mock WorkspaceManager.
- **Plan 5** depends on Plan 2. Test the scanner with synthetic index data.
- **Plan 6** depends on all previous plans. End-to-end tests verify the full pipeline.

Run tests with: `uv run python -m pytest scripts/spec_manager/tests/refinement/hollowed_spec/ -p no:randomly -v`

## Success Criteria

1. **Hollow-out pipeline**: Given a complete `spec.md` with at least 3 sections and 10 paragraphs, `hollow_out_spec()` produces a `HollowedSpec` with correctly parsed sections, paragraphs, keywords, and entity references. The keyword index has at least 20 entries. The entity index captures all `ENT-####` references.

2. **Search accuracy**: Given a pre-built index with 3 hollowed specs, `EvidenceSearcher.search()` returns the correct spec paragraph as the top result for queries containing keywords from that paragraph, in at least 80% of test cases.

3. **Ambiguity resolution**: When an ambiguity's question text contains keywords matching a paragraph in the evidence store, `EvidenceStoreResearcher.research()` returns a `SteeringResponse` with `source="evidence_store"` and the response text includes the relevant paragraph content.

4. **Gap creation**: When `EvidenceStoreResearcher.research()` returns None and web research also fails, a `Gap` entry with type `EVIDENCE_GAP` is created in the `GapQueue`.

5. **Hook integration**: After `spec_building` completes for a library, the `workspace/evidence_store/{lib_id}/hollowed_spec.json` file exists and the `evidence_store_index.json` includes entries for that library.

6. **Adjacency pre-fetch**: Given two specs where Spec A mentions entity `ENT-0001` in a section about payments, and Spec B also mentions `ENT-0001` in a section about fraud detection, `AdjacencyScanner.scan()` on Spec A's payments section returns evidence from Spec B's fraud detection section.

7. **CLI operational**: `spec-manager evidence-store status --run-id <id>` reports the number of indexed specs, total paragraphs, keyword count, and entity count.

8. **All tests pass**: `uv run python -m pytest scripts/spec_manager/tests/refinement/hollowed_spec/ -p no:randomly -v` exits 0.
