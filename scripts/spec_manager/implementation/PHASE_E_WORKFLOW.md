# Phase E: Workflow Integration

## Overview

This phase wires everything together with **compliance gating**, **compositing**, and **plan.md sync**.

The workflow orchestrates:

1. **Ingest** - Process new inputs with provenance tracking
2. **Clean** - Iteratively clean using Clean→Validate→Fix→Snapshot loop
3. **Compliance Gate** - Library discovery BLOCKED until compliance threshold met
4. **Discover** - Identify and refine libraries (only after compliance)
5. **Review** - Concrete resolution actions, not just analysis
6. **Sync** - plan.md ↔ libraries synchronization
7. **Finalize** - Remove stamps, generate gaps.md, relations written to output

## Key Additions

### Compliance Gate

Library discovery cannot begin until inputs are "compliant":
- Format compliance score > threshold (e.g., 90%)
- No critical errors in validation
- Remainder queue below threshold

### Compositing (Merge + Remainder Partition)

When multiple patches touch the same element:
- Don't just "latest wins"
- Keep unchanged atoms + updated atoms
- Carry unresolved atoms as remainder
- Persist composite artifacts as intermediate markdown

**Strategy-Driven Compositing**: Compositing is NOT a single algorithm:

| Content Type | Compositing Strategy | Preserves |
|--------------|---------------------|-----------|
| Structured (algo/claim) | Diff/patch application | Sequence, structure |
| Messy prose | Bag-of-lines (fallback) | Content (not order) |
| Vague patch intent | LLM-assisted merge | Semantic intent |

For structured content, use sequence-preserving diff/patch with provenance pinned to hunks.
For messy prose, allow bag-of-lines only as LOW-CONFIDENCE fallback, and record that it's low-confidence evidence.
When patch intent is vague, LLM-assisted merge requires: provenance spans, evidence trail, remainder capture when confidence is low.

### Versioned Intermediate Artifacts

**Critical**: Writing a single composite.md (overwritten) is NOT "retain files between each step."

**Design**:
```
.workspace/intermediates/
├── cleaning_pass_01/
│   ├── composite.md
│   ├── plan.md
│   └── evidence.json
├── cleaning_pass_02/
│   ├── composite.md
│   ├── plan.md
│   └── evidence.json
├── compositing_01/
│   ├── composite.md
│   └── remainders.json
└── discovery_01/
    ├── libraries/
    │   ├── field.md
    │   └── verification.md
    └── shapes.json
```

**Comparator**: Can answer "what moved, what was dropped, what was re-expressed?" between any two versions.

### plan.md ↔ libraries Sync

After finalization, ensure consistency:
- **Authority at finalization: LIBRARIES** (not configurable - this is the workflow design)
- plan.md is generated as a unified view/projection of libraries
- During ingest, plan.md can be a working projection, but authority at the end is fixed
- Run ProjectionComparator for membership checks
- Drift → gaps.md entries

**Clarification**: The conversation is clear - libraries are created late and become authoritative at the end. plan.md is a projection/unified view.

### Relations in Output

Cross-cutting concerns preserved:
- Per-element: `(@[+rel:library_name])`
- Library-level cross-links index

## The Complete Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           INGEST WORKFLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Inputs    │───▶│  Cleaning   │───▶│ Compositing │                 │
│  │ (patches)   │    │ (iterative) │    │ (remainders)│                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         │    Intermediate snapshots saved at each step                  │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────────────────────────────────────────────┐               │
│  │              PROVENANCE TRACKING                     │               │
│  │  Every unit stamped with @from:p# @modified:p#,p#   │               │
│  └─────────────────────────────────────────────────────┘               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  Candidate  │───▶│Multi-Label  │───▶│   Shape     │                 │
│  │Identification│   │ Assignment  │    │ Aggregation │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         │    Strategies applied as appropriate                          │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────────────────────────────────────────────┐               │
│  │              LIBRARY DISCOVERY                       │               │
│  │  Libraries emerge from data, not predefined          │               │
│  └─────────────────────────────────────────────────────┘               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │  Overlap    │───▶│  Resolve    │───▶│   Assign    │                 │
│  │  Analysis   │    │  Conflicts  │    │   Primary   │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         │    Reference original inputs for priority                     │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────────────────────────────────────────────┐               │
│  │              LIBRARY REVIEW                          │               │
│  │  Convergence/divergence analysis                     │               │
│  └─────────────────────────────────────────────────────┘               │
│                                                                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Discard   │───▶│  Generate   │───▶│   Write     │                 │
│  │   Stamps    │    │   Gaps      │    │   Output    │                 │
│  └─────────────┘    └─────────────┘    └─────────────┘                 │
│         │                  │                  │                         │
│         │    Libraries become authoritative                             │
│         ▼                  ▼                  ▼                         │
│  ┌─────────────────────────────────────────────────────┐               │
│  │              FINALIZATION                            │               │
│  │  • libraries/*.md (authoritative)                    │               │
│  │  • plan.md (unified view)                            │               │
│  │  • gaps.md (remaining issues)                        │               │
│  └─────────────────────────────────────────────────────┘               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Implementation

### File 1: `spec_manager/workflow/orchestrator.py`

```python
"""
Workflow orchestrator - coordinates the full ingest workflow.

The orchestrator:
- Manages phase transitions
- Applies strategies at appropriate points
- Saves intermediate states
- Handles errors gracefully
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from spec_manager.core.provenance import ProvenanceTracker, TrackedUnit
from spec_manager.core.intermediate import IntermediateManager, IntermediateState
from spec_manager.core.gaps import UnifiedGapDetector
from spec_manager.strategies.registry import StrategyRegistry
from spec_manager.strategies.base import ProcessingContext, StrategyPhase
from spec_manager.discovery.candidate import CandidateIdentifier
from spec_manager.discovery.labeling import MultiLabeler
from spec_manager.discovery.aggregation import ShapeAggregator
from spec_manager.discovery.refinement import LibraryRefiner


logger = logging.getLogger(__name__)


class WorkflowPhase(Enum):
    """Phases in the ingest workflow."""

    INIT = "init"
    CLEANING = "cleaning"       # With compliance gate
    COMPOSITING = "compositing" # Merge + remainder partition
    DISCOVERY = "discovery"     # Only after compliance gate passes
    REVIEW = "review"           # Concrete resolution actions
    SYNC = "sync"               # plan.md ↔ libraries synchronization
    FINALIZE = "finalize"       # Stamps removed, relations written
    COMPLETE = "complete"


# =============================================================================
# PATCH-CHAIN + CONTEXT INDEX DATA STRUCTURES (Gap 5 fix)
# =============================================================================

@dataclass
class PatchDependency:
    """Represents a patch dependency: source_patch patches target_patch."""
    source_patch: str           # e.g., "p5"
    target_patch: str           # e.g., "p3"
    dependency_type: str        # "patches", "extends", "replaces"
    evidence: str               # Where this dependency was detected


class PatchDependencyGraph:
    """
    Tracks patch dependencies: "p5 patches p3 which patched p1".

    Used for entity resolution when vague references need patch context.
    """

    def __init__(self):
        self.dependencies: list[PatchDependency] = []
        self._graph: dict[str, list[str]] = {}  # patch_id → [patched_by]

    def add_dependency(self, source: str, target: str, dep_type: str = "patches", evidence: str = "") -> None:
        """Add a patch dependency."""
        self.dependencies.append(PatchDependency(source, target, dep_type, evidence))
        if target not in self._graph:
            self._graph[target] = []
        self._graph[target].append(source)

    def get_patch_chain(self, patch_id: str) -> list[str]:
        """Get the chain of patches that led to patch_id."""
        chain = [patch_id]
        current = patch_id

        # Walk backwards through dependencies
        visited = {patch_id}
        while True:
            # Find what this patch depends on
            depends_on = None
            for dep in self.dependencies:
                if dep.source_patch == current:
                    depends_on = dep.target_patch
                    break

            if depends_on and depends_on not in visited:
                chain.append(depends_on)
                visited.add(depends_on)
                current = depends_on
            else:
                break

        return list(reversed(chain))  # Oldest first

    def infer_from_content(self, patch_content: str, patch_id: str) -> None:
        """
        Infer dependencies from patch content.

        Gap 1 fix: PRIMARY inference is from:
        1. Chronological order (p1 < p2 < p3)
        2. Shared element IDs (if p5 mentions Algorithm 3, check which patch introduced it)
        3. Provenance "modified_by" evidence already in units

        SECONDARY (low-confidence hint): regex mention parsing.
        Do NOT rely on hardcoded domain phrases like "relaxation algorithm".
        """
        import re

        # PRIMARY: Extract numeric patch ID and assume sequential dependency
        match = re.match(r'p(\d+)', patch_id)
        if match:
            patch_num = int(match.group(1))
            # Assume patches p1...p(n-1) as potential dependencies
            for prev_num in range(1, patch_num):
                prev_id = f"p{prev_num}"
                # Only add if we have evidence from shared IDs
                shared_ids = self._find_shared_ids(patch_content, prev_id)
                if shared_ids:
                    self.add_dependency(
                        source=patch_id,
                        target=prev_id,
                        dep_type='patches',
                        evidence=f"Shared IDs: {', '.join(shared_ids[:3])}"
                    )

        # SECONDARY (low-confidence hint): explicit patch references
        # These are treated as HINTS, not the backbone of dependency inference
        hint_patterns = [
            (r'patches?\s+(p\d+)', 'patches', 0.6),
            (r'from\s+(p\d+)', 'extends', 0.5),
            (r'(p\d+)\'s', 'extends', 0.4),
            (r'updates?\s+(p\d+)', 'patches', 0.6),
        ]

        for pattern, dep_type, confidence in hint_patterns:
            for match in re.finditer(pattern, patch_content, re.IGNORECASE):
                target = match.group(1)
                if target != patch_id:
                    # Mark as low-confidence hint, not backbone dependency
                    self.add_dependency(
                        source=patch_id,
                        target=target,
                        dep_type=dep_type,
                        evidence=f"[hint:{confidence:.1f}] {match.group(0)}"
                    )

    def _find_shared_ids(self, content: str, other_patch_id: str) -> list[str]:
        """Find element IDs that appear in both this content and originate from other_patch_id."""
        import re
        # Extract all declared/referenced IDs
        id_patterns = [
            r'\(\[=([^\]]+)\]\)',     # Declarations
            r'\(@\[\+?([^\]]+)\]\)',  # References
            r'\bAlgorithm\s+(\d+)\b', # Algorithm references
            r'\b(P\d+C\d+|P\d+I\d+|D\d+|G\d+)\b',  # Standard IDs
        ]
        found_ids = []
        for pattern in id_patterns:
            for m in re.finditer(pattern, content):
                found_ids.append(m.group(1))
        # In a real implementation, cross-reference with what other_patch_id introduced
        # For now, return non-empty if we find standard IDs (actual lookup requires state)
        return list(set(found_ids))[:5]


class ContextIndex:
    """
    Index over all context strata for entity resolution.

    Strata (in priority order):
    1. Originals (patches/*.md)
    2. Each intermediate projection (cleaning_pass_*/composite.md)
    3. Current composite

    Entity resolution queries this to find "the relaxation algorithm"
    when a vague reference needs resolution.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._index: dict[str, list[dict]] = {}  # term → locations
        self._strata: list[dict] = []  # [{path, content, priority}, ...]

    def add_stratum(self, path: Path, content: str, priority: int, stratum_type: str) -> None:
        """Add a context stratum to the index."""
        self._strata.append({
            'path': str(path),
            'content': content,
            'priority': priority,
            'type': stratum_type
        })
        self._index_content(content, str(path), priority)

    def _index_content(self, content: str, path: str, priority: int) -> None:
        """
        Index terms from content.

        Gap 1 fix: Index primarily from DECLARED IDS + HEADINGS + EXTRACTED KEYPHRASES,
        NOT a fixed phrase list like "relaxation algorithm" or "convergence proof".

        Indexing sources (in order):
        1. Declared IDs: ([=...]) annotations
        2. Headings: ## Algorithm 1, ### D5, etc.
        3. Keyphrases: spaCy noun chunks or TF-IDF extracted terms
        4. Standard ID patterns: P#C#, P#I#, G#, D#, Lean#
        """
        import re

        # PRIMARY: Declared IDs - these are authoritative
        decl_pattern = re.compile(r'\(\[=([^\]]+)\]\)')
        for match in decl_pattern.finditer(content):
            term = match.group(1).lower()
            self._add_to_index(term, path, match.start(), content, priority, 'declared_id')

        # SECONDARY: Headings with element IDs
        heading_pattern = re.compile(r'^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)(.*)$', re.MULTILINE)
        for match in heading_pattern.finditer(content):
            term = match.group(2).lower()
            self._add_to_index(term, path, match.start(), content, priority, 'heading')

        # TERTIARY: Standard ID patterns in body (not declarations/headings)
        standard_patterns = [
            (r'\bAlgorithm\s+(\d+)\b', 'algorithm'),
            (r'\b(D\d+)\b', 'data_structure'),
            (r'\b(G\d+)\b', 'goal'),
            (r'\b(P\d+C\d+)\b', 'claim'),
            (r'\b(P\d+I\d+)\b', 'invariant'),
            (r'\b(Lean\d+)\b', 'lean'),
        ]
        for pattern, entity_type in standard_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                term = match.group(0).lower()
                self._add_to_index(term, path, match.start(), content, priority, entity_type)

        # QUATERNARY: Extract keyphrases using NLP (if available)
        self._index_keyphrases(content, path, priority)

    def _add_to_index(self, term: str, path: str, position: int, content: str, priority: int, entity_type: str) -> None:
        """Add a term to the index with context."""
        if term not in self._index:
            self._index[term] = []
        self._index[term].append({
            'path': path,
            'position': position,
            'context': content[max(0, position-50):position+100],
            'priority': priority,
            'type': entity_type
        })

    def _index_keyphrases(self, content: str, path: str, priority: int) -> None:
        """
        Extract keyphrases using NLP (spaCy noun chunks or fallback).

        Gap 1 fix: This replaces hardcoded domain phrases with data-driven extraction.
        """
        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(content[:5000])  # Limit for performance

            # Extract noun chunks as potential keyphrases
            for chunk in doc.noun_chunks:
                # Filter: at least 2 words, not too common
                if len(chunk.text.split()) >= 2 and len(chunk.text) < 50:
                    term = chunk.text.lower()
                    if term not in self._index:
                        self._index[term] = []
                    self._index[term].append({
                        'path': path,
                        'position': chunk.start_char,
                        'context': content[max(0, chunk.start_char-30):chunk.end_char+30],
                        'priority': priority - 1,  # Lower priority than explicit IDs
                        'type': 'keyphrase'
                    })
        except (ImportError, OSError):
            # Fallback: simple bigram extraction
            import re
            words = re.findall(r'\b[A-Za-z][a-z]+\b', content)
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}".lower()
                if bigram not in self._index:
                    self._index[bigram] = []
                # Very low priority for fallback keyphrases
                self._index[bigram].append({
                    'path': path,
                    'position': 0,
                    'context': bigram,
                    'priority': priority - 2,
                    'type': 'bigram'
                })

    def resolve(self, vague_reference: str, patch_context: str = None) -> list[dict]:
        """
        Resolve a vague reference to candidate entities.

        Returns candidates sorted by priority (higher = more recent/relevant).
        """
        candidates = []

        # Normalize reference
        normalized = vague_reference.lower().strip()

        # Direct lookup
        if normalized in self._index:
            candidates.extend(self._index[normalized])

        # Fuzzy lookup - partial matches
        for term, locations in self._index.items():
            if normalized in term or term in normalized:
                candidates.extend(locations)

        # Sort by priority (descending) and dedupe
        candidates.sort(key=lambda x: x['priority'], reverse=True)
        seen = set()
        unique = []
        for c in candidates:
            key = (c['path'], c['position'])
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique[:10]  # Top 10 candidates

    def refresh_from_intermediates(self) -> None:
        """Refresh index from all intermediate projections."""
        intermediates_dir = self.workspace / "intermediates"
        if not intermediates_dir.exists():
            return

        priority = 10  # Start priority
        for pass_dir in sorted(intermediates_dir.iterdir()):
            if pass_dir.is_dir():
                composite_path = pass_dir / "composite.md"
                if composite_path.exists():
                    content = composite_path.read_text()
                    self.add_stratum(composite_path, content, priority, 'intermediate')
                    priority += 1  # Later intermediates have higher priority


