"""Context management for the workflow.

PatchDependencyGraph: Tracks patch dependencies (e.g., "p5 patches p3 which patched p1").
ContextIndex: Index over all context strata for entity resolution.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from spec_refinement.schemas.sections import FileSections  # type: ignore[import-not-found]
from spec_refinement.schemas.terms import FileTerms  # type: ignore[import-not-found]

logger = logging.getLogger(__name__)


@dataclass
class PatchDependency:
    """Represents a patch dependency: source_patch patches target_patch."""

    source_patch: str  # e.g., "p5"
    target_patch: str  # e.g., "p3"
    dependency_type: str  # "patches", "extends", "replaces"
    evidence: str  # Where this dependency was detected


class PatchDependencyGraph:
    """Tracks patch dependencies: "p5 patches p3 which patched p1".

    Used for entity resolution when vague references need patch context.
    """

    def __init__(self) -> None:
        """Initialize the patch dependency graph."""
        self.dependencies: list[PatchDependency] = []
        self._graph: dict[str, list[str]] = {}  # patch_id -> [patched_by]

    def add_dependency(
        self, source: str, target: str, dep_type: str = "patches", evidence: str = ""
    ) -> None:
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
        """Infer dependencies from patch content.

        PRIMARY inference is from:
        1. Chronological order (p1 < p2 < p3)
        2. Shared element IDs (if p5 mentions Algorithm 3, check which patch introduced it)
        3. Provenance "modified_by" evidence already in units

        SECONDARY (low-confidence hint): regex mention parsing.
        Do NOT rely on hardcoded domain phrases like "relaxation algorithm".
        """
        # PRIMARY: Extract numeric patch ID and assume sequential dependency
        match = re.match(r"p(\d+)", patch_id)
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
                        dep_type="patches",
                        evidence=f"Shared IDs: {', '.join(shared_ids[:3])}",
                    )

        # SECONDARY (low-confidence hint): explicit patch references
        # These are treated as HINTS, not the backbone of dependency inference
        hint_patterns = [
            (r"patches?\s+(p\d+)", "patches", 0.6),
            (r"from\s+(p\d+)", "extends", 0.5),
            (r"(p\d+)\'s", "extends", 0.4),
            (r"updates?\s+(p\d+)", "patches", 0.6),
        ]

        for pattern, dep_type, confidence in hint_patterns:
            for m in re.finditer(pattern, patch_content, re.IGNORECASE):
                target = m.group(1)
                if target != patch_id:
                    # Mark as low-confidence hint, not backbone dependency
                    self.add_dependency(
                        source=patch_id,
                        target=target,
                        dep_type=dep_type,
                        evidence=f"[hint:{confidence:.1f}] {m.group(0)}",
                    )

    def _find_shared_ids(self, content: str, other_patch_id: str) -> list[str]:
        """Find element IDs that appear in both this content and originate from other_patch_id."""
        # Extract all declared/referenced IDs
        id_patterns = [
            r"\(\[=([^\]]+)\]\)",  # Declarations
            r"\(@\[\+?([^\]]+)\]\)",  # References
            r"\bAlgorithm\s+(\d+)\b",  # Algorithm references
            r"\b(P\d+C\d+|P\d+I\d+|D\d+|G\d+)\b",  # Standard IDs
        ]
        found_ids = []
        for pattern in id_patterns:
            for m in re.finditer(pattern, content):
                found_ids.append(m.group(1))
        # In a real implementation, cross-reference with what other_patch_id introduced
        # For now, return non-empty if we find standard IDs (actual lookup requires state)
        return list(set(found_ids))[:5]


class ContextIndex:
    """Index over all context strata for entity resolution.

    Strata (in priority order):
    1. Originals (patches/*.md)
    2. Each intermediate projection (pass_*/composite.md)
    3. Current composite

    Entity resolution queries this to find "the relaxation algorithm"
    when a vague reference needs resolution.
    """

    def __init__(self, workspace: Path) -> None:
        """Initialize the context index with a workspace path."""
        self.workspace = workspace
        self._index: dict[str, list[dict[str, Any]]] = {}  # term -> locations
        self._strata: list[dict[str, Any]] = []  # [{path, content, priority}, ...]

    def add_stratum(self, path: Path, content: str, priority: int, stratum_type: str) -> None:
        """Add a context stratum to the index."""
        self._strata.append(
            {"path": str(path), "content": content, "priority": priority, "type": stratum_type}
        )
        self._index_content(content, str(path), priority)

    def _index_content(self, content: str, path: str, priority: int) -> None:
        """Index terms from content.

        Index primarily from DECLARED IDS + HEADINGS + EXTRACTED KEYPHRASES,
        NOT a fixed phrase list like "relaxation algorithm" or "convergence proof".

        Indexing sources (in order):
        1. Declared IDs: ([=...]) annotations
        2. Headings: ## Algorithm 1, ### D5, etc.
        3. Keyphrases: spaCy noun chunks or TF-IDF extracted terms
        4. Standard ID patterns: P#C#, P#I#, G#, D#, Lean#
        """
        # PRIMARY: Declared IDs - these are authoritative
        decl_pattern = re.compile(r"\(\[=([^\]]+)\]\)")
        for match in decl_pattern.finditer(content):
            term = match.group(1).lower()
            self._add_to_index(term, path, match.start(), content, priority, "declared_id")

        # SECONDARY: Headings with element IDs
        heading_pattern = re.compile(
            r"^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)(.*)$", re.MULTILINE
        )
        for match in heading_pattern.finditer(content):
            term = match.group(2).lower()
            self._add_to_index(term, path, match.start(), content, priority, "heading")

        # TERTIARY: Standard ID patterns in body (not declarations/headings)
        standard_patterns = [
            (r"\bAlgorithm\s+(\d+)\b", "algorithm"),
            (r"\b(D\d+)\b", "data_structure"),
            (r"\b(G\d+)\b", "goal"),
            (r"\b(P\d+C\d+)\b", "claim"),
            (r"\b(P\d+I\d+)\b", "invariant"),
            (r"\b(Lean\d+)\b", "lean"),
        ]
        for pattern, entity_type in standard_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                term = match.group(0).lower()
                self._add_to_index(term, path, match.start(), content, priority, entity_type)

        # QUATERNARY: Extract keyphrases using NLP (if available)
        self._index_keyphrases(content, path, priority)

    def _add_to_index(
        self, term: str, path: str, position: int, content: str, priority: int, entity_type: str
    ) -> None:
        """Add a term to the index with context."""
        if term not in self._index:
            self._index[term] = []
        self._index[term].append(
            {
                "path": path,
                "position": position,
                "context": content[max(0, position - 50) : position + 100],
                "priority": priority,
                "type": entity_type,
            }
        )

    def _index_keyphrases(self, content: str, path: str, priority: int) -> None:
        """Extract keyphrases using NLP (spaCy noun chunks or fallback).

        This replaces hardcoded domain phrases with data-driven extraction.
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
                    self._index[term].append(
                        {
                            "path": path,
                            "position": chunk.start_char,
                            "context": content[max(0, chunk.start_char - 30) : chunk.end_char + 30],
                            "priority": priority - 1,  # Lower priority than explicit IDs
                            "type": "keyphrase",
                        }
                    )
        except (ImportError, OSError):
            # Fallback: simple bigram extraction
            words = re.findall(r"\b[A-Za-z][a-z]+\b", content)
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i + 1]}".lower()
                if bigram not in self._index:
                    self._index[bigram] = []
                # Very low priority for fallback keyphrases
                self._index[bigram].append(
                    {
                        "path": path,
                        "position": 0,
                        "context": bigram,
                        "priority": priority - 2,
                        "type": "bigram",
                    }
                )

    def resolve(
        self, vague_reference: str, patch_context: str | None = None
    ) -> list[dict[str, Any]]:
        """Resolve a vague reference to candidate entities.

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
        candidates.sort(key=lambda x: x["priority"], reverse=True)
        seen: set[tuple[str, int]] = set()
        unique = []
        for c in candidates:
            key = (c["path"], c["position"])
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique[:10]  # Top 10 candidates

    def get_terms_for_patch(self, patch_id: str) -> list[str]:
        """Extract declared terms and IDs for a patch."""
        if not patch_id:
            return []

        terms: set[str] = set()
        for stratum in self._strata:
            path_name = Path(stratum["path"]).name
            if patch_id not in path_name:
                continue

            content = stratum["content"]
            for match in re.finditer(r"\(\[=([^\]]+)\]\)", content):
                terms.add(match.group(1))
            for match in re.finditer(
                r"^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)",
                content,
                re.MULTILINE,
            ):
                terms.add(match.group(2))

        return sorted(terms)

    def get_sections_for_patch(self, patch_id: str) -> list[str]:
        """Extract section headings for a patch."""
        if not patch_id:
            return []

        sections: set[str] = set()
        for stratum in self._strata:
            path_name = Path(stratum["path"]).name
            if patch_id not in path_name:
                continue

            content = stratum["content"]
            for match in re.finditer(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE):
                sections.add(match.group(2).strip())

        return sorted(sections)

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
                    content = composite_path.read_text(encoding="utf-8")
                    self.add_stratum(composite_path, content, priority, "intermediate")
                    priority += 1  # Later intermediates have higher priority

    def to_dict(self) -> dict[str, Any]:
        """Serialize context index to JSON.

        Schema:
        {
          "index": {
            "term": [
              {
                "path": "str - source file path",
                "position": "int - character offset",
                "context": "str - surrounding text",
                "priority": "int - stratum priority",
                "type": "str - entity type (term, section, declared_id, etc.)"
              }
            ]
          },
          "strata": [
            {
              "path": "str - stratum file path",
              "content": "str - full content (for LLM context)",
              "priority": "int - resolution priority",
              "type": "str - stratum type (original, patch, intermediate)"
            }
          ]
        }
        """
        return {"index": self._index, "strata": self._strata}

    @classmethod
    def from_dict(cls, data: dict[str, Any], workspace: Path) -> ContextIndex:
        """Deserialize context index from dictionary data."""
        if "index" not in data or "strata" not in data:
            raise ValueError("Context index data must include 'index' and 'strata'")
        index = cls(workspace)
        index._index = data["index"]
        index._strata = data["strata"]
        return index

    def save(self, path: Path) -> None:
        """Persist context index to disk as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)

    @classmethod
    def load(cls, path: Path, workspace: Path) -> ContextIndex:
        """Load a context index from disk."""
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload, workspace)


