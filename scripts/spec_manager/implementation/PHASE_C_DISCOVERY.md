# Phase C: Multi-Label Library Discovery

## Overview

This phase implements the library discovery workflow. The key insight is:

**Libraries EMERGE from the data. You don't predefine them.**

The process is:
1. Look at clean inputs and identify candidate libraries (BIG systems)
2. Multi-label every element ("this looks like X, Y, Z")
3. Aggregate labels to see library shapes (convergence/divergence)
4. Discover new libraries from clusters
5. Iterate until each element has ONE primary label
6. Add relation annotations for cross-cutting concerns

## Why Multi-Label First?

Traditional approach: Assign each element to exactly one category immediately.

Problem: Many elements legitimately relate to multiple systems. Forcing early decisions loses information.

Solution: Allow ambiguity during discovery. Elements can have multiple candidate labels with confidence scores. The "shape" of libraries emerges from aggregation.

Example:
```
Algorithm 5 (field relaxation):
  - field_solver: 0.85      # Primary concern
  - graph_ops: 0.40         # Uses graph operations
  - uncertainty: 0.25       # Updates uncertainty values

After aggregation, field_solver gets Algorithm 5 as primary.
Graph_ops and uncertainty get relation annotations.
```

## The Discovery Process

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: CANDIDATE IDENTIFICATION                            │
│                                                             │
│ Look at all elements. What BIG systems do you see?          │
│ Not components. Not small things. SYSTEMS.                  │
│                                                             │
│ Input: Clean elements (all annotated)                       │
│ Output: Initial library guesses                             │
│   - field_solver (field computation system)                 │
│   - graph_store (graph management system)                   │
│   - ingestion (data ingestion system)                       │
│   - ...                                                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 2: MULTI-LABEL ASSIGNMENT                              │
│                                                             │
│ For each element, ask: "Which libraries might this go in?"  │
│ Assign confidence scores. Be generous - allow overlap.      │
│                                                             │
│ Algorithm 5:                                                │
│   field_solver: 0.85, graph_ops: 0.40, uncertainty: 0.25    │
│                                                             │
│ This captures the "smear" - elements that cross boundaries. │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 3: SHAPE AGGREGATION                                   │
│                                                             │
│ Aggregate all labels per library. What shape emerges?       │
│                                                             │
│ field_solver:                                               │
│   strong_matches: [Alg3, Alg5, D12, D15]                    │
│   medium_matches: [Alg8, D20]                               │
│   weak_matches: [Alg1, D5]                                  │
│   convergence: 0.87 (high - good library!)                  │
│                                                             │
│ mystery_cluster:                                            │
│   elements: [Alg7, Alg9, D30]                               │
│   no strong library match                                   │
│   → Maybe a new library?                                    │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 4: LIBRARY REFINEMENT                                  │
│                                                             │
│ Based on shapes, refine the library set:                    │
│   - High convergence → Keep as-is                           │
│   - Bimodal distribution → Split into two libraries         │
│   - High overlap with another → Merge libraries             │
│   - Orphan cluster → Create new library                     │
│                                                             │
│ Iterate until stable.                                       │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ Step 5: PRIMARY ASSIGNMENT                                  │
│                                                             │
│ Each element gets ONE primary library (highest confidence). │
│ Lower-confidence matches become relation annotations.       │
│                                                             │
│ Algorithm 5:                                                │
│   primary: field_solver                                     │
│   relations: [graph_ops, uncertainty]                       │
│                                                             │
│ These relations help future library refinement.             │
└─────────────────────────────────────────────────────────────┘
```

## Implementation

### File 1: `spec_manager/discovery/candidate.py`

```python
"""
Candidate library identification.

This module identifies potential libraries by analyzing the content
of all elements. It looks for BIG systems, not small components.

The heuristics include:
- Keyword clustering (field, graph, ingestion, etc.)
- Reference patterns (what references what)
- Structural similarity (similar element types together)
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from spec_manager.core.provenance import TrackedUnit, UnitType


@dataclass
class LibraryEvent:
    """Event tracking rename/merge/split of libraries during discovery."""
    event_type: str              # "rename", "merge", "split"
    timestamp: datetime
    details: dict[str, Any]      # Event-specific data


@dataclass
class CandidateLibrary:
    """A candidate library identified during discovery."""

    # Stable internal ID (never changes during discovery)
    internal_id: str             # e.g., "LIB_TMP_013" - stable for tracking

    # Display name (can change freely during discovery)
    name: str                    # Current display name (can churn)
    description: str

    # Evidence for this library
    keywords: list[str]                    # Keywords that suggest this library
    exemplar_elements: list[str]           # Element IDs that clearly belong
    confidence: float = 0.5                # How confident we are this is real

    # Discovery metadata
    how_identified: str = ""               # What triggered this identification

    # Name history (track churning)
    name_history: list[str] = field(default_factory=list)  # Previous names

    # Event log for this library
    events: list[LibraryEvent] = field(default_factory=list)

    def rename(self, new_name: str, reason: str = "") -> None:
        """Rename library - stable ID unchanged, display name updated."""
        self.name_history.append(self.name)
        self.events.append(LibraryEvent(
            event_type="rename",
            timestamp=datetime.now(),
            details={"from": self.name, "to": new_name, "reason": reason}
        ))
        self.name = new_name


class CandidateIdentifier:
    """
    Identifies candidate libraries from elements.

    The key insight is to look for SYSTEMS, not components.
    A system is a cohesive set of elements that work together
    to achieve a capability.

    CRITICAL: NO HARDCODED KEYWORDS.
    Candidate libraries are identified from MULTI-SIGNAL COMBINATION:
    - Content clustering (word-based seed, NOT the defining signal)
    - Reference graph structure (who cites who)
    - Relation annotations (smear from prior iterations)
    - Unit types (algorithms/claims/datastructures cluster differently)
    - LLM-derived system summaries (optional)

    Word-based clustering is ONE candidate-generator strategy, not the only one.
    The main convergence mechanism is multi-labeling + shape aggregation.
    """

    def __init__(self, config_path: Path | None = None, llm_client=None):
        self.candidates: dict[str, CandidateLibrary] = {}  # keyed by internal_id
        self.keyword_config: dict[str, list[str]] = {}
        self._next_lib_id = 1  # Counter for stable internal IDs
        self._llm = llm_client

        # Load keywords from config if provided (optional bootstrap)
        if config_path and config_path.exists():
            self._load_keyword_config(config_path)

    def _generate_internal_id(self) -> str:
        """Generate a stable internal ID for a candidate library."""
        lib_id = f"LIB_TMP_{self._next_lib_id:03d}"
        self._next_lib_id += 1
        return lib_id

    def _load_keyword_config(self, path: Path) -> None:
        """
        Load keyword configuration from YAML file.

        This is OPTIONAL and only used as a bootstrap hint.
        Keywords are NOT hardcoded - they come from config.
        """
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        self.keyword_config = data.get('candidate_keywords', {})

    def identify_candidates(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """
        Identify candidate libraries from a set of units.

        Returns initial guesses for libraries based on:
        1. DATA-DRIVEN CLUSTERING (primary approach)
        2. Optional keyword hints from config (NOT hardcoded)

        Libraries EMERGE from data, they are not predefined.
        """
        candidates = []

        # PRIMARY: Data-driven clustering from content
        clusters = self._cluster_by_content(units)
        for cluster_name, cluster_units in clusters.items():
            if len(cluster_units) >= 3:  # Minimum cluster size
                internal_id = self._generate_internal_id()
                candidate = CandidateLibrary(
                    internal_id=internal_id,  # Stable ID for tracking
                    name=cluster_name,        # Display name (can churn)
                    description=f"Emerged from content clustering",
                    keywords=self._extract_keywords(cluster_units),
                    exemplar_elements=[u.id for u in cluster_units[:5]],
                    confidence=0.6,  # Medium confidence for data-driven
                    how_identified="Content clustering"
                )
                candidates.append(candidate)
                self.candidates[internal_id] = candidate  # Key by internal_id

        # SECONDARY: Use keyword config hints (if provided, NOT hardcoded)
        if self.keyword_config:
            all_content = ' '.join(u.content.lower() for u in units)

            for system_name, keywords in self.keyword_config.items():
                # Skip if already found via clustering
                if system_name in self.candidates:
                    continue

                # Count keyword occurrences
                keyword_counts = {
                    kw: all_content.count(kw)
                    for kw in keywords
                }
                total_matches = sum(keyword_counts.values())

                if total_matches > 5:  # Threshold for significance
                    exemplars = self._find_exemplars(units, keywords)

                    internal_id = self._generate_internal_id()
                    candidate = CandidateLibrary(
                        internal_id=internal_id,
                        name=system_name,
                        description=f"System for {system_name}-related operations",
                        keywords=keywords,
                        exemplar_elements=exemplars[:5],
                        confidence=min(total_matches / 50, 1.0),
                        how_identified=f"Config-assisted: {total_matches} matches"
                    )
                    candidates.append(candidate)
                    self.candidates[internal_id] = candidate

        # Look for orphan clusters (elements that don't match any system)
        assigned = set()
        for c in candidates:
            assigned.update(c.exemplar_elements)

        orphans = [u.id for u in units if u.id not in assigned]
        if orphans:
            # Analyze orphans for potential new library
            orphan_candidate = self._analyze_orphans(
                [u for u in units if u.id in orphans]
            )
            if orphan_candidate:
                candidates.append(orphan_candidate)
                self.candidates[orphan_candidate.name] = orphan_candidate

        return candidates

    def _cluster_by_content(
        self,
        units: list[TrackedUnit]
    ) -> dict[str, list[TrackedUnit]]:
        """
        Cluster units by content similarity - DATA-DRIVEN approach.

        Uses TF-IDF-like approach to identify natural clusters.
        Libraries EMERGE from data, they are not predefined.
        """
        # Extract significant words from each unit
        unit_words: dict[str, set[str]] = {}
        word_freq = defaultdict(int)

        for unit in units:
            words = set(re.findall(r'\b[a-z]{4,}\b', unit.content.lower()))
            # Filter stopwords
            stopwords = {'that', 'this', 'with', 'from', 'have', 'will', 'been', 'each', 'which', 'their', 'when', 'where'}
            words = words - stopwords
            unit_words[unit.id] = words
            for word in words:
                word_freq[word] += 1

        # Find discriminating words (appear in 10-80% of units)
        total = len(units)
        discriminating = {
            word for word, count in word_freq.items()
            if 0.1 * total < count < 0.8 * total
        }

        # Cluster by most common discriminating words
        clusters: dict[str, list[TrackedUnit]] = defaultdict(list)

        for unit in units:
            words = unit_words[unit.id] & discriminating
            if words:
                # Assign to cluster based on most frequent discriminating word
                best_word = max(words, key=lambda w: word_freq[w])
                clusters[f"cluster_{best_word}"].append(unit)

        return dict(clusters)

    def _extract_keywords(
        self,
        units: list[TrackedUnit]
    ) -> list[str]:
        """Extract the most common keywords from a set of units."""
        word_freq = defaultdict(int)

        for unit in units:
            words = set(re.findall(r'\b[a-z]{4,}\b', unit.content.lower()))
            for word in words:
                word_freq[word] += 1

        # Return top keywords by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:10]]

    def _find_exemplars(
        self,
        units: list[TrackedUnit],
        keywords: list[str]
    ) -> list[str]:
        """Find elements that best exemplify a keyword set."""
        scores = []

        for unit in units:
            content_lower = unit.content.lower()
            score = sum(
                content_lower.count(kw) for kw in keywords
            )
            if score > 0:
                scores.append((unit.id, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scores]

    def _analyze_orphans(
        self,
        orphan_units: list[TrackedUnit]
    ) -> CandidateLibrary | None:
        """Analyze orphan elements for potential new library."""
        if len(orphan_units) < 3:
            return None  # Too few to form a library

        # Extract common keywords from orphans
        word_freq = defaultdict(int)
        for unit in orphan_units:
            words = re.findall(r'\b[a-z]{4,}\b', unit.content.lower())
            for word in set(words):  # Count each word once per unit
                word_freq[word] += 1

        # Find words that appear in most orphans
        common_words = [
            word for word, count in word_freq.items()
            if count >= len(orphan_units) * 0.5  # In at least half
        ]

        if not common_words:
            return None

        return CandidateLibrary(
            internal_id=self._generate_internal_id(),
            name=f"emerging_{common_words[0]}",
            description=f"Emerging system around {', '.join(common_words[:3])}",
            keywords=common_words[:5],
            exemplar_elements=[u.id for u in orphan_units[:5]],
            confidence=0.3,  # Low confidence for emerging
            how_identified="Orphan cluster analysis"
        )

    def suggest_from_references(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """
        Identify candidates based on reference patterns.

        Elements that reference each other heavily might form a system.
        """
        # Build reference graph
        ref_graph = defaultdict(set)
        for unit in units:
            for ref in unit.references:
                ref_graph[unit.id].add(ref)

        # Find clusters (elements that heavily reference each other)
        clusters = self._find_reference_clusters(ref_graph)

        candidates = []
        for i, cluster in enumerate(clusters):
            if len(cluster) >= 3:
                candidate = CandidateLibrary(
                    internal_id=self._generate_internal_id(),
                    name=f"ref_cluster_{i}",
                    description="Elements with strong mutual references",
                    keywords=[],
                    exemplar_elements=list(cluster)[:5],
                    confidence=0.4,
                    how_identified="Reference pattern analysis"
                )
                candidates.append(candidate)

        return candidates

    def _find_reference_clusters(
        self,
        ref_graph: dict[str, set[str]]
    ) -> list[set[str]]:
        """Find clusters of mutually-referencing elements."""
        clusters = []
        visited = set()

        for node in ref_graph:
            if node in visited:
                continue

            # BFS to find connected component
            cluster = set()
            queue = [node]

            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue

                visited.add(current)
                cluster.add(current)

                # Add neighbors
                for neighbor in ref_graph.get(current, []):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(cluster) >= 3:
                clusters.append(cluster)

        return clusters

    # =========================================================================
    # MULTI-SIGNAL DISCOVERY (Gap 9)
    # =========================================================================

    def discover_with_all_signals(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """
        Combine ALL signals for library discovery.

        Signals (in order of weight):
        1. Reference graph structure (highest - who cites who)
        2. Unit type clustering (algorithms cluster differently than data structures)
        3. Relation annotations from prior iterations
        4. Content clustering (word-based seed)
        5. LLM system summaries (optional, expensive)

        Returns unified candidate list with combined confidence scores.
        """
        all_candidates: dict[str, CandidateLibrary] = {}
        candidate_evidence: dict[str, list[dict]] = defaultdict(list)

        # Signal 1: Reference graph (high weight)
        ref_candidates = self.suggest_from_references(units)
        for c in ref_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append({
                'signal': 'reference_graph',
                'weight': 0.4,
                'elements': c.exemplar_elements
            })

        # Signal 2: Unit type clustering
        type_candidates = self._cluster_by_unit_type(units)
        for c in type_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append({
                'signal': 'unit_type',
                'weight': 0.3,
                'elements': c.exemplar_elements
            })

        # Signal 3: Relation annotations from prior iterations
        relation_candidates = self._extract_from_relations(units)
        for c in relation_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append({
                'signal': 'relations',
                'weight': 0.15,
                'elements': c.exemplar_elements
            })

        # Signal 4: Content clustering (word-based seed)
        content_candidates = self.identify_candidates(units)  # Existing method
        for c in content_candidates:
            if c.internal_id not in all_candidates:
                all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append({
                'signal': 'content_clustering',
                'weight': 0.1,
                'elements': c.exemplar_elements
            })

        # Signal 5: LLM system summaries (optional)
        if self._llm:
            llm_candidates = self._llm_summarize_systems(units)
            for c in llm_candidates:
                all_candidates[c.internal_id] = c
                candidate_evidence[c.internal_id].append({
                    'signal': 'llm_summary',
                    'weight': 0.05,
                    'elements': c.exemplar_elements
                })

        # Combine confidence scores using weighted evidence
        for internal_id, evidence_list in candidate_evidence.items():
            if internal_id in all_candidates:
                total_weight = sum(e['weight'] for e in evidence_list)
                all_candidates[internal_id].confidence = min(total_weight, 1.0)
                all_candidates[internal_id].how_identified = ', '.join(
                    f"{e['signal']}({e['weight']:.2f})" for e in evidence_list
                )

        return list(all_candidates.values())

    def _cluster_by_unit_type(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """
        Cluster by unit type - algorithms cluster differently than data structures.

        Insight: A system often has a characteristic "shape" of unit types.
        """
        candidates = []

        # Group by unit type
        by_type: dict[UnitType, list[TrackedUnit]] = defaultdict(list)
        for unit in units:
            by_type[unit.unit_type].append(unit)

        # Algorithms often form systems
        if UnitType.ALGORITHM in by_type and len(by_type[UnitType.ALGORITHM]) >= 3:
            # Subcluster algorithms by their claims/references
            alg_clusters = self._subcluster_by_claims(by_type[UnitType.ALGORITHM])
            for i, cluster in enumerate(alg_clusters):
                if len(cluster) >= 2:
                    candidates.append(CandidateLibrary(
                        internal_id=self._generate_internal_id(),
                        name=f"algorithm_system_{i}",
                        description="Algorithms with related claims",
                        keywords=[],
                        exemplar_elements=[u.id for u in cluster[:5]],
                        confidence=0.5,
                        how_identified="Unit type + claim clustering"
                    ))

        # Data structures often form cohesive systems
        if UnitType.DATA_STRUCTURE in by_type and len(by_type[UnitType.DATA_STRUCTURE]) >= 3:
            candidates.append(CandidateLibrary(
                internal_id=self._generate_internal_id(),
                name="data_types",
                description="Data structure definitions",
                keywords=[],
                exemplar_elements=[u.id for u in by_type[UnitType.DATA_STRUCTURE][:5]],
                confidence=0.4,
                how_identified="Unit type clustering (data structures)"
            ))

        return candidates

    def _subcluster_by_claims(
        self,
        algorithms: list[TrackedUnit]
    ) -> list[list[TrackedUnit]]:
        """Subcluster algorithms by the claims they reference."""
        # Group by claim references
        claim_to_algs: dict[str, list[TrackedUnit]] = defaultdict(list)

        for alg in algorithms:
            claims_found = re.findall(r'\b(P?\d*C\d+)\b', alg.content)
            if claims_found:
                for claim in claims_found:
                    claim_to_algs[claim].append(alg)
            else:
                claim_to_algs['_no_claims'].append(alg)

        # Convert to clusters
        clusters = [algs for algs in claim_to_algs.values() if len(algs) >= 2]
        return clusters

    def _extract_from_relations(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """Extract library candidates from existing relation annotations."""
        candidates = []

        # Collect all relation_libraries from units
        relation_counts: dict[str, list[str]] = defaultdict(list)
        for unit in units:
            for rel_lib in unit.relation_libraries:
                relation_counts[rel_lib].append(unit.id)

        # Create candidates from common relations
        for lib_name, element_ids in relation_counts.items():
            if len(element_ids) >= 2:
                candidates.append(CandidateLibrary(
                    internal_id=self._generate_internal_id(),
                    name=lib_name,
                    description=f"From relation annotations",
                    keywords=[],
                    exemplar_elements=element_ids[:5],
                    confidence=0.35,
                    how_identified="Relation annotation extraction"
                ))

        return candidates

    def _llm_summarize_systems(
        self,
        units: list[TrackedUnit]
    ) -> list[CandidateLibrary]:
        """Use LLM to identify systems from unit content."""
        if not self._llm:
            return []

        # Sample units for LLM (avoid overwhelming context)
        sample_size = min(20, len(units))
        sample = units[:sample_size]

        unit_summaries = [f"- {u.id}: {u.content[:100]}..." for u in sample]

        prompt = f"""Analyze these spec elements and identify what BIG SYSTEMS they might belong to.