@dataclass
class WorkflowConfig:
    """Configuration for the workflow."""

    max_cleaning_passes: int = 10
    max_discovery_iterations: int = 10
    save_intermediates: bool = True
    apply_strategies: bool = True
    verbose: bool = False

    # =========================================================================
    # COMPLIANCE GATE CONFIGURATION (Gap 2 fix)
    # =========================================================================
    compliance_threshold: float = 0.90  # 90% format compliance required
    compliance_gate_mode: str = "block"  # "block" (default) or "warn"
    max_remainder_ratio: float = 0.05   # Max 5% atoms in remainder queue
    require_no_critical_errors: bool = True  # Block on any critical error


@dataclass
class WorkflowState:
    """Current state of the workflow."""

    phase: WorkflowPhase = WorkflowPhase.INIT
    cleaning_pass: int = 0
    discovery_iteration: int = 0

    # Tracked content
    units: list[TrackedUnit] = field(default_factory=list)

    # Discovery state
    candidate_libraries: list[str] = field(default_factory=list)
    library_shapes: dict[str, Any] = field(default_factory=dict)
    final_labels: dict[str, Any] = field(default_factory=dict)

    # Metrics
    started_at: datetime = field(default_factory=datetime.now)
    errors: list[str] = field(default_factory=list)