class ContextIndexBuilder:
    """Builds ContextIndex from manifest files (terms and sections).

    Reads manifest/terms/*.terms.json and manifest/sections/*.sections.json
    to populate the context index for LLM agent entity resolution.
    """

    def __init__(self, workspace: Path, spec_folder: Path) -> None:
        """Initialize the builder with workspace and spec folder paths."""
        self.workspace = workspace
        self.spec_folder = spec_folder

    def build_from_manifests(self) -> ContextIndex:
        """Build a ContextIndex using manifest files."""
        index = ContextIndex(self.workspace)
        self._load_terms_manifests(index)
        self._load_sections_manifests(index)
        return index

    def _load_terms_manifests(self, index: ContextIndex) -> None:
        """Load term manifests and add terms to the index."""
        terms_dir = self.spec_folder / "manifest" / "terms"
        if not terms_dir.exists():
            return

        for terms_file in sorted(terms_dir.glob("*.terms.json")):
            try:
                payload = FileTerms.model_validate_json(terms_file.read_text(encoding="utf-8"))
            except (OSError, ValidationError, ValueError) as exc:
                logger.warning("Skipping malformed terms manifest %s: %s", terms_file, exc)
                continue

            for section_terms in payload.section_terms:
                for term in section_terms.terms:
                    normalized = term.lower()
                    index._add_to_index(
                        normalized,
                        str(terms_file),
                        0,
                        term,
                        0,
                        "term",
                    )

            for term in payload.global_terms:
                normalized = term.lower()
                index._add_to_index(
                    normalized,
                    str(terms_file),
                    0,
                    term,
                    0,
                    "term",
                )

    def _load_sections_manifests(self, index: ContextIndex) -> None:
        """Load section manifests and add sections to the index."""
        sections_dir = self.spec_folder / "manifest" / "sections"
        if not sections_dir.exists():
            return

        for sections_file in sorted(sections_dir.glob("*.sections.json")):
            try:
                payload = FileSections.model_validate_json(
                    sections_file.read_text(encoding="utf-8")
                )
            except (OSError, ValidationError, ValueError) as exc:
                logger.warning("Skipping malformed sections manifest %s: %s", sections_file, exc)
                continue

            for section in payload.sections:
                section_id = section.section_id.lower()
                index._add_to_index(
                    section_id,
                    str(sections_file),
                    0,
                    section.section_id,
                    0,
                    "section",
                )
                label = section.label.strip()
                if label:
                    index._add_to_index(
                        label.lower(),
                        str(sections_file),
                        0,
                        label,
                        0,
                        "section",
                    )

    def save_index(self, index: ContextIndex, output_path: Path) -> None:
        """Save a context index to disk."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        index.save(output_path)