Elements:
{chr(10).join(unit_summaries)}

Identify 2-5 major systems (not small components). For each system:
1. Name (single word, lowercase, underscore-separated)
2. Which elements belong to it (list IDs)
3. Brief description

Output as JSON array: [{{"name": "...", "elements": ["id1", "id2"], "description": "..."}}]"""

        try:
            response = self._llm.complete(prompt)
            import json
            systems = json.loads(response)

            candidates = []
            for sys in systems:
                candidates.append(CandidateLibrary(
                    internal_id=self._generate_internal_id(),
                    name=sys['name'],
                    description=sys.get('description', 'LLM-identified system'),
                    keywords=[],
                    exemplar_elements=sys.get('elements', [])[:5],
                    confidence=0.3,  # Lower confidence for LLM
                    how_identified="LLM system summary"
                ))
            return candidates
        except Exception:
            return []
```

### File 2: `spec_manager/discovery/labeling.py`

```python
"""
Multi-label assignment for library discovery.

This module assigns elements to candidate libraries with confidence
scores. Elements can have multiple labels - this captures the
"smear" of cross-cutting concerns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from spec_manager.core.provenance import TrackedUnit
from .candidate import CandidateLibrary


@dataclass
class ElementLabels:
    """Labels assigned to an element."""

    element_id: str
    labels: dict[str, float]  # library_name → confidence

    @property
    def primary(self) -> str | None:
        """Get the primary (highest confidence) label."""
        if not self.labels:
            return None
        return max(self.labels, key=self.labels.get)

    @property
    def relations(self) -> list[str]:
        """Get non-primary labels as relations."""
        primary = self.primary
        return [
            lib for lib, conf in self.labels.items()
            if lib != primary and conf > 0.2  # Threshold for relation
        ]