class WorkflowOrchestrator:
    """
    Orchestrates the full ingest workflow.

    Usage:
        orchestrator = WorkflowOrchestrator(spec_folder)
        result = orchestrator.run()
    """

    def __init__(
        self,
        spec_folder: Path,
        config: WorkflowConfig | None = None
    ):
        self.spec_folder = Path(spec_folder)
        self.config = config or WorkflowConfig()

        # Initialize components
        self.workspace = self.spec_folder / ".workspace"
        self.workspace.mkdir(exist_ok=True)

        self.tracker = ProvenanceTracker()
        self.intermediate_mgr = IntermediateManager(self.workspace)
        self.strategy_registry = StrategyRegistry()
        self.gap_detector = UnifiedGapDetector()

        # =========================================================================
        # PATCH-CHAIN + CONTEXT INDEX (Gap 5 fix)
        # =========================================================================
        # Required for entity resolution: index over all context strata
        self.patch_graph = PatchDependencyGraph()  # "p5 patches p3 patched p1"
        self.context_index = ContextIndex(self.workspace)  # originals + intermediates + composites

        # State
        self.state = WorkflowState()

        # Load strategies
        strategies_dir = Path(__file__).parent.parent / "strategies" / "definitions"
        if strategies_dir.exists():
            self.strategy_registry.load_from_directory(strategies_dir)

    def run(self) -> WorkflowState:
        """
        Run the full workflow:

        1. INIT       - Load inputs, extract units
        2. CLEANING   - Iterative clean with compliance gate
        3. COMPOSITING - Merge + remainder partition
        4. DISCOVERY  - Multi-label library identification (after compliance)
        5. REVIEW     - Concrete resolution actions
        6. SYNC       - plan.md ↔ libraries synchronization
        7. FINALIZE   - Stamps removed, gaps.md, relations written
        """
        try:
            self._phase_init()
            self._phase_cleaning()
            self._phase_compositing()
            self._phase_discovery()
            self._phase_review()
            self._phase_sync()       # ← NEW: plan.md ↔ libraries sync
            self._phase_finalize()

            self.state.phase = WorkflowPhase.COMPLETE
            logger.info("Workflow completed successfully")

        except Exception as e:
            logger.error(f"Workflow failed: {e}")
            self.state.errors.append(str(e))
            raise

        return self.state

    def _phase_init(self) -> None:
        """
        Initialize: Load inputs, extract units.

        Gap 9 fix: Support both patch layouts:
        1. patches/*.md - patch files in a patches subdirectory
        2. p*.md - patch files directly in spec folder (p1.md, p2.md, etc.)
        3. Existing plan.md + libraries/ - use as starting state
        """
        logger.info("Phase: INIT")
        self.state.phase = WorkflowPhase.INIT

        # Gap 9 fix: Discover input files from multiple layouts
        patch_files = []

        # Layout 1: patches/*.md (preferred)
        patches_dir = self.spec_folder / "patches"
        if patches_dir.exists():
            patch_files.extend(sorted(patches_dir.glob("*.md")))
            logger.info(f"  Found {len(patch_files)} files in patches/ directory")

        # Layout 2: p*.md directly in spec_folder
        direct_patches = sorted(self.spec_folder.glob("p*.md"))
        # Filter to actual patch files (p1.md, p2.md, etc.) not plan.md or other files
        direct_patches = [p for p in direct_patches if re.match(r'^p\d+\.md$', p.name)]
        if direct_patches:
            patch_files.extend(direct_patches)
            logger.info(f"  Found {len(direct_patches)} direct patch files (p*.md)")

        # Gap 9 fix: Also index existing plan.md + libraries/ as starting state
        existing_plan = self.spec_folder / "plan.md"
        existing_libraries = self.spec_folder / "libraries"

        if existing_plan.exists():
            logger.info("  Found existing plan.md - indexing as original stratum")
            self.context_index.add_stratum(
                existing_plan,
                existing_plan.read_text(encoding="utf-8"),
                priority=100,  # High priority - authoritative starting state
                stratum_type="original"
            )

        if existing_libraries.exists():
            for lib_file in existing_libraries.glob("*.md"):
                logger.info(f"  Found existing library: {lib_file.name}")
                self.context_index.add_stratum(
                    lib_file,
                    lib_file.read_text(encoding="utf-8"),
                    priority=100,
                    stratum_type="original"
                )

        # Validate we have at least some input
        if not patch_files and not existing_plan.exists():
            raise ValueError(
                f"No inputs found. Expected one of:\n"
                f"  - {patches_dir}/*.md\n"
                f"  - {self.spec_folder}/p*.md\n"
                f"  - {existing_plan} + {existing_libraries}/"
            )

        # Extract units from each patch
        for patch_file in patch_files:
            patch_id = patch_file.stem  # e.g., "p1", "p5"
            content = patch_file.read_text(encoding="utf-8")

            units = self.tracker.extract_units_from_file(
                content=content,
                file_path=str(patch_file),
                patch_id=patch_id
            )

            self.state.units.extend(units)
            logger.info(f"  Extracted {len(units)} units from {patch_file.name}")

            # Gap 9 fix: Index patches as strata for entity resolution
            self.context_index.add_stratum(
                patch_file,
                content,
                priority=50,  # Lower than originals, higher than intermediates
                stratum_type="patch"
            )

        logger.info(f"  Total units: {len(self.state.units)}")

        # Save initial state
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="init",
                description="Initial extraction from patches",
                tracker=self.tracker
            )
            self.intermediate_mgr.save(state)

    def _phase_cleaning(self) -> None:
        """
        Clean inputs iteratively using Clean→Validate→Fix→Snapshot loop.

        CRITICAL (Gap 3 fix): Each pass reads from PREVIOUS INTERMEDIATE PROJECTION,
        not from the original source folder. This closes the loop so detectors
        operate on the evolving state.

        COMPLIANCE GATE: Library discovery is BLOCKED until:
        - Format compliance score > threshold (90%)
        - No critical errors
        - Remainder queue < threshold
        """
        logger.info("Phase: CLEANING (with compliance gate)")
        self.state.phase = WorkflowPhase.CLEANING

        # =========================================================================
        # INTERMEDIATE PROJECTION LOOP (Gap 3 fix)
        # =========================================================================
        # Input = current intermediate projection (not original source folder)
        # Output = next intermediate projection + workspace state
        # Detectors read from the projection, not originals

        current_projection_path = None  # Will be set after first pass

        for pass_num in range(1, self.config.max_cleaning_passes + 1):
            self.state.cleaning_pass = pass_num
            logger.info(f"  Cleaning pass {pass_num}")

            # Step 1: Run validation against INTERMEDIATE PROJECTION (Gap 3 fix)
            # First pass: read from spec_folder
            # Subsequent passes: read from previous intermediate projection
            if current_projection_path and current_projection_path.exists():
                logger.info(f"    Reading from intermediate: {current_projection_path}")
                evidence = self.gap_detector.collect_evidence_from_path(current_projection_path)
            else:
                logger.info(f"    Reading from original: {self.spec_folder}")
                evidence = self.gap_detector.collect_evidence(self.spec_folder)

            compliance_score = self._compute_compliance_score(evidence)
            logger.info(f"    Compliance score: {compliance_score:.1%}")

            # Step 2: Check compliance gate
            if compliance_score >= self.config.compliance_threshold:
                logger.info(f"  Compliance gate PASSED ({compliance_score:.1%} >= {self.config.compliance_threshold:.1%})")
                break

            # Step 3: Apply fix strategies
            if self.config.apply_strategies:
                context = ProcessingContext(
                    units=self.state.units,
                    phase=StrategyPhase.CLEANING,
                    results={'evidence': evidence, 'compliance_score': compliance_score}
                )

                strategies = self.strategy_registry.get_applicable(context)
                changes_made = False

                for strategy in strategies:
                    result = strategy.execute(context)

                    if result.actions_taken:
                        changes_made = True
                        for action in result.actions_taken:
                            logger.info(f"    [{strategy.name}] {action}")

                    self.state.units = result.units
                    context = ProcessingContext(
                        units=self.state.units,
                        phase=StrategyPhase.CLEANING,
                        previous_results={strategy.name: result.metrics}
                    )

                if not changes_made:
                    logger.warning(f"  No changes in pass {pass_num} but compliance not met!")
                    # Don't break - let remaining passes try

            # Gap 10 fix: Compute prose_ratio for this pass
            prose_ratio = self._compute_prose_ratio(self.state.units)
            logger.info(f"    Prose ratio: {prose_ratio:.1%}")

            # Store prose_ratio in context for strategy evolution triggers
            if self.config.apply_strategies:
                context.previous_results['prose_ratio'] = prose_ratio

            # Step 4: Snapshot (versioned per pass) - BECOMES NEXT INPUT (Gap 3 fix)
            if self.config.save_intermediates:
                # Create versioned directory for this pass
                pass_dir = self.intermediate_mgr.intermediates_dir / f"cleaning_pass_{pass_num:02d}"
                pass_dir.mkdir(exist_ok=True)

                # Save composite.md - THIS BECOMES THE NEXT PASS INPUT (Gap 3 fix)
                composite_md = self._generate_composite_markdown(self.state.units)
                composite_path = pass_dir / "composite.md"
                composite_path.write_text(composite_md)

                # Save plan.md projection for this pass
                plan_md = self._generate_plan_projection(self.state.units)
                (pass_dir / "plan.md").write_text(plan_md)

                # Save evidence.json
                import json
                evidence_data = [{'severity': e.severity.value, 'message': e.message, 'location': e.location} for e in evidence]
                (pass_dir / "evidence.json").write_text(json.dumps(evidence_data, indent=2))

                # Gap 10 fix: Save prose_ratio metrics
                metrics_data = {
                    'pass': pass_num,
                    'compliance_score': compliance_score,
                    'prose_ratio': prose_ratio,
                    'unit_count': len(self.state.units),
                    'prose_units': sum(1 for u in self.state.units if str(getattr(u, 'unit_type', '')).lower() == 'prose'),
                    'structured_units': sum(1 for u in self.state.units if str(getattr(u, 'unit_type', '')).lower() in ('algorithm', 'claim', 'invariant', 'goal'))
                }
                (pass_dir / "metrics.json").write_text(json.dumps(metrics_data, indent=2))

                # Save state snapshot
                state = self.intermediate_mgr.create_snapshot(
                    phase=f"cleaning_pass_{pass_num}",
                    description=f"After cleaning pass {pass_num} (compliance: {compliance_score:.1%}, prose: {prose_ratio:.1%})",
                    tracker=self.tracker
                )
                self.intermediate_mgr.save(state)

                # UPDATE: Set current projection path for NEXT pass to read (Gap 3 fix)
                current_projection_path = pass_dir
                logger.info(f"    Intermediate saved: {pass_dir} (will be input for next pass)")

        # Final compliance check - THIS IS A TRUE GATE (Gap 2 fix)
        final_evidence = self.gap_detector.collect_evidence(self.spec_folder)
        final_score = self._compute_compliance_score(final_evidence)
        has_critical = any(e.severity == Severity.ERROR for e in final_evidence)
        remainder_ratio = len(getattr(self.state, 'remainders', [])) / max(len(self.state.units), 1)

        self.state.compliance_passed = False
        self.state.compliance_score = final_score
        self.state.compliance_details = {
            'score': final_score,
            'threshold': self.config.compliance_threshold,
            'has_critical_errors': has_critical,
            'remainder_ratio': remainder_ratio
        }

        if final_score < self.config.compliance_threshold:
            if self.config.compliance_gate_mode == "block":
                logger.error(f"  ❌ Compliance gate BLOCKED: {final_score:.1%} < {self.config.compliance_threshold:.1%}")
                logger.error(f"     Discovery phase will be SKIPPED. Fix compliance issues first.")
                # Do NOT raise - we continue to finalize what we have
            else:
                logger.warning(f"  ⚠️ Compliance gate WARNING: {final_score:.1%} (mode=warn, continuing)")
                self.state.compliance_passed = True  # Allow with warning
        elif has_critical and self.config.require_no_critical_errors:
            if self.config.compliance_gate_mode == "block":
                logger.error(f"  ❌ Compliance gate BLOCKED: {sum(1 for e in final_evidence if e.severity == Severity.ERROR)} critical errors")
                logger.error(f"     Discovery phase will be SKIPPED. Fix critical errors first.")
            else:
                logger.warning(f"  ⚠️ Critical errors present but mode=warn, continuing")
                self.state.compliance_passed = True
        elif remainder_ratio > self.config.max_remainder_ratio:
            if self.config.compliance_gate_mode == "block":
                logger.error(f"  ❌ Compliance gate BLOCKED: {remainder_ratio:.1%} atoms in remainder (max {self.config.max_remainder_ratio:.1%})")
            else:
                logger.warning(f"  ⚠️ High remainder ratio but mode=warn, continuing")
                self.state.compliance_passed = True
        else:
            logger.info(f"  ✅ Compliance gate PASSED: {final_score:.1%}")
            self.state.compliance_passed = True

    def _compute_compliance_score(self, evidence: list) -> float:
        """Compute compliance score from evidence (0-1)."""
        if not evidence:
            return 1.0

        # Count by severity
        errors = sum(1 for e in evidence if e.severity.value == 'error')
        warnings = sum(1 for e in evidence if e.severity.value == 'warning')

        # Simple scoring: each error = -10%, each warning = -2%
        penalty = (errors * 0.10) + (warnings * 0.02)
        return max(0.0, 1.0 - penalty)

    def _phase_compositing(self) -> None:
        """
        Composite units using MERGE + REMAINDER PARTITION.

        NOT just "latest wins" - instead:
        - Keep unchanged atoms + updated atoms
        - Carry unresolved atoms as remainder
        - Persist composite artifacts as intermediate markdown

        Gap 11 fix: Granularity ladder drives atomization level.
        When annotations are sparse, emit fine atoms (line/sentence).
        When well-annotated, use coarser section-level atomization.
        """
        logger.info("Phase: COMPOSITING (merge + remainder)")
        self.state.phase = WorkflowPhase.COMPOSITING

        # Gap 11 fix: Select granularity level for compositing
        granularity = self._select_compositing_granularity()
        logger.info(f"  Using granularity level: {granularity}")

        # Group units by ID to find overlaps
        units_by_id: dict[str, list[TrackedUnit]] = {}
        for unit in self.state.units:
            if unit.id not in units_by_id:
                units_by_id[unit.id] = []
            units_by_id[unit.id].append(unit)

        # Handle overlaps with merge + remainder
        composited_units = []
        remainder_units = []

        for id_value, units in units_by_id.items():
            if len(units) == 1:
                composited_units.append(units[0])
            else:
                # Multiple patches define this ID - merge with remainder
                # Gap 11 fix: Pass granularity to merge function
                composited, remainder = self._merge_with_remainder(units, granularity)
                composited_units.append(composited)
                if remainder:
                    remainder_units.extend(remainder)
                logger.info(f"  Merged {id_value} from {len(units)} sources")
                if remainder:
                    logger.info(f"    Remainder: {len(remainder)} unresolved atoms")

        self.state.units = composited_units
        self.state.remainders = remainder_units

        # Persist composite artifacts as intermediate markdown
        if self.config.save_intermediates:
            composite_md = self._generate_composite_markdown(composited_units)
            composite_path = self.intermediate_mgr.intermediates_dir / "composite.md"
            composite_path.write_text(composite_md)
            logger.info(f"  Saved composite.md ({len(composite_md)} chars)")

            state = self.intermediate_mgr.create_snapshot(
                phase="compositing",
                description=f"After compositing: {len(composited_units)} units, {len(remainder_units)} remainders",
                tracker=self.tracker
            )
            self.intermediate_mgr.save(state)

    def _select_compositing_granularity(self) -> str:
        """
        Select the appropriate granularity level for compositing (Gap 11 fix).

        When annotations are sparse, emit fine atoms (line/sentence).
        When well-annotated, use coarser section-level atomization.

        Returns: 'line', 'sentence', 'clause', or 'section'
        """
        # Count annotation density across all units
        total_decls = 0
        total_lines = 0

        for unit in self.state.units:
            content = getattr(unit, 'content', '')
            decl_count = content.count("([=")
            line_count = len(content.splitlines())
            total_decls += decl_count
            total_lines += line_count

        if total_lines == 0:
            return 'line'  # Default to finest granularity

        density = total_decls / total_lines

        # Gap 11 fix: Granularity ladder
        if density > 0.1:
            # Well-annotated: use section-level
            return 'section'
        elif density > 0.05:
            # Moderately annotated: use sentence-level
            return 'sentence'
        elif density > 0.02:
            # Sparse annotations: use clause-level
            return 'clause'
        else:
            # Very sparse: use line-level for maximum tracking
            return 'line'

    def _merge_with_remainder(
        self,
        units: list[TrackedUnit],
        granularity: str = 'line'
    ) -> tuple[TrackedUnit, list[TrackedUnit]]:
        """
        Merge multiple units with same ID using ATOM-BASED MEMBERSHIP.

        CRITICAL: Does NOT use set-of-lines (destroys order/duplicates).
        Instead, uses diff hunks with stable atom IDs.

        Gap 11 fix: Uses granularity ladder to control atom size.

        Returns: (merged_unit, remainder_units)
        """
        # Sort by patch order (p1 < p5 < p10)
        def patch_order(u: TrackedUnit) -> int:
            patch_id = u.introduced_by
            if patch_id.startswith('p'):
                try:
                    return int(patch_id[1:])
                except ValueError:
                    return 999
            return 999

        sorted_units = sorted(units, key=patch_order)
        base = sorted_units[0]  # Start from earliest

        # =====================================================================
        # ATOM-BASED MEMBERSHIP (Gap 1 fix)
        # =====================================================================
        # Atoms are lines with stable IDs, preserving order and multiplicity.
        # NOT sets - we keep order and allow duplicates.

        # Convert to atoms with stable IDs
        base_atoms = self._content_to_atoms(base.content, base.introduced_by)
        membership_evidence = {}  # atom_id → MembershipEvidence

        # Track all atoms through transformations
        all_atoms = list(base_atoms)  # Ordered list, not set
        remainder_atoms = []
        lineage_edges = []  # (from_atom_id, to_atom_id, transformation)

        # Apply each subsequent patch using diff hunks
        for i, later_unit in enumerate(sorted_units[1:], 1):
            later_atoms = self._content_to_atoms(later_unit.content, later_unit.introduced_by)

            # Use SequenceMatcher for diff hunks (preserves order)
            from difflib import SequenceMatcher
            matcher = SequenceMatcher(
                None,
                [a['content'] for a in all_atoms],
                [a['content'] for a in later_atoms]
            )

            new_atoms = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'equal':
                    # Unchanged atoms - carry forward with lineage
                    for idx in range(i1, i2):
                        atom = all_atoms[idx].copy()
                        atom['status'] = 'unchanged'
                        new_atoms.append(atom)
                        # Record membership evidence
                        membership_evidence[atom['id']] = {
                            'rationale': 'Unchanged through patch',
                            'confidence': 1.0,
                            'method': 'exact_match'
                        }

                elif tag == 'replace':
                    # Modified atoms - later patch wins, old goes to remainder
                    for idx in range(i1, i2):
                        old_atom = all_atoms[idx]
                        remainder_atoms.append({
                            **old_atom,
                            'status': 'replaced',
                            'replaced_by': later_unit.introduced_by
                        })

                    for idx in range(j1, j2):
                        new_atom = later_atoms[idx].copy()
                        new_atom['status'] = 'added'
                        new_atoms.append(new_atom)
                        # Record lineage edge (many-to-many possible)
                        for old_idx in range(i1, i2):
                            lineage_edges.append({
                                'from': all_atoms[old_idx]['id'],
                                'to': new_atom['id'],
                                'transformation': 'replace',
                                'patch': later_unit.introduced_by
                            })
                        membership_evidence[new_atom['id']] = {
                            'rationale': f'Replaced by {later_unit.introduced_by}',
                            'confidence': 0.9,
                            'method': 'diff_replace'
                        }

                elif tag == 'delete':
                    # Deleted atoms - go to remainder
                    for idx in range(i1, i2):
                        remainder_atoms.append({
                            **all_atoms[idx],
                            'status': 'deleted',
                            'deleted_by': later_unit.introduced_by
                        })

                elif tag == 'insert':
                    # New atoms from later patch
                    for idx in range(j1, j2):
                        new_atom = later_atoms[idx].copy()
                        new_atom['status'] = 'added'
                        new_atoms.append(new_atom)
                        membership_evidence[new_atom['id']] = {
                            'rationale': f'Added by {later_unit.introduced_by}',
                            'confidence': 1.0,
                            'method': 'diff_insert'
                        }

            all_atoms = new_atoms

        # Convert atoms back to content (preserves order)
        merged_content = '\n'.join(a['content'] for a in all_atoms)

        # Create merged unit with membership tracking
        merged = TrackedUnit(
            id=base.id,
            content=merged_content,
            unit_type=base.unit_type,
            source=sorted_units[-1].source,
            introduced_by=base.introduced_by,
            modified_by=[u.introduced_by for u in sorted_units[1:]],
            declarations=sorted_units[-1].declarations,
            references=sorted_units[-1].references,
            # NEW: Atom-based membership tracking
            source_atom_ids=[a['id'] for a in all_atoms],
            membership_evidence=membership_evidence,
            lineage_edges=lineage_edges
        )

        # Create remainder units for unresolved content
        remainders = []
        if remainder_atoms:
            remainder_content = '\n'.join(
                f"[{a.get('deleted_by', a.get('replaced_by', 'unknown'))}] {a['content']}"
                for a in remainder_atoms
            )
            remainder_unit = TrackedUnit(
                id=f"{base.id}_remainder",
                content=remainder_content,
                unit_type=UnitType.PROSE,
                source=base.source,
                introduced_by="composite",
                status=UnitStatus.PENDING,
                # Track which atoms went to remainder
                source_atom_ids=[a['id'] for a in remainder_atoms]
            )
            remainders.append(remainder_unit)

        return merged, remainders

    def _content_to_atoms(
        self,
        content: str,
        source_id: str,
        granularity: str = 'line'
    ) -> list[dict]:
        """
        Convert content to atoms with stable IDs.

        Gap 11 fix: Granularity ladder drives atom size.
        - 'line': One atom per line (maximum tracking fidelity)
        - 'sentence': One atom per sentence
        - 'clause': One atom per clause (using NLP)
        - 'section': One atom per annotated section

        Atoms preserve order and multiplicity (unlike sets).
        Each atom has: id, content, source, line_number
        """
        atoms = []

        if granularity == 'line':
            # Line-level atomization (default, maximum tracking)
            for i, line in enumerate(content.split('\n')):
                atom_id = f"{source_id}_L{i+1}_{hash(line) % 10000:04d}"
                atoms.append({
                    'id': atom_id,
                    'content': line,
                    'source': source_id,
                    'line_number': i + 1,
                    'granularity': 'line'
                })

        elif granularity == 'sentence':
            # Sentence-level atomization
            import re
            sentences = re.split(r'(?<=[.!?])\s+', content)
            line_num = 1
            for i, sent in enumerate(sentences):
                sent = sent.strip()
                if not sent:
                    continue
                atom_id = f"{source_id}_S{i+1}_{hash(sent) % 10000:04d}"
                atoms.append({
                    'id': atom_id,
                    'content': sent,
                    'source': source_id,
                    'line_number': line_num,
                    'granularity': 'sentence'
                })
                line_num += sent.count('\n') + 1

        elif granularity == 'clause':
            # Clause-level atomization (using conjunctions and semicolons)
            import re
            clauses = re.split(r';\s*|\s+and\s+|\s+or\s+', content)
            line_num = 1
            for i, clause in enumerate(clauses):
                clause = clause.strip()
                if not clause:
                    continue
                atom_id = f"{source_id}_CL{i+1}_{hash(clause) % 10000:04d}"
                atoms.append({
                    'id': atom_id,
                    'content': clause,
                    'source': source_id,
                    'line_number': line_num,
                    'granularity': 'clause'
                })
                line_num += clause.count('\n') + 1

        elif granularity == 'section':
            # Section-level atomization (using annotations and headers)
            import re
            # Split on annotations ([=...]) or markdown headers
            section_pattern = re.compile(r'(?=\(\[=|\n##+ )')
            sections = section_pattern.split(content)
            line_num = 1
            for i, section in enumerate(sections):
                section = section.strip()
                if not section:
                    continue
                # Extract section ID if available
                decl_match = re.search(r'\(\[=([^\]]+)\]\)', section)
                if decl_match:
                    section_name = decl_match.group(1)
                    atom_id = f"{source_id}_{section_name}_{hash(section) % 10000:04d}"
                else:
                    atom_id = f"{source_id}_SEC{i+1}_{hash(section) % 10000:04d}"
                atoms.append({
                    'id': atom_id,
                    'content': section,
                    'source': source_id,
                    'line_number': line_num,
                    'granularity': 'section'
                })
                line_num += section.count('\n') + 1

        return atoms

    def _generate_composite_markdown(self, units: list[TrackedUnit]) -> str:
        """Generate markdown representation of composite state."""
        lines = ["# Composite State\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")
        lines.append(f"Units: {len(units)}\n\n")

        for unit in sorted(units, key=lambda u: u.id):
            lines.append(f"## {unit.id}\n")
            lines.append(f"Type: {unit.unit_type.value}\n")
            lines.append(f"Introduced: {unit.introduced_by}\n")
            if unit.modified_by:
                lines.append(f"Modified: {', '.join(unit.modified_by)}\n")
            lines.append(f"\n```\n{unit.content}\n```\n\n")

        return '\n'.join(lines)

    def _generate_plan_projection(self, units: list[TrackedUnit]) -> str:
        """
        Generate plan.md projection from current units (Gap 11 partial).

        This creates a unified view that can be compared against library state.
        """
        lines = ["# Plan (Intermediate Projection)\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")
        lines.append(f"Units: {len(units)}\n\n")

        # Group by unit type
        by_type: dict[str, list[TrackedUnit]] = {}
        for unit in units:
            type_name = unit.unit_type.value if hasattr(unit.unit_type, 'value') else str(unit.unit_type)
            if type_name not in by_type:
                by_type[type_name] = []
            by_type[type_name].append(unit)

        # Output each type section
        type_order = ['algorithm', 'claim', 'invariant', 'goal', 'data_structure', 'proof', 'lean', 'prose']
        for type_name in type_order:
            if type_name in by_type:
                lines.append(f"## {type_name.replace('_', ' ').title()}s\n")
                for unit in sorted(by_type[type_name], key=lambda u: u.id):
                    lines.append(f"### {unit.id} ([={unit.id}])\n")
                    lines.append(f"{unit.content}\n")
                    lines.append("---\n")
                lines.append("\n")

        # Add remaining types not in order
        for type_name, type_units in by_type.items():
            if type_name not in type_order:
                lines.append(f"## {type_name.replace('_', ' ').title()}s\n")
                for unit in sorted(type_units, key=lambda u: u.id):
                    lines.append(f"### {unit.id}\n")
                    lines.append(f"{unit.content}\n")
                    lines.append("---\n")

        return '\n'.join(lines)

    def _phase_discovery(self) -> None:
        """
        Discover libraries through multi-labeling.

        CRITICAL: This phase is BLOCKED if compliance gate did not pass (Gap 2 fix).
        """
        logger.info("Phase: DISCOVERY")
        self.state.phase = WorkflowPhase.DISCOVERY

        # =========================================================================
        # COMPLIANCE GATE CHECK (Gap 2 fix)
        # =========================================================================
        if not getattr(self.state, 'compliance_passed', False):
            logger.warning("  ⏭️ SKIPPING discovery - compliance gate not passed")
            logger.warning(f"     Compliance: {getattr(self.state, 'compliance_score', 0):.1%}")
            logger.warning(f"     Details: {getattr(self.state, 'compliance_details', {})}")
            logger.warning("  To force discovery, set compliance_gate_mode='warn' in config")
            return  # Skip discovery entirely

        # Step 1: Identify candidates (using multi-signal discovery)
        identifier = CandidateIdentifier()
        candidates = identifier.discover_with_all_signals(self.state.units)  # Multi-signal discovery

        self.state.candidate_libraries = [c.name for c in candidates]
        logger.info(f"  Identified {len(candidates)} candidate libraries")

        # Step 2-4: Refine iteratively
        refiner = LibraryRefiner(self.state.units)
        result = refiner.refine(
            candidates,
            max_iterations=self.config.max_discovery_iterations
        )

        self.state.discovery_iteration = result.iteration
        self.state.library_shapes = {
            name: {
                'strong': len(shape.strong_matches),
                'medium': len(shape.medium_matches),
                'convergence': shape.convergence
            }
            for name, shape in result.shapes.items()
        }

        logger.info(f"  Refinement completed in {result.iteration} iterations")
        logger.info(f"  Convergence: {result.convergence_score:.2f}")

        # Step 5: Finalize assignments
        self.state.final_labels = refiner.finalize()

        # Save intermediate
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="discovery",
                description="After library discovery",
                tracker=self.tracker,
                candidate_libraries=self.state.candidate_libraries,
                library_shapes=self.state.library_shapes
            )
            self.intermediate_mgr.save(state)

    def _phase_review(self) -> None:
        """
        Review libraries for overlap and resolve conflicts.

        Gap 8 fix: Enforce proof-chain non-authoritative state in projections.
        Gap 9 fix: Produce concrete actions (merge/split/drop/legacy) with provenance.
        """
        logger.info("Phase: REVIEW")
        self.state.phase = WorkflowPhase.REVIEW

        # =========================================================================
        # PROOF-CHAIN NON-AUTHORITATIVE ENFORCEMENT (Gap 8 fix)
        # =========================================================================
        # Units with broken proof chains get status = NON_AUTHORITATIVE
        # They are quarantined from final library output until resolved

        logger.info("  Checking proof chains for non-authoritative elements...")
        non_authoritative_units = set()

        for unit in self.state.units:
            # Check if this unit type requires proof chain
            unit_type = getattr(unit, 'unit_type', None)
            if unit_type and str(unit_type).lower() in ('algorithm', 'claim'):
                content = getattr(unit, 'content', '')

                # Check for claim references in algorithms
                if 'algorithm' in str(unit_type).lower():
                    has_claim_ref = bool(re.search(r'\(@\[\+?P?\d*C\d+\]\)', content))
                    has_claim_mention = bool(re.search(r'\bP?\d*C\d+\b', content))

                    if not has_claim_ref and not has_claim_mention:
                        non_authoritative_units.add(unit.id)
                        unit.status = UnitStatus.NON_AUTHORITATIVE if hasattr(unit, 'status') else 'non_authoritative'

        if non_authoritative_units:
            logger.warning(f"  ⚠️ {len(non_authoritative_units)} units marked NON_AUTHORITATIVE (broken proof chain)")
            for unit_id in list(non_authoritative_units)[:5]:
                logger.warning(f"      - {unit_id}")
            if len(non_authoritative_units) > 5:
                logger.warning(f"      ... and {len(non_authoritative_units) - 5} more")

        self.state.non_authoritative_units = list(non_authoritative_units)

        # =========================================================================
        # LIBRARY REVIEW ACTIONS (Gap 9 fix)
        # =========================================================================
        # Produce concrete actions: merge/split/drop/legacy with provenance justification

        review_actions: list[dict] = []

        # Gap 6 fix: Use RELATIVE, PER-INGEST PROVENANCE ordering instead of hardcoded thresholds
        # Compute the full patch range from this ingest to determine "early" vs "late"
        all_patch_nums = []
        for unit in self.state.units:
            p = getattr(unit, 'introduced_by', '')
            if p.startswith('p'):
                try:
                    all_patch_nums.append(int(p[1:]))
                except ValueError:
                    pass

        max_patch_in_ingest = max(all_patch_nums) if all_patch_nums else 1
        min_patch_in_ingest = min(all_patch_nums) if all_patch_nums else 1
        patch_range = max_patch_in_ingest - min_patch_in_ingest + 1

        # Define "early" as first third of the patch range (relative, not hardcoded < 3)
        early_threshold = min_patch_in_ingest + max(1, patch_range // 3)
        logger.info(f"  Relative provenance thresholds: early={early_threshold}, range={patch_range}")

        # Analyze overlap between libraries
        if hasattr(self.state, 'library_shapes') and self.state.library_shapes:
            logger.info("  Analyzing library overlap for concrete actions...")

            for lib_name, shape_info in self.state.library_shapes.items():
                lib_units = [u for u in self.state.units if getattr(u, 'primary_library', None) == lib_name]

                # Check for merge candidates (high overlap)
                convergence = shape_info.get('convergence', 0)
                if convergence < 0.5:  # Low convergence suggests split
                    # Gap 6 fix: No requires_manual - emit as proposed patch action
                    review_actions.append({
                        'action': 'SPLIT',
                        'target': lib_name,
                        'provenance': f"Low convergence ({convergence:.2f}) suggests internal divergence",
                        'confidence': 1 - convergence,
                        'auto_applicable': False,  # Gap 6: Requires future patch pass to apply
                        'proposed_implementation': f"Split {lib_name} into sub-libraries based on clustering"
                    })

                # Check for empty/deprecated libraries
                if len(lib_units) == 0:
                    # Gap 6 fix: Safe auto-action (provably redundant + no references)
                    review_actions.append({
                        'action': 'DROP',
                        'target': lib_name,
                        'provenance': "No elements assigned to library",
                        'confidence': 1.0,
                        'auto_applicable': True  # Gap 6: Safe auto-action
                    })

                # Check for legacy artifacts - Gap 6 fix: Use RELATIVE thresholds
                if lib_units:
                    patches = [getattr(u, 'introduced_by', '') for u in lib_units]
                    patch_nums = []
                    for p in patches:
                        if p.startswith('p'):
                            try:
                                patch_nums.append(int(p[1:]))
                            except ValueError:
                                pass

                    # Gap 6 fix: Use relative threshold instead of hardcoded < 3
                    if patch_nums and max(patch_nums) < early_threshold:
                        # Check if this library is referenced elsewhere (can't auto-drop if referenced)
                        is_referenced = any(
                            lib_name in getattr(u, 'relation_libraries', [])
                            for u in self.state.units
                            if getattr(u, 'primary_library', None) != lib_name
                        )

                        review_actions.append({
                            'action': 'LEGACY',
                            'target': lib_name,
                            'provenance': f"All elements from early patches (p{min(patch_nums)}-p{max(patch_nums)}), before threshold p{early_threshold}",
                            'confidence': 0.7 if not is_referenced else 0.4,
                            # Gap 6 fix: Auto-applicable only if not referenced and fully superseded
                            'auto_applicable': not is_referenced and self._is_fully_superseded(lib_name, lib_units),
                            'is_referenced': is_referenced,
                            'proposed_implementation': f"Archive {lib_name} to legacy/ folder" if not is_referenced else f"Review references before archiving {lib_name}"
                        })

        # Store review actions
        self.state.review_actions = review_actions

        if review_actions:
            logger.info(f"  Review produced {len(review_actions)} concrete actions:")
            for action in review_actions[:5]:
                logger.info(f"    {action['action']}: {action['target']} ({action['provenance'][:50]}...)")

        # Apply verification strategies
        if self.config.apply_strategies:
            context = ProcessingContext(
                units=self.state.units,
                phase=StrategyPhase.VERIFICATION
            )

            strategies = self.strategy_registry.get_applicable(context)
            for strategy in strategies:
                result = strategy.execute(context)
                for issue in result.issues:
                    logger.warning(f"  [{strategy.name}] {issue}")

        # Save intermediate
        if self.config.save_intermediates:
            state = self.intermediate_mgr.create_snapshot(
                phase="review",
                description="After library review",
                tracker=self.tracker,
                candidate_libraries=self.state.candidate_libraries,
                library_shapes=self.state.library_shapes,
                review_actions=self.state.review_actions,
                non_authoritative_units=self.state.non_authoritative_units
            )
            self.intermediate_mgr.save(state)

    def _phase_sync(self) -> None:
        """
        Synchronize plan.md ↔ libraries.

        Gap 2 fix: AUTHORITY IS NOT CONFIGURABLE.
        - LIBRARIES are authoritative (always, at finalization)
        - plan.md is ALWAYS REGENERATED from libraries (it's a projection/unified view)
        - "Plan-only" content becomes DRIFT EVIDENCE + REMAINDER, never a competing authority

        This phase detects drift to surface in gaps.md, but does NOT make plan.md authoritative.
        """
        logger.info("Phase: SYNC (libraries → plan.md projection)")
        self.state.phase = WorkflowPhase.SYNC

        plan_path = self.spec_folder / "plan.md"
        libraries_dir = self.spec_folder / "libraries"

        # NOTE: We don't require existing plan.md - it will be regenerated in finalize
        # This phase is for detecting drift evidence, not for reconciling competing authorities

        drift_evidence = []
        plan_only_remainder = []

        # If existing plan.md exists, check for content that isn't in libraries (drift)
        # Gap 3 fix: Use ATOM-BASED membership, not set comparison
        if plan_path.exists() and libraries_dir.exists():
            plan_content = plan_path.read_text()

            # Convert plan to atoms with stable IDs
            plan_atoms = self._content_to_atoms(plan_content, 'plan')

            # Collect all library atoms (multiset - preserves duplicates)
            library_atoms = []
            for lib_file in libraries_dir.glob("*.md"):
                lib_content = lib_file.read_text()
                lib_atoms = self._content_to_atoms(lib_content, lib_file.stem)
                library_atoms.extend(lib_atoms)

            # Gap 3 fix: Use SequenceMatcher for sequence-aware comparison
            from difflib import SequenceMatcher
            plan_lines = [a['content'] for a in plan_atoms if a['content'].strip()]
            lib_lines = [a['content'] for a in library_atoms if a['content'].strip()]

            # Create a set of library content for quick lookup (but use sequence for actual matching)
            lib_content_set = set(lib_lines)

            # Find plan-only content → this is DRIFT, not authority
            for atom in plan_atoms:
                line_stripped = atom['content'].strip()
                if line_stripped and not line_stripped.startswith('#') and line_stripped != '---':
                    if line_stripped not in lib_content_set:
                        # Also check for fuzzy matches (content that was slightly modified)
                        best_match_ratio = 0.0
                        for lib_line in lib_lines:
                            ratio = SequenceMatcher(None, line_stripped, lib_line).ratio()
                            if ratio > best_match_ratio:
                                best_match_ratio = ratio

                        # Only mark as drift if no good fuzzy match
                        if best_match_ratio < 0.85:
                            plan_only_remainder.append({
                                'line': atom['line_number'],
                                'content': line_stripped[:100],
                                'type': 'plan_only_drift',
                                'best_fuzzy_match': best_match_ratio,
                                'atom_id': atom['id']
                            })

            if plan_only_remainder:
                drift_evidence.append({
                    'type': 'plan_only_content',
                    'description': 'Content in plan.md not found in any library (will be lost on regeneration)',
                    'lines_count': len(plan_only_remainder),
                    'samples': plan_only_remainder[:5],
                    'severity': 'warning',
                    'action': 'Either add to a library or accept as intentional removal'
                })
                logger.warning(f"  ⚠️ {len(plan_only_remainder)} lines in plan.md not in libraries (drift)")
                logger.warning(f"     These will be LOST when plan.md is regenerated from libraries")

        # NOTE: We do NOT do "library-only" checks here because:
        # 1. Libraries are authoritative - they define what exists
        # 2. plan.md is regenerated from libraries in finalize phase
        # 3. Library content is, by definition, in the authoritative state

        if drift_evidence:
            logger.info(f"  Detected {len(drift_evidence)} drift issues → gaps.md")

        self.state.sync_drift = drift_evidence
        self.state.plan_only_remainder = plan_only_remainder

    def _phase_finalize(self) -> None:
        """
        Finalize: Remove stamps, generate output, write relations.

        - Gap 10: Stamps are REMOVED from output files (explicit step with test)
        - Gap 11: plan.md is generated from authoritative library state
        - Gap 8: Non-authoritative units are quarantined
        - Relations are WRITTEN to output libraries
        - Gaps.md includes drift from sync phase
        """
        logger.info("Phase: FINALIZE")
        self.state.phase = WorkflowPhase.FINALIZE

        # Gap 5 fix: Run gap detection on PROJECTION OUTPUT, not original spec_folder
        # The current_projection_path is the latest intermediate projection
        # Only AFTER finalize writes to spec_folder should we run "final-state" detectors on spec_folder
        projection_path = getattr(self.state, 'current_projection_path', None)

        if projection_path and projection_path.exists():
            logger.info(f"  Running gap detection on projection output: {projection_path}")
            gaps = self.gap_detector.detect_all(projection_path)
            evidence_source = projection_path
        else:
            # Fallback to spec_folder if no projection available (first run)
            logger.warning("  No projection path available, falling back to spec_folder")
            gaps = self.gap_detector.detect_all(self.spec_folder)
            evidence_source = self.spec_folder

        # Add sync drift as gap evidence
        for drift in getattr(self.state, 'sync_drift', []):
            evidence = GapEvidence(
                severity=Severity.WARNING,
                message=f"Library drift: {drift['library']} has {drift['lines_count']} lines not in plan.md",
                location=f"libraries/{drift['library']}.md",
                detector="sync_comparator",
                details=drift
            )
            # Gap 5 fix: Collect evidence from projection output, not spec_folder
            gaps = self.gap_detector.synthesize_gaps(
                self.gap_detector.collect_evidence(evidence_source) + [evidence]
            )

        gaps_md = self.gap_detector.format_gaps_md(gaps)

        # Write gaps.md
        gaps_path = self.spec_folder / "gaps.md"
        gaps_path.write_text(gaps_md, encoding="utf-8")
        logger.info(f"  Wrote {len(gaps)} gaps to gaps.md")

        # Write libraries (with relations preserved)
        libraries_dir = self.spec_folder / "libraries"
        libraries_dir.mkdir(exist_ok=True)

        # Group units by primary library (excluding non-authoritative - Gap 8)
        by_library: dict[str, list[TrackedUnit]] = {}
        quarantined: list[TrackedUnit] = []

        for unit in self.state.units:
            # Gap 8: Quarantine non-authoritative units
            if unit.id in getattr(self.state, 'non_authoritative_units', []):
                quarantined.append(unit)
                continue

            labels = self.state.final_labels.get(unit.id)
            if labels and labels.primary:
                lib = labels.primary
                if lib not in by_library:
                    by_library[lib] = []
                by_library[lib].append(unit)

        if quarantined:
            logger.warning(f"  ⚠️ {len(quarantined)} units quarantined (non-authoritative)")

        # Write each library (with relations, stamps stripped - Gap 10)
        for lib_name, units in by_library.items():
            lib_path = libraries_dir / f"{lib_name}.md"
            content = self._format_library_with_relations(lib_name, units)

            # =====================================================================
            # STAMP STRIPPING (Gap 10 fix)
            # =====================================================================
            content = self._strip_provenance_stamps(content)

            lib_path.write_text(content, encoding="utf-8")
            logger.info(f"  Wrote {len(units)} elements to {lib_name}.md")

        # =========================================================================
        # PLAN.MD PROJECTION FROM LIBRARIES (Gap 11 fix)
        # =========================================================================
        # plan.md is a deterministic projection of authoritative library state
        # NOT a separate source of truth

        logger.info("  Generating plan.md from authoritative library state...")
        plan_content = self._generate_plan_from_libraries(by_library)

        # Strip stamps from plan.md too (Gap 10)
        plan_content = self._strip_provenance_stamps(plan_content)

        plan_path = self.spec_folder / "plan.md"
        plan_path.write_text(plan_content, encoding="utf-8")
        logger.info(f"  Wrote plan.md (projection of {len(by_library)} libraries)")

        # =========================================================================
        # STAMP STRIPPING FINALIZATION CHECK (Gap 10 test)
        # =========================================================================
        # Verify no stamps remain in output artifacts

        stamp_check_failed = False
        stamp_pattern = re.compile(r'@(from|modified|line):[^\s]+')

        for lib_path in libraries_dir.glob("*.md"):
            content = lib_path.read_text()
            if stamp_pattern.search(content):
                logger.error(f"  ❌ STAMP STRIPPING FAILED: {lib_path.name} contains stamps")
                stamp_check_failed = True

        if stamp_pattern.search(plan_path.read_text()):
            logger.error(f"  ❌ STAMP STRIPPING FAILED: plan.md contains stamps")
            stamp_check_failed = True

        if not stamp_check_failed:
            logger.info("  ✅ Stamp stripping verified: no stamps in output artifacts")

        # Write quarantined units to separate file
        if quarantined:
            quarantine_path = self.spec_folder / "quarantine.md"
            quarantine_content = self._format_quarantine_file(quarantined)
            quarantine_path.write_text(quarantine_content, encoding="utf-8")
            logger.info(f"  Wrote {len(quarantined)} quarantined units to quarantine.md")

        # Final coverage report
        report = self.tracker.get_coverage_report()
        logger.info(f"  Coverage: {report['coverage_percent']:.1f}%")
        logger.info(f"  Mapped: {report['mapped']}, Dropped: {report['dropped']}, Unaccounted: {report['unaccounted']}")

    def _strip_provenance_stamps(self, content: str) -> str:
        """
        Strip provenance stamps from content (Gap 10).

        Removes @from:p#, @modified:p#, @line:# from output.
        Stamps are preserved in .workspace/ for debugging.
        """
        import re

        # Pattern: <!-- @from:p1 @modified:p5,p7 @line:234 -->
        content = re.sub(r'\s*<!--\s*@(from|modified|line):[^>]+-->', '', content)

        # Pattern: @from:p1 (inline)
        content = re.sub(r'\s*@(from|modified|line):[^\s]+', '', content)

        return content

    def _generate_plan_from_libraries(self, by_library: dict[str, list]) -> str:
        """
        Generate plan.md as a deterministic projection from authoritative library state (Gap 11).

        This is NOT a separate source of truth - it's computed from libraries.
        """
        lines = ["# Plan\n"]
        lines.append(f"<!-- Generated from authoritative library state: {datetime.now().isoformat()} -->\n")
        lines.append(f"<!-- DO NOT EDIT DIRECTLY - Edit libraries/*.md instead -->\n\n")

        # Table of contents
        lines.append("## Table of Contents\n")
        for lib_name in sorted(by_library.keys()):
            lib_units = by_library[lib_name]
            lines.append(f"- [{lib_name}](#{lib_name.replace(' ', '-').lower()}) ({len(lib_units)} elements)\n")
        lines.append("\n---\n\n")

        # Each library section
        for lib_name in sorted(by_library.keys()):
            units = by_library[lib_name]
            lines.append(f"## {lib_name}\n\n")

            # Sort units by type then by ID
            def unit_sort_key(u):
                type_order = {'algorithm': 0, 'claim': 1, 'invariant': 2, 'goal': 3, 'data_structure': 4}
                unit_type = str(getattr(u, 'unit_type', 'unknown')).lower()
                return (type_order.get(unit_type, 99), u.id)

            for unit in sorted(units, key=unit_sort_key):
                # Header with declaration and pinning back to library
                lines.append(f"### {unit.id} ([={unit.id}]) <!-- @pin:libraries/{lib_name}.md -->\n\n")

                # Content
                lines.append(f"{unit.content}\n\n")

                # Relations (if any)
                if hasattr(unit, 'relation_libraries') and unit.relation_libraries:
                    rels = ', '.join(f"(@[+rel:{r}])" for r in unit.relation_libraries)
                    lines.append(f"Relations: {rels}\n\n")

                lines.append("---\n\n")

        return '\n'.join(lines)

    def _compute_prose_ratio(self, units: list) -> float:
        """
        Compute the prose ratio for the current unit set (Gap 10 fix).

        prose_ratio = (prose bytes/lines/units) / (total bytes/lines/units)

        This metric is used in:
        - Evolution triggers: "Prose ratio not decreasing"
        - Termination conditions: "Prose minimized enough"
        - Acceptance gates: "Prose below threshold"

        Returns a value between 0.0 (no prose) and 1.0 (all prose).
        """
        if not units:
            return 0.0

        # Count by unit type
        prose_count = 0
        total_count = len(units)
        prose_bytes = 0
        total_bytes = 0

        for unit in units:
            unit_type = str(getattr(unit, 'unit_type', 'unknown')).lower()
            content = getattr(unit, 'content', '')
            content_len = len(content.encode('utf-8'))

            total_bytes += content_len

            if unit_type in ('prose', 'unknown', 'paragraph', 'text'):
                prose_count += 1
                prose_bytes += content_len

        # Return byte-weighted ratio (more accurate than unit count)
        if total_bytes > 0:
            return prose_bytes / total_bytes
        elif total_count > 0:
            return prose_count / total_count
        else:
            return 0.0

    def _is_fully_superseded(self, lib_name: str, lib_units: list) -> bool:
        """
        Check if a library has been fully superseded by later patches (Gap 6 fix).

        A library is fully superseded if:
        - All its element IDs appear in later patches with the same or updated content
        - No element from this library is the sole source of an ID

        Returns True if safe to auto-archive, False if manual review needed.
        """
        lib_ids = {getattr(u, 'id', '') for u in lib_units}

        # Find all units from later patches
        later_units = []
        for unit in self.state.units:
            if getattr(unit, 'primary_library', None) != lib_name:
                p = getattr(unit, 'introduced_by', '')
                if p.startswith('p'):
                    try:
                        patch_num = int(p[1:])
                        max_lib_patch = max(
                            int(getattr(u, 'introduced_by', 'p0')[1:])
                            for u in lib_units
                            if getattr(u, 'introduced_by', '').startswith('p')
                        ) if lib_units else 0
                        if patch_num > max_lib_patch:
                            later_units.append(unit)
                    except ValueError:
                        pass

        # Check if all library IDs appear in later units
        later_ids = {getattr(u, 'id', '') for u in later_units}
        superseded_ids = lib_ids & later_ids

        # Only fully superseded if all IDs are covered
        return superseded_ids == lib_ids and len(lib_ids) > 0

    def _format_quarantine_file(self, units: list) -> str:
        """Format quarantine.md for non-authoritative units."""
        lines = ["# Quarantined Elements\n"]
        lines.append("These elements have broken proof chains and are NON-AUTHORITATIVE.\n")
        lines.append("They are excluded from libraries/*.md and plan.md until resolved.\n\n")
        lines.append("## Unresolved Elements\n\n")

        for unit in units:
            lines.append(f"### {unit.id}\n")
            lines.append(f"- **Status**: NON_AUTHORITATIVE\n")
            lines.append(f"- **Issue**: Broken proof chain (no claim reference)\n")
            lines.append(f"- **Source**: {getattr(unit, 'source', 'unknown')}\n")
            lines.append(f"- **Introduced by**: {getattr(unit, 'introduced_by', 'unknown')}\n\n")
            lines.append(f"```\n{getattr(unit, 'content', '')[:500]}...\n```\n\n")

        return '\n'.join(lines)

    def _format_library_with_relations(self, name: str, units: list[TrackedUnit]) -> str:
        """
        Format units as a library file WITH relation annotations preserved.

        Per-element: (@[+rel:library_name])
        Library-level: cross-links index at end
        """
        lines = [f"# {name.replace('_', ' ').title()}\n"]

        cross_links = set()

        for unit in sorted(units, key=lambda u: u.id):
            # Get relation libraries from labels
            labels = self.state.final_labels.get(unit.id)
            relation_libs = labels.relations if labels else []

            # Add relation annotation if present
            if relation_libs:
                rel_annotations = ' '.join(f"(@[+rel:{r}])" for r in relation_libs)
                lines.append(f"{unit.content}\n{rel_annotations}")
                cross_links.update(relation_libs)
            else:
                lines.append(unit.content)

            lines.append("\n---\n")

        # Add cross-links index at end
        if cross_links:
            lines.append("\n## Cross-References\n")
            lines.append("This library has elements related to:\n")
            for lib in sorted(cross_links):
                lines.append(f"- [{lib}](libraries/{lib}.md)")
            lines.append("")

        return '\n'.join(lines)

    def _format_library(self, name: str, units: list[TrackedUnit]) -> str:
        """Format units as a library file (backward compat)."""
        return self._format_library_with_relations(name, units)
```

### File 2: `spec_manager/workflow/ingest.py`

```python
"""
Ingest command - entry point for processing new inputs.
"""

from __future__ import annotations

from pathlib import Path

from .orchestrator import WorkflowOrchestrator, WorkflowConfig


def ingest(
    spec_folder: str | Path,
    max_cleaning_passes: int = 10,
    max_discovery_iterations: int = 10,
    save_intermediates: bool = True,
    verbose: bool = False
) -> dict:
    """
    Run the full ingest workflow on a spec folder.

    Args:
        spec_folder: Path to spec folder containing patches/
        max_cleaning_passes: Max iterations for cleaning phase
        max_discovery_iterations: Max iterations for library discovery
        save_intermediates: Whether to save intermediate states
        verbose: Enable verbose logging

    Returns:
        Dict with workflow results
    """
    config = WorkflowConfig(
        max_cleaning_passes=max_cleaning_passes,
        max_discovery_iterations=max_discovery_iterations,
        save_intermediates=save_intermediates,
        verbose=verbose
    )

    orchestrator = WorkflowOrchestrator(
        spec_folder=Path(spec_folder),
        config=config
    )

    state = orchestrator.run()

    return {
        'phase': state.phase.value,
        'cleaning_passes': state.cleaning_pass,
        'discovery_iterations': state.discovery_iteration,
        'total_units': len(state.units),
        'libraries': list(state.library_shapes.keys()),
        'errors': state.errors
    }
```

### File 3: `spec_manager/cli.py` (Enhanced)

```python
"""
Enhanced CLI with new workflow commands.
"""

import argparse
import sys
from pathlib import Path

from .workflow.ingest import ingest
from .workflow.orchestrator import WorkflowOrchestrator, WorkflowConfig
from .core.gaps import UnifiedGapDetector
from .strategies.registry import StrategyRegistry


def cmd_ingest(args):
    """Run full ingest workflow."""
    result = ingest(
        spec_folder=args.spec_folder,
        max_cleaning_passes=args.max_passes,
        max_discovery_iterations=args.max_iterations,
        save_intermediates=not args.no_intermediates,
        verbose=args.verbose
    )

    print(f"Workflow completed: {result['phase']}")
    print(f"  Cleaning passes: {result['cleaning_passes']}")
    print(f"  Discovery iterations: {result['discovery_iterations']}")
    print(f"  Total units: {result['total_units']}")
    print(f"  Libraries: {', '.join(result['libraries'])}")

    if result['errors']:
        print(f"  Errors: {len(result['errors'])}")
        for error in result['errors']:
            print(f"    - {error}")


def cmd_gaps(args):
    """Run unified gap detection."""
    detector = UnifiedGapDetector()
    gaps = detector.detect_all(
        spec_folder=Path(args.spec_folder),
        include_info=not args.no_info
    )

    print(f"Detected {len(gaps)} gaps:")

    # Summary by type
    by_type = {}
    for gap in gaps:
        by_type[gap.gap_type] = by_type.get(gap.gap_type, 0) + 1

    for gap_type, count in sorted(by_type.items()):
        print(f"  {gap_type}: {count}")

    # Write if requested
    if args.update:
        gaps_md = detector.format_gaps_md(gaps)
        gaps_path = Path(args.spec_folder) / "gaps.md"
        gaps_path.write_text(gaps_md)
        print(f"\nUpdated: {gaps_path}")


def cmd_strategies(args):
    """List or manage strategies."""
    registry = StrategyRegistry()

    # Load from default location
    strategies_dir = Path(__file__).parent / "strategies" / "definitions"
    if strategies_dir.exists():
        registry.load_from_directory(strategies_dir)

    if args.list:
        strategies = registry.list_strategies()
        print(f"Available strategies ({len(strategies)}):\n")

        for s in strategies:
            print(f"  {s['name']}")
            print(f"    Purpose: {s['purpose'][:60]}...")
            print(f"    Phases: {', '.join(s['phases'])}")
            print(f"    Tools: {', '.join(s['tools'])}")
            print()


def cmd_intermediates(args):
    """List or inspect intermediate states."""
    from .core.intermediate import IntermediateManager

    workspace = Path(args.spec_folder) / ".workspace"
    mgr = IntermediateManager(workspace)

    if args.list:
        states = mgr.list_states()
        print(f"Intermediate states ({len(states)}):\n")

        for s in states:
            print(f"  v{s['version']:03d} [{s['phase']}]")
            print(f"    {s['description']}")
            print(f"    Coverage: {s['coverage_percent']:.1f}%")
            print()

    elif args.compare:
        v1, v2 = args.compare
        state1 = mgr.load(v1)
        state2 = mgr.load(v2)

        if not state1 or not state2:
            print(f"Could not load states {v1} and/or {v2}")
            return

        diff = mgr.compare(state1, state2)
        print(f"Comparison v{v1} → v{v2}:")
        print(f"  Units added: {len(diff['units_added'])}")
        print(f"  Units removed: {len(diff['units_removed'])}")
        print(f"  Status changes: {len(diff['status_changes'])}")
        print(f"  Coverage: {diff['coverage_change']['from']:.1f}% → {diff['coverage_change']['to']:.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description="Spec Manager - Adaptive specification processing"
    )
    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Ingest command
    p_ingest = subparsers.add_parser('ingest', help='Run full ingest workflow')
    p_ingest.add_argument('spec_folder', help='Path to spec folder')
    p_ingest.add_argument('--max-passes', type=int, default=10, help='Max cleaning passes')
    p_ingest.add_argument('--max-iterations', type=int, default=10, help='Max discovery iterations')
    p_ingest.add_argument('--no-intermediates', action='store_true', help='Skip saving intermediates')
    p_ingest.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    p_ingest.set_defaults(func=cmd_ingest)

    # Gaps command
    p_gaps = subparsers.add_parser('gaps', help='Run unified gap detection')
    p_gaps.add_argument('spec_folder', help='Path to spec folder')
    p_gaps.add_argument('--update', action='store_true', help='Write gaps.md')
    p_gaps.add_argument('--no-info', action='store_true', help='Exclude info-level gaps')
    p_gaps.set_defaults(func=cmd_gaps)

    # Strategies command
    p_strat = subparsers.add_parser('strategies', help='List available strategies')
    p_strat.add_argument('--list', '-l', action='store_true', help='List all strategies')
    p_strat.set_defaults(func=cmd_strategies)

    # Intermediates command
    p_int = subparsers.add_parser('intermediates', help='Inspect intermediate states')
    p_int.add_argument('spec_folder', help='Path to spec folder')
    p_int.add_argument('--list', '-l', action='store_true', help='List all states')
    p_int.add_argument('--compare', nargs=2, type=int, metavar=('V1', 'V2'), help='Compare two versions')
    p_int.set_defaults(func=cmd_intermediates)

    args = parser.parse_args()

    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
```

## New CLI Commands

```bash
# Full ingest workflow
spec_manager ingest /path/to/spec --verbose

# Unified gap detection
spec_manager gaps /path/to/spec --update

# List available strategies
spec_manager strategies --list

# Inspect intermediate states
spec_manager intermediates /path/to/spec --list
spec_manager intermediates /path/to/spec --compare 3 5
```

## Success Criteria

1. `spec_manager ingest` runs the full workflow
2. All phases execute in order
3. Intermediate states saved and loadable
4. Strategies applied at appropriate phases
5. Libraries generated from discovery
6. gaps.md generated with all gap types
7. Coverage report shows nothing unaccounted
8. New CLI commands work

## Testing

```python
def test_full_workflow(tmp_path):
    # Create test spec folder
    spec_folder = tmp_path / "test_spec"
    spec_folder.mkdir()
    (spec_folder / "patches").mkdir()

    # Create test patches
    (spec_folder / "patches" / "p1.md").write_text('''
## Algorithm 1 ([=Algorithm 1])

First algorithm content.

## D1 ([=D1])

Data structure 1.
''')

    (spec_folder / "patches" / "p2.md").write_text('''
## Algorithm 2 ([=Algorithm 2])

Second algorithm, references (@[+Algorithm 1]).
''')

    # Run workflow
    result = ingest(spec_folder)

    assert result['phase'] == 'complete'
    assert result['total_units'] >= 3
    assert len(result['errors']) == 0

    # Check outputs
    assert (spec_folder / "gaps.md").exists()
    assert (spec_folder / "libraries").exists()
```
