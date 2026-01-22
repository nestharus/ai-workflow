"""Candidate library identification.

This module identifies potential libraries by analyzing the content
of all elements. It looks for BIG systems, not small components.

The heuristics include:
- Keyword clustering (word-based seed, NOT the defining signal)
- Reference patterns (what references what)
- Structural similarity (similar element types together)
- LLM-derived system summaries (optional)

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

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from spec_manager.core.provenance import TrackedUnit, UnitType

# Minimal English stopwords for TF-IDF (no hardcoded structural terms)
_ENGLISH_STOPWORDS = frozenset(
    {
        "that",
        "this",
        "with",
        "from",
        "have",
        "will",
        "been",
        "each",
        "which",
        "their",
        "when",
        "where",
        "they",
        "them",
        "then",
        "than",
        "also",
        "only",
        "more",
        "some",
        "such",
        "other",
        "into",
        "over",
        "after",
        "before",
        "through",
        "what",
        "about",
        "would",
        "could",
        "should",
        "there",
    }
)


class LLMClient(Protocol):
    """Protocol for LLM client interface."""

    def complete(self, prompt: str) -> str:
        """Complete a prompt and return the response text."""
        ...


@dataclass
class LibraryEvent:
    """Event tracking rename/merge/split of libraries during discovery."""

    event_type: str  # "rename", "merge", "split"
    timestamp: datetime
    details: dict[str, Any]  # Event-specific data


@dataclass
class CandidateLibrary:
    """A candidate library identified during discovery."""

    # Stable internal ID (never changes during discovery)
    internal_id: str  # e.g., "LIB_TMP_013" - stable for tracking

    # Display name (can change freely during discovery)
    name: str  # Current display name (can churn)
    description: str

    # Evidence for this library
    keywords: list[str] = field(default_factory=list)  # Keywords that suggest this library
    exemplar_elements: list[str] = field(default_factory=list)  # Element IDs that clearly belong
    confidence: float = 0.5  # How confident we are this is real

    # Discovery metadata
    how_identified: str = ""  # What triggered this identification

    # Name history (track churning)
    name_history: list[str] = field(default_factory=list)  # Previous names

    # Event log for this library
    events: list[LibraryEvent] = field(default_factory=list)

    def rename(self, new_name: str, reason: str = "") -> None:
        """Rename library - stable ID unchanged, display name updated."""
        self.name_history.append(self.name)
        self.events.append(
            LibraryEvent(
                event_type="rename",
                timestamp=datetime.now(),
                details={"from": self.name, "to": new_name, "reason": reason},
            )
        )
        self.name = new_name


class CandidateIdentifier:
    """Identifies candidate libraries from elements.

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

    def __init__(self, config_path: Path | None = None, llm_client: LLMClient | None = None):
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
        """Load keyword configuration from YAML file.

        This is OPTIONAL and only used as a bootstrap hint.
        Keywords are NOT hardcoded - they come from config.
        """
        import yaml

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self.keyword_config = data.get("candidate_keywords", {})

    def identify_candidates(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
        """Identify candidate libraries from a set of units.

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
                    name=cluster_name,  # Display name (can churn)
                    description="Emerged from content clustering",
                    keywords=self._extract_keywords(cluster_units),
                    exemplar_elements=[u.id for u in cluster_units[:5]],
                    confidence=0.6,  # Medium confidence for data-driven
                    how_identified="Content clustering",
                )
                candidates.append(candidate)
                self.candidates[internal_id] = candidate  # Key by internal_id

        # SECONDARY: Use keyword config hints (if provided, NOT hardcoded)
        if self.keyword_config:
            all_content = " ".join(u.content.lower() for u in units)

            for system_name, keywords in self.keyword_config.items():
                # Skip if already found via clustering
                if any(c.name == system_name for c in candidates):
                    continue

                # Count keyword occurrences
                keyword_counts = {kw: all_content.count(kw) for kw in keywords}
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
                        how_identified=f"Config-assisted: {total_matches} matches",
                    )
                    candidates.append(candidate)
                    self.candidates[internal_id] = candidate

        # Look for orphan clusters (elements that don't match any system)
        assigned: set[str] = set()
        for c in candidates:
            assigned.update(c.exemplar_elements)

        orphans = [u.id for u in units if u.id not in assigned]
        if orphans:
            # Analyze orphans for potential new library
            orphan_candidate = self._analyze_orphans([u for u in units if u.id in orphans])
            if orphan_candidate:
                candidates.append(orphan_candidate)
                self.candidates[orphan_candidate.internal_id] = orphan_candidate

        return candidates

    def _cluster_by_content(self, units: list[TrackedUnit]) -> dict[str, list[TrackedUnit]]:
        """Cluster units by content similarity using TF-IDF naming.

        Strategy:
        1. First cluster by reference graph (units that cite each other)
        2. Name clusters using TF-IDF (terms frequent in cluster, rare globally)

        TF-IDF naturally filters structural terms: words like 'function' appear
        everywhere (low IDF) while domain terms like 'field' cluster together
        (high IDF within cluster).
        """
        import math

        # Step 1: Build reference graph and cluster by connectivity
        ref_graph: dict[str, set[str]] = defaultdict(set)
        unit_map = {u.id: u for u in units}

        for unit in units:
            for ref in unit.references:
                ref_graph[unit.id].add(ref)
                # Add reverse edge for connectivity
                if ref in unit_map:
                    ref_graph[ref].add(unit.id)

        # Find connected components via BFS
        visited: set[str] = set()
        raw_clusters: list[list[TrackedUnit]] = []

        for unit in units:
            if unit.id in visited:
                continue

            # BFS to find connected component
            component: list[TrackedUnit] = []
            queue = [unit.id]

            while queue:
                current_id = queue.pop(0)
                if current_id in visited:
                    continue
                visited.add(current_id)

                if current_id in unit_map:
                    component.append(unit_map[current_id])

                for neighbor in ref_graph.get(current_id, []):
                    if neighbor not in visited and neighbor in unit_map:
                        queue.append(neighbor)

            if len(component) >= 2:  # Minimum cluster size
                raw_clusters.append(component)

        # Step 2: Name each cluster using TF-IDF
        # First compute global document frequency
        total_units = len(units)
        global_doc_freq: dict[str, int] = defaultdict(int)

        for unit in units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                global_doc_freq[word] += 1

        clusters: dict[str, list[TrackedUnit]] = {}

        for cluster_units in raw_clusters:
            # Compute TF within cluster
            cluster_tf: dict[str, int] = defaultdict(int)
            for unit in cluster_units:
                words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
                words = words - _ENGLISH_STOPWORDS
                for word in words:
                    cluster_tf[word] += 1

            # Compute TF-IDF for each word in cluster
            tfidf_scores: dict[str, float] = {}
            for word, tf in cluster_tf.items():
                # IDF = log(total_docs / docs_containing_word)
                df = global_doc_freq.get(word, 1)
                idf = math.log(total_units / df) if df > 0 else 0
                tfidf_scores[word] = tf * idf

            # Pick the highest TF-IDF word as cluster name
            if tfidf_scores:
                best_word = max(tfidf_scores, key=lambda w: tfidf_scores[w])
                cluster_name = best_word  # No prefix - just the domain term
            else:
                cluster_name = f"cluster_{len(clusters)}"

            # Handle name collisions
            if cluster_name in clusters:
                cluster_name = f"{cluster_name}_{len(clusters)}"

            clusters[cluster_name] = cluster_units

        return clusters

    def _extract_keywords(self, units: list[TrackedUnit]) -> list[str]:
        """Extract the most common keywords from a set of units."""
        word_freq: dict[str, int] = defaultdict(int)

        for unit in units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                word_freq[word] += 1

        # Return top keywords by frequency
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:10]]

    def _find_exemplars(self, units: list[TrackedUnit], keywords: list[str]) -> list[str]:
        """Find elements that best exemplify a keyword set."""
        scores: list[tuple[str, int]] = []

        for unit in units:
            content_lower = unit.content.lower()
            score = sum(content_lower.count(kw) for kw in keywords)
            if score > 0:
                scores.append((unit.id, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scores]

    def _analyze_orphans(
        self, orphan_units: list[TrackedUnit], all_units: list[TrackedUnit] | None = None
    ) -> CandidateLibrary | None:
        """Analyze orphan elements for potential new library.

        Uses TF-IDF to pick the most distinctive term as the name
        (not generic emerging_{word}).
        """
        import math

        if len(orphan_units) < 3:
            return None  # Too few to form a library

        # Compute global doc frequency (from all units if available)
        reference_units = all_units if all_units else orphan_units
        total_units = len(reference_units)
        global_doc_freq: dict[str, int] = defaultdict(int)
        for unit in reference_units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                global_doc_freq[word] += 1

        # Compute TF-IDF for orphan cluster
        cluster_tf: dict[str, int] = defaultdict(int)
        for unit in orphan_units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            words = words - _ENGLISH_STOPWORDS
            for word in words:
                cluster_tf[word] += 1

        tfidf_scores: dict[str, float] = {}
        for word, tf in cluster_tf.items():
            df = global_doc_freq.get(word, 1)
            idf = math.log(total_units / df) if df > 0 else 0
            tfidf_scores[word] = tf * idf

        if not tfidf_scores:
            return None

        # Pick highest TF-IDF word
        best_word = max(tfidf_scores, key=lambda w: tfidf_scores[w])
        top_keywords = sorted(tfidf_scores.keys(), key=lambda w: tfidf_scores[w], reverse=True)[:5]

        return CandidateLibrary(
            internal_id=self._generate_internal_id(),
            name=best_word,  # Just the domain term, no prefix
            description="Emerged from unassigned elements",
            keywords=top_keywords,
            exemplar_elements=[u.id for u in orphan_units[:5]],
            confidence=0.3,  # Low confidence for emerging
            how_identified="Orphan cluster analysis",
        )

    def suggest_from_references(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
        """Identify candidates based on reference patterns.

        Elements that reference each other heavily might form a system.
        Names clusters using TF-IDF (not generic ref_cluster_0).
        """
        # Build reference graph
        ref_graph: dict[str, set[str]] = defaultdict(set)
        unit_map = {u.id: u for u in units}
        for unit in units:
            for ref in unit.references:
                ref_graph[unit.id].add(ref)

        # Find clusters (elements that heavily reference each other)
        clusters = self._find_reference_clusters(ref_graph)

        # Compute global doc frequency for TF-IDF naming
        total_units = len(units)
        global_doc_freq: dict[str, int] = defaultdict(int)
        for unit in units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                global_doc_freq[word] += 1

        candidates = []
        used_names: set[str] = set()
        for cluster_ids in clusters:
            if len(cluster_ids) >= 3:
                # Get the actual units for this cluster
                cluster_units = [unit_map[uid] for uid in cluster_ids if uid in unit_map]
                if len(cluster_units) >= 2:
                    name = self._name_cluster_by_tfidf(
                        cluster_units, global_doc_freq, total_units, used_names
                    )
                    used_names.add(name)
                    candidate = CandidateLibrary(
                        internal_id=self._generate_internal_id(),
                        name=name,
                        description="Elements with strong mutual references",
                        keywords=[],
                        exemplar_elements=list(cluster_ids)[:5],
                        confidence=0.4,
                        how_identified="Reference pattern analysis",
                    )
                    candidates.append(candidate)

        return candidates

    def _find_reference_clusters(self, ref_graph: dict[str, set[str]]) -> list[set[str]]:
        """Find clusters of mutually-referencing elements."""
        clusters: list[set[str]] = []
        visited: set[str] = set()

        for node in ref_graph:
            if node in visited:
                continue

            # BFS to find connected component
            cluster: set[str] = set()
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

    def discover_with_all_signals(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
        """Combine ALL signals for library discovery.

        Signals (in order of weight):
        1. Reference graph structure (highest - who cites who)
        2. Unit type clustering (algorithms cluster differently than data structures)
        3. Relation annotations from prior iterations
        4. Content clustering (word-based seed)
        5. LLM system summaries (optional, expensive)

        Returns unified candidate list with combined confidence scores.
        """
        all_candidates: dict[str, CandidateLibrary] = {}
        candidate_evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)

        # Signal 1: Reference graph (high weight)
        ref_candidates = self.suggest_from_references(units)
        for c in ref_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append(
                {"signal": "reference_graph", "weight": 0.4, "elements": c.exemplar_elements}
            )

        # Signal 2: Unit type clustering
        type_candidates = self._cluster_by_unit_type(units)
        for c in type_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append(
                {"signal": "unit_type", "weight": 0.3, "elements": c.exemplar_elements}
            )

        # Signal 3: Relation annotations from prior iterations
        relation_candidates = self._extract_from_relations(units)
        for c in relation_candidates:
            all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append(
                {"signal": "relations", "weight": 0.15, "elements": c.exemplar_elements}
            )

        # Signal 4: Content clustering (word-based seed)
        content_candidates = self.identify_candidates(units)  # Existing method
        for c in content_candidates:
            if c.internal_id not in all_candidates:
                all_candidates[c.internal_id] = c
            candidate_evidence[c.internal_id].append(
                {"signal": "content_clustering", "weight": 0.1, "elements": c.exemplar_elements}
            )

        # Signal 5: LLM system summaries (optional)
        if self._llm:
            llm_candidates = self._llm_summarize_systems(units)
            for c in llm_candidates:
                all_candidates[c.internal_id] = c
                candidate_evidence[c.internal_id].append(
                    {"signal": "llm_summary", "weight": 0.05, "elements": c.exemplar_elements}
                )

        # Combine confidence scores using weighted evidence
        for internal_id, evidence_list in candidate_evidence.items():
            if internal_id in all_candidates:
                total_weight = sum(e["weight"] for e in evidence_list)
                all_candidates[internal_id].confidence = min(total_weight, 1.0)
                all_candidates[internal_id].how_identified = ", ".join(
                    f"{e['signal']}({e['weight']:.2f})" for e in evidence_list
                )

        return list(all_candidates.values())

    def _cluster_by_unit_type(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
        """Cluster by unit type - algorithms cluster differently than data structures.

        Insight: A system often has a characteristic "shape" of unit types.
        Names clusters using TF-IDF (not generic names like algorithm_system_0).
        """
        candidates = []

        # Compute global doc frequency for TF-IDF naming
        total_units = len(units)
        global_doc_freq: dict[str, int] = defaultdict(int)
        for unit in units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            for word in words:
                global_doc_freq[word] += 1

        # Group by unit type
        by_type: dict[UnitType, list[TrackedUnit]] = defaultdict(list)
        for unit in units:
            by_type[unit.unit_type].append(unit)

        # Algorithms often form systems
        if UnitType.ALGORITHM in by_type and len(by_type[UnitType.ALGORITHM]) >= 3:
            # Subcluster algorithms by their claims/references
            alg_clusters = self._subcluster_by_claims(by_type[UnitType.ALGORITHM])
            used_names: set[str] = set()
            for cluster in alg_clusters:
                if len(cluster) >= 2:
                    # Name using TF-IDF
                    name = self._name_cluster_by_tfidf(
                        cluster, global_doc_freq, total_units, used_names
                    )
                    used_names.add(name)
                    candidates.append(
                        CandidateLibrary(
                            internal_id=self._generate_internal_id(),
                            name=name,
                            description="Algorithms with related claims",
                            keywords=[],
                            exemplar_elements=[u.id for u in cluster[:5]],
                            confidence=0.5,
                            how_identified="Unit type + claim clustering",
                        )
                    )

        # Data structures often form cohesive systems
        if UnitType.DATA_STRUCTURE in by_type and len(by_type[UnitType.DATA_STRUCTURE]) >= 3:
            name = self._name_cluster_by_tfidf(
                by_type[UnitType.DATA_STRUCTURE], global_doc_freq, total_units, set()
            )
            candidates.append(
                CandidateLibrary(
                    internal_id=self._generate_internal_id(),
                    name=name,
                    description="Data structure definitions",
                    keywords=[],
                    exemplar_elements=[u.id for u in by_type[UnitType.DATA_STRUCTURE][:5]],
                    confidence=0.4,
                    how_identified="Unit type clustering (data structures)",
                )
            )

        return candidates

    def _subcluster_by_claims(self, algorithms: list[TrackedUnit]) -> list[list[TrackedUnit]]:
        """Subcluster algorithms by the claims they reference."""
        # Group by claim references
        claim_to_algs: dict[str, list[TrackedUnit]] = defaultdict(list)

        for alg in algorithms:
            claims_found = re.findall(r"\b(P?\d*C\d+)\b", alg.content)
            if claims_found:
                for claim in claims_found:
                    claim_to_algs[claim].append(alg)
            else:
                claim_to_algs["_no_claims"].append(alg)

        # Convert to clusters
        clusters = [algs for algs in claim_to_algs.values() if len(algs) >= 2]
        return clusters

    def _name_cluster_by_tfidf(
        self,
        cluster_units: list[TrackedUnit],
        global_doc_freq: dict[str, int],
        total_units: int,
        used_names: set[str],
    ) -> str:
        """Name a cluster using TF-IDF - pick the most distinctive term.

        TF-IDF naturally filters structural terms: words like 'function' appear
        everywhere (low IDF) while domain terms like 'field' cluster together
        (high IDF within cluster).
        """
        import math

        # Compute TF within cluster
        cluster_tf: dict[str, int] = defaultdict(int)
        for unit in cluster_units:
            words = set(re.findall(r"\b[a-z]{4,}\b", unit.content.lower()))
            words = words - _ENGLISH_STOPWORDS
            for word in words:
                cluster_tf[word] += 1

        # Compute TF-IDF for each word
        tfidf_scores: dict[str, float] = {}
        for word, tf in cluster_tf.items():
            df = global_doc_freq.get(word, 1)
            idf = math.log(total_units / df) if df > 0 else 0
            tfidf_scores[word] = tf * idf

        # Pick highest TF-IDF word not already used
        sorted_words = sorted(tfidf_scores.keys(), key=lambda w: tfidf_scores[w], reverse=True)
        for word in sorted_words:
            if word not in used_names:
                return word

        # Fallback if all names used
        base_name = sorted_words[0] if sorted_words else "cluster"
        counter = 1
        while f"{base_name}_{counter}" in used_names:
            counter += 1
        return f"{base_name}_{counter}"

    def _extract_from_relations(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
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
                candidates.append(
                    CandidateLibrary(
                        internal_id=self._generate_internal_id(),
                        name=lib_name,
                        description="From relation annotations",
                        keywords=[],
                        exemplar_elements=element_ids[:5],
                        confidence=0.35,
                        how_identified="Relation annotation extraction",
                    )
                )

        return candidates

    def _llm_summarize_systems(self, units: list[TrackedUnit]) -> list[CandidateLibrary]:
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

            # Strip markdown code fences if present (e.g., ```json ... ```)
            stripped = response.strip()
            if stripped.startswith("```"):
                # Extract content between code fences using regex
                match = re.search(r"```(?:json)?\s*\n(.*?)\n```", stripped, re.DOTALL)
                if match:
                    stripped = match.group(1)
                else:
                    # Fallback for compact one-line fences (e.g., ```json{"name":"x"}```)
                    # Remove surrounding backticks and optional "json" marker
                    lower = stripped.lower()
                    stripped = stripped.strip("`").strip()
                    if lower.startswith("json") and (len(lower) == 4 or not lower[4].isalnum()):
                        stripped = stripped[4:].strip()
                    stripped = stripped.strip("`").strip()

            systems = json.loads(stripped)

            candidates = []
            for sys in systems:
                candidates.append(
                    CandidateLibrary(
                        internal_id=self._generate_internal_id(),
                        name=sys["name"],
                        description=sys.get("description", "LLM-identified system"),
                        keywords=[],
                        exemplar_elements=sys.get("elements", [])[:5],
                        confidence=0.3,  # Lower confidence for LLM
                        how_identified="LLM system summary",
                    )
                )
            return candidates
        except Exception:
            return []