class MultiLabeler:
    """
    Assigns multiple labels to elements with confidence scores.

    The labeling process:
    1. For each element, check against each candidate library
    2. Compute confidence based on keyword match, references, type
    3. Store all labels above threshold
    """

    def __init__(self, candidates: list[CandidateLibrary]):
        self.candidates = {c.name: c for c in candidates}
        self.labels: dict[str, ElementLabels] = {}

    def label_element(self, unit: TrackedUnit) -> ElementLabels:
        """Assign labels to a single element."""
        scores = {}

        for lib_name, candidate in self.candidates.items():
            score = self._compute_confidence(unit, candidate)
            if score > 0.1:  # Minimum threshold
                scores[lib_name] = score

        labels = ElementLabels(
            element_id=unit.id,
            labels=scores
        )
        self.labels[unit.id] = labels
        return labels

    def label_all(self, units: list[TrackedUnit]) -> dict[str, ElementLabels]:
        """Label all elements."""
        for unit in units:
            self.label_element(unit)
        return self.labels

    def _compute_confidence(
        self,
        unit: TrackedUnit,
        candidate: CandidateLibrary
    ) -> float:
        """
        Compute confidence that element belongs to library.

        Factors:
        - Keyword matches in content
        - References to exemplar elements
        - Element type alignment
        - Name/ID similarity
        """
        score = 0.0
        content_lower = unit.content.lower()

        # Keyword matches (40% weight)
        keyword_matches = sum(
            content_lower.count(kw) for kw in candidate.keywords
        )
        keyword_score = min(keyword_matches / 10, 1.0)  # Normalize
        score += keyword_score * 0.4

        # Reference to exemplars (30% weight)
        ref_matches = sum(
            1 for ref in unit.references
            if ref in candidate.exemplar_elements
        )
        ref_score = min(ref_matches / 3, 1.0)
        score += ref_score * 0.3

        # Is this element an exemplar? (20% weight)
        if unit.id in candidate.exemplar_elements:
            score += 0.2

        # Name similarity (10% weight)
        id_lower = unit.id.lower()
        name_match = any(kw in id_lower for kw in candidate.keywords)
        if name_match:
            score += 0.1

        return min(score, 1.0)

    def get_unlabeled(self) -> list[str]:
        """Get elements with no labels above threshold."""
        return [
            eid for eid, labels in self.labels.items()
            if not labels.labels
        ]

    def get_by_library(self, library_name: str) -> list[tuple[str, float]]:
        """Get all elements labeled with a library, sorted by confidence."""
        results = []
        for eid, labels in self.labels.items():
            if library_name in labels.labels:
                results.append((eid, labels.labels[library_name]))
        results.sort(key=lambda x: x[1], reverse=True)
        return results
```

### File 3: `spec_manager/discovery/aggregation.py`

```python
"""
Library shape aggregation.

This module aggregates labels to see the "shape" of each library -
what elements point to it, how strongly, and whether there's
convergence or divergence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .labeling import ElementLabels


@dataclass
class LibraryShape:
    """
    Aggregated view of a library's shape.

    The shape tells us:
    - What elements strongly belong here
    - What elements weakly relate
    - Whether the library is well-defined (convergence)
    - Whether it overlaps with other libraries
    """

    name: str

    # Elements by confidence tier
    strong_matches: list[str] = field(default_factory=list)    # > 0.7
    medium_matches: list[str] = field(default_factory=list)    # 0.4 - 0.7
    weak_matches: list[str] = field(default_factory=list)      # 0.2 - 0.4

    # Metrics
    total_weight: float = 0.0           # Sum of all confidences
    element_count: int = 0              # Total elements
    convergence: float = 0.0            # How well-defined (0-1)

    # Overlap with other libraries
    overlaps: dict[str, float] = field(default_factory=dict)

    # Suggestions
    should_split: bool = False
    should_merge_with: str | None = None
    split_reason: str | None = None


class ShapeAggregator:
    """
    Aggregates labels to reveal library shapes.

    The aggregation process:
    1. Group elements by their labels
    2. Compute metrics for each library
    3. Identify overlaps between libraries
    4. Suggest refinements (split, merge, new)
    """

    def __init__(self, labels: dict[str, ElementLabels]):
        self.labels = labels
        self.shapes: dict[str, LibraryShape] = {}

    def aggregate(self) -> dict[str, LibraryShape]:
        """Compute shapes for all libraries."""
        # Collect elements per library
        library_elements: dict[str, list[tuple[str, float]]] = {}

        for element_id, element_labels in self.labels.items():
            for lib_name, confidence in element_labels.labels.items():
                if lib_name not in library_elements:
                    library_elements[lib_name] = []
                library_elements[lib_name].append((element_id, confidence))

        # Compute shape for each library
        for lib_name, elements in library_elements.items():
            shape = self._compute_shape(lib_name, elements)
            self.shapes[lib_name] = shape

        # Compute overlaps
        self._compute_overlaps()

        # Generate suggestions
        self._generate_suggestions()

        return self.shapes

    def _compute_shape(
        self,
        name: str,
        elements: list[tuple[str, float]]
    ) -> LibraryShape:
        """Compute shape metrics for a library."""
        shape = LibraryShape(name=name)

        # Sort by confidence
        elements.sort(key=lambda x: x[1], reverse=True)

        # Categorize by confidence tier
        for element_id, confidence in elements:
            if confidence > 0.7:
                shape.strong_matches.append(element_id)
            elif confidence > 0.4:
                shape.medium_matches.append(element_id)
            else:
                shape.weak_matches.append(element_id)

            shape.total_weight += confidence

        shape.element_count = len(elements)

        # Compute convergence
        # High convergence = most elements are strong matches
        if shape.element_count > 0:
            strong_ratio = len(shape.strong_matches) / shape.element_count
            # Also consider confidence distribution
            avg_confidence = shape.total_weight / shape.element_count
            shape.convergence = (strong_ratio + avg_confidence) / 2

        return shape

    def _compute_overlaps(self) -> None:
        """Compute overlap between libraries."""
        library_names = list(self.shapes.keys())

        for i, lib1 in enumerate(library_names):
            shape1 = self.shapes[lib1]
            elements1 = set(shape1.strong_matches + shape1.medium_matches)

            for lib2 in library_names[i+1:]:
                shape2 = self.shapes[lib2]
                elements2 = set(shape2.strong_matches + shape2.medium_matches)

                # Compute Jaccard overlap
                intersection = len(elements1 & elements2)
                union = len(elements1 | elements2)

                if union > 0:
                    overlap = intersection / union
                    if overlap > 0.1:  # Significant overlap
                        shape1.overlaps[lib2] = overlap
                        shape2.overlaps[lib1] = overlap

    def _generate_suggestions(self) -> None:
        """Generate refinement suggestions based on shapes."""
        for name, shape in self.shapes.items():
            # Should split? (bimodal distribution)
            # Heuristic: many medium matches but few strong
            if (len(shape.medium_matches) > len(shape.strong_matches) * 2
                and shape.convergence < 0.5):
                shape.should_split = True
                shape.split_reason = "Bimodal distribution suggests two distinct concepts"

            # Should merge? (high overlap with another)
            for other_name, overlap in shape.overlaps.items():
                if overlap > 0.6:  # Very high overlap
                    other_shape = self.shapes[other_name]
                    # Merge smaller into larger
                    if shape.element_count < other_shape.element_count:
                        shape.should_merge_with = other_name

    def get_new_library_candidates(self) -> list[list[str]]:
        """
        Find clusters that might be new libraries.

        These are elements that:
        - Have no strong match to any library
        - But strongly reference each other
        """
        # Find elements with only weak matches
        weak_elements = []
        for element_id, labels in self.labels.items():
            max_confidence = max(labels.labels.values()) if labels.labels else 0
            if max_confidence < 0.4:
                weak_elements.append(element_id)

        if len(weak_elements) < 3:
            return []

        # These could form new libraries - return as candidates
        return [weak_elements]

    def summary(self) -> dict[str, Any]:
        """Generate a summary of all library shapes."""
        return {
            name: {
                'strong': len(shape.strong_matches),
                'medium': len(shape.medium_matches),
                'weak': len(shape.weak_matches),
                'convergence': round(shape.convergence, 2),
                'overlaps': shape.overlaps,
                'should_split': shape.should_split,
                'should_merge_with': shape.should_merge_with
            }
            for name, shape in self.shapes.items()
        }
```

### File 4: `spec_manager/discovery/refinement.py`

```python
"""
Iterative library refinement.

This module handles the iterative process of refining libraries
until each element has a single primary assignment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spec_manager.core.provenance import TrackedUnit
from .candidate import CandidateLibrary, CandidateIdentifier
from .labeling import MultiLabeler, ElementLabels
from .aggregation import ShapeAggregator, LibraryShape


@dataclass
class RefinementResult:
    """Result of a refinement iteration."""

    iteration: int
    libraries: list[CandidateLibrary]
    shapes: dict[str, LibraryShape]
    labels: dict[str, ElementLabels]

    # Changes made
    libraries_added: list[str]
    libraries_removed: list[str]
    libraries_merged: list[tuple[str, str]]  # (source, target)
    libraries_split: list[tuple[str, list[str]]]  # (source, new_names)

    # Metrics
    convergence_score: float  # Overall convergence
    unassigned_count: int


class LibraryRefiner:
    """
    Iteratively refines libraries until stable.

    The refinement loop:
    1. Label elements with current libraries
    2. Aggregate to see shapes
    3. Apply suggestions (split, merge, new)
    4. Repeat until stable
    """

    def __init__(self, units: list[TrackedUnit]):
        self.units = units
        self.iteration = 0
        self.history: list[RefinementResult] = []

    def refine(
        self,
        initial_candidates: list[CandidateLibrary],
        max_iterations: int = 10
    ) -> RefinementResult:
        """
        Run refinement until stable or max iterations.

        Returns the final refinement result.
        """
        candidates = initial_candidates.copy()

        for i in range(max_iterations):
            self.iteration = i + 1

            # Label with current candidates
            labeler = MultiLabeler(candidates)
            labels = labeler.label_all(self.units)

            # Aggregate to see shapes
            aggregator = ShapeAggregator(labels)
            shapes = aggregator.aggregate()

            # Check for suggested changes
            added, removed, merged, split = self._apply_suggestions(
                candidates, shapes, aggregator
            )

            # Compute metrics
            convergence = self._compute_overall_convergence(shapes)
            unassigned = len(labeler.get_unlabeled())

            result = RefinementResult(
                iteration=self.iteration,
                libraries=candidates.copy(),
                shapes=shapes,
                labels=labels,
                libraries_added=added,
                libraries_removed=removed,
                libraries_merged=merged,
                libraries_split=split,
                convergence_score=convergence,
                unassigned_count=unassigned
            )
            self.history.append(result)

            # Check for stability
            if not added and not removed and not merged and not split:
                break  # Stable!

            # Update candidates for next iteration
            # (mutations happened in _apply_suggestions)

        return self.history[-1]

    def _apply_suggestions(
        self,
        candidates: list[CandidateLibrary],
        shapes: dict[str, LibraryShape],
        aggregator: ShapeAggregator
    ) -> tuple[list[str], list[str], list[tuple[str, str]], list[tuple[str, list[str]]]]:
        """Apply shape-based suggestions to candidates."""
        added = []
        removed = []
        merged = []
        split = []

        # Handle merges
        for name, shape in shapes.items():
            if shape.should_merge_with:
                # Remove the smaller library
                candidates[:] = [c for c in candidates if c.name != name]
                removed.append(name)
                merged.append((name, shape.should_merge_with))

        # Handle splits
        for name, shape in shapes.items():
            if shape.should_split and name not in removed:
                # Create two new libraries from the split
                new_names = [f"{name}_a", f"{name}_b"]
                old_candidate = next(c for c in candidates if c.name == name)

                # Split elements between new libraries
                # (Simple heuristic: divide medium matches)
                mid = len(shape.medium_matches) // 2

                new_a = CandidateLibrary(
                    name=new_names[0],
                    description=f"Split from {name} (part A)",
                    keywords=old_candidate.keywords,
                    exemplar_elements=shape.strong_matches[:3] + shape.medium_matches[:mid],
                    confidence=0.5,
                    how_identified=f"Split from {name}"
                )

                new_b = CandidateLibrary(
                    name=new_names[1],
                    description=f"Split from {name} (part B)",
                    keywords=old_candidate.keywords,
                    exemplar_elements=shape.medium_matches[mid:] + shape.weak_matches[:3],
                    confidence=0.5,
                    how_identified=f"Split from {name}"
                )

                candidates[:] = [c for c in candidates if c.name != name]
                candidates.extend([new_a, new_b])

                removed.append(name)
                added.extend(new_names)
                split.append((name, new_names))

        # Handle new library candidates
        new_clusters = aggregator.get_new_library_candidates()
        for cluster in new_clusters:
            new_name = f"emerging_{self.iteration}"
            new_lib = CandidateLibrary(
                name=new_name,
                description=f"Emerging library from iteration {self.iteration}",
                keywords=[],
                exemplar_elements=cluster[:5],
                confidence=0.3,
                how_identified="Emerged from weak-match cluster"
            )
            candidates.append(new_lib)
            added.append(new_name)

        return added, removed, merged, split

    def _compute_overall_convergence(
        self,
        shapes: dict[str, LibraryShape]
    ) -> float:
        """Compute overall convergence across all libraries."""
        if not shapes:
            return 0.0

        total_convergence = sum(s.convergence for s in shapes.values())
        return total_convergence / len(shapes)

    def finalize(self) -> dict[str, ElementLabels]:
        """
        Finalize labels by assigning primary and relations.

        After refinement, each element should have exactly one
        primary library and zero or more relation libraries.
        """
        if not self.history:
            raise ValueError("Must run refine() before finalize()")

        final_result = self.history[-1]
        final_labels = {}

        for element_id, labels in final_result.labels.items():
            # Primary is highest confidence
            primary = labels.primary
            relations = labels.relations

            final_labels[element_id] = ElementLabels(
                element_id=element_id,
                labels={primary: 1.0} if primary else {}  # Normalize primary to 1.0
            )
            # Store relations for annotation
            if relations:
                final_labels[element_id].labels.update({
                    r: labels.labels[r] for r in relations
                })

        return final_labels
```

## Integration with Workflow

```python
# In workflow orchestrator

from spec_manager.discovery.candidate import CandidateIdentifier
from spec_manager.discovery.labeling import MultiLabeler
from spec_manager.discovery.aggregation import ShapeAggregator
from spec_manager.discovery.refinement import LibraryRefiner


async def discover_libraries(
    units: list[TrackedUnit],
    llm_client=None,
    config_path: Path | None = None
) -> dict[str, ElementLabels]:
    """
    Run the full library discovery workflow.

    IMPORTANT: Uses discover_with_all_signals() for multi-signal discovery.
    This combines:
    1. Reference graph structure (highest weight)
    2. Unit type clustering
    3. Relation annotations from prior iterations
    4. Content clustering (word-based seed)
    5. LLM system summaries (optional, if llm_client provided)
    """

    # Step 1: Identify candidates using ALL signals (not just keywords)
    identifier = CandidateIdentifier(config_path=config_path, llm_client=llm_client)
    candidates = identifier.discover_with_all_signals(units)  # Multi-signal discovery

    print(f"Identified {len(candidates)} candidate libraries via multi-signal discovery")
    for c in candidates:
        print(f"  - {c.name} ({c.internal_id}): {c.how_identified}")

    # Step 2-4: Refine iteratively
    refiner = LibraryRefiner(units)
    result = refiner.refine(candidates, max_iterations=10)

    print(f"Refinement completed in {result.iteration} iterations")
    print(f"Convergence: {result.convergence_score:.2f}")
    print(f"Unassigned: {result.unassigned_count}")

    # Step 5: Finalize assignments
    final_labels = refiner.finalize()

    return final_labels


# Legacy wrapper (deprecated - use discover_libraries with discover_with_all_signals)
async def discover_libraries_keyword_only(units: list[TrackedUnit]) -> dict[str, ElementLabels]:
    """
    DEPRECATED: Keyword-based discovery only.

    Use discover_libraries() instead, which uses discover_with_all_signals().
    This is kept for backward compatibility but should not be used in new code.
    """
    import warnings
    warnings.warn(
        "discover_libraries_keyword_only is deprecated. "
        "Use discover_libraries() which uses discover_with_all_signals().",
        DeprecationWarning
    )

    identifier = CandidateIdentifier()
    candidates = identifier.identify_candidates(units)  # Old method
    candidates.extend(identifier.suggest_from_references(units))

    refiner = LibraryRefiner(units)
    result = refiner.refine(candidates, max_iterations=10)

    return refiner.finalize()
```

## Known Limitations

### MultiLabeler Keyword Reliance

The `MultiLabeler._compute_confidence()` method currently weights signals as:
- **40%** - Keyword matches in content
- **30%** - References to exemplar elements
- **20%** - Is this element an exemplar?
- **10%** - Name/ID similarity (keyword-based)

This means **50% of the signal is keyword-based** (40% direct + 10% name).

**Why this is acceptable for now:**
1. Keywords come from config or data-driven clustering (not hardcoded)
2. `CandidateIdentifier.discover_with_all_signals()` compensates by using multi-signal discovery for candidate generation
3. The labeling step happens AFTER candidates are identified - it just assigns existing candidates to elements

**Future improvement opportunity:**
- Add LLM-based semantic similarity scoring as a signal in `_compute_confidence()`
- Reduce keyword weight from 40% to 20%, add 20% for LLM semantic score
- This would make labeling less keyword-dependent

```python
# FUTURE: Improved confidence computation
def _compute_confidence(self, unit, candidate) -> float:
    score = 0.0
    # Keyword matches (20% weight - reduced from 40%)
    score += keyword_score * 0.2
    # Reference to exemplars (30% weight)
    score += ref_score * 0.3
    # Is this element an exemplar? (20% weight)
    score += 0.2 if is_exemplar else 0
    # Name similarity (10% weight)
    score += 0.1 if name_match else 0
    # LLM semantic similarity (20% weight - NEW)
    score += llm_semantic_score * 0.2
    return min(score, 1.0)
```

## Success Criteria

1. Can identify candidate libraries from content
2. Multi-labeling captures cross-cutting concerns
3. Shape aggregation reveals convergence/divergence
4. Refinement converges to stable state
5. Each element ends with one primary label
6. Relations are preserved for annotations
7. New libraries emerge from orphan clusters
8. **Multi-signal discovery is used by orchestrator** (not keyword-only)

## Testing

```python
def test_discovery_workflow():
    units = [
        TrackedUnit(id="Alg1", content="field relaxation algorithm", ...),
        TrackedUnit(id="Alg2", content="graph traversal for edges", ...),
        TrackedUnit(id="D1", content="field state storage", ...),
    ]

    # Full workflow
    labels = discover_libraries(units)

    # Each element has a primary
    for label in labels.values():
        assert label.primary is not None

    # Field-related elements should cluster
    assert labels["Alg1"].primary == labels["D1"].primary
```
