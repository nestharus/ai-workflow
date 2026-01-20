"""
Entity resolution engine - FIRST-CLASS requirement.

When patch prose has vague references like "the algorithm" or "it",
we need to resolve them using:
- Annotations from the same file
- Prior patch versions
- Original inputs the patch references
- Intermediate composites ("smeared state")

Entity resolution failure -> gaps.md entry + keep remainder unit
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ResolutionContext:
    """Context available for resolving references."""

    # Patch dependency graph
    patch_chain: list[str]  # e.g., ["p1", "p3", "p5"] - p5 patches p3 patches p1

    # Available contexts in priority order
    current_file_ids: set[str] = field(default_factory=set)          # IDs declared in current file
    prior_patch_ids: dict[str, set[str]] = field(default_factory=dict)  # patch_id -> IDs it defined
    intermediate_ids: dict[str, set[str]] = field(default_factory=dict)  # intermediate_file -> IDs
    original_ids: dict[str, set[str]] = field(default_factory=dict)    # original_file -> IDs


@dataclass
class ResolutionResult:
    """Result of attempting to resolve a reference."""

    original_text: str
    resolved_to: str | None
    confidence: float
    evidence: list[str]  # Why we resolved to this
    context_used: str    # "current", "prior_patch", "intermediate", "original"


class ReferenceStore:
    """
    Interface for retrieving context to resolve references.

    Given a vague mention, retrieve top-k candidate contexts.

    Index primarily from DECLARED IDs + HEADINGS + KEYPHRASES,
    NOT hardcoded domain phrases. Domain-specific phrase lists are configurable.
    """

    def __init__(self, spec_folder: Path, config_path: Path | None = None) -> None:
        self.spec_folder = spec_folder
        self.index: dict[str, list[str]] = {}  # term -> [id, id, ...]
        self.phrase_config: dict[str, str] = {}  # Optional domain phrase config

        # Load optional domain phrase config (data-driven, not hardcoded)
        if config_path and config_path.exists():
            with open(config_path, encoding='utf-8') as f:
                self.phrase_config = yaml.safe_load(f).get('domain_phrases', {})

    def index_file(self, path: Path, content: str, file_type: str) -> None:
        """
        Index a file's content for later retrieval.

        Indexing hierarchy:
        1. Declared IDs (authoritative)
        2. Heading-based IDs
        3. NLP-extracted keyphrases
        4. Configurable domain phrases (from YAML, not hardcoded)
        """
        from spec_manager.core.annotations import AnnotationParser

        parser = AnnotationParser()

        # PRIMARY: Declared IDs - authoritative
        for decl in parser.parse_declarations(content):
            term = decl.id_value.lower()
            if term not in self.index:
                self.index[term] = []
            self.index[term].append(f"{file_type}:{path.name}:{decl.id_value}")

        # SECONDARY: Heading-based IDs
        heading_pattern = re.compile(
            r'^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)',
            re.MULTILINE
        )
        for match in heading_pattern.finditer(content):
            term = match.group(2).lower()
            if term not in self.index:
                self.index[term] = []
            self.index[term].append(f"{file_type}:{path.name}:heading:{match.group(2)}")

        # TERTIARY: NLP keyphrases
        self._index_keyphrases(content, path, file_type)

        # QUATERNARY: Configurable domain phrases (from config, not hardcoded)
        for phrase, category in self.phrase_config.items():
            if phrase.lower() in content.lower():
                term = phrase.lower()
                if term not in self.index:
                    self.index[term] = []
                self.index[term].append(f"{file_type}:{path.name}:phrase:{category}")

    def _index_keyphrases(self, content: str, path: Path, file_type: str) -> None:
        """Extract and index keyphrases using NLP."""
        try:
            import spacy
            nlp = spacy.load("en_core_web_sm")
            doc = nlp(content[:5000])

            for chunk in doc.noun_chunks:
                if len(chunk.text.split()) >= 2 and len(chunk.text) < 40:
                    term = chunk.text.lower()
                    if term not in self.index:
                        self.index[term] = []
                    self.index[term].append(f"{file_type}:{path.name}:keyphrase:{chunk.text}")
        except (ImportError, OSError):
            pass  # NLP not available, skip keyphrase indexing

    def retrieve(
        self,
        mention: str,
        context: ResolutionContext,
        top_k: int = 5
    ) -> list[tuple[str, float]]:
        """
        Retrieve candidate resolutions for a mention.

        Returns list of (candidate_id, confidence) pairs.
        """
        candidates: list[tuple[str, float]] = []

        # Normalize mention
        mention_lower = mention.lower().strip()

        # Check exact matches first
        if mention_lower in self.index:
            for entry in self.index[mention_lower][:top_k]:
                candidates.append((entry, 1.0))

        # Check partial matches
        for term, entries in self.index.items():
            if term in mention_lower or mention_lower in term:
                for entry in entries[:2]:
                    if (entry, 1.0) not in candidates:
                        candidates.append((entry, 0.7))

        # Sort by confidence
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]


class EntityResolver:
    """
    Resolves vague references in patch content.

    This is a FIRST-CLASS component, not just a strategy stub.
    """

    def __init__(self, reference_store: ReferenceStore) -> None:
        self.store = reference_store
        self.failures: list[tuple[str, str]] = []  # (text, file)

    def resolve(
        self,
        text: str,
        context: ResolutionContext
    ) -> ResolutionResult:
        """Attempt to resolve a vague reference."""

        # Find candidates
        candidates = self.store.retrieve(text, context)

        if not candidates:
            # Failed to resolve
            self.failures.append((text, "no_candidates"))
            return ResolutionResult(
                original_text=text,
                resolved_to=None,
                confidence=0.0,
                evidence=["No candidates found in any context"],
                context_used="none"
            )

        # Take best candidate
        best_id, confidence = candidates[0]

        # Determine which context it came from
        context_used = "unknown"
        if "current:" in best_id:
            context_used = "current"
        elif "prior_patch:" in best_id:
            context_used = "prior_patch"
        elif "intermediate:" in best_id:
            context_used = "intermediate"
        elif "original:" in best_id:
            context_used = "original"

        return ResolutionResult(
            original_text=text,
            resolved_to=best_id.split(":")[-1],  # Extract actual ID
            confidence=confidence,
            evidence=[f"Found in {best_id}"],
            context_used=context_used
        )

    def get_failures_as_gaps(self) -> list[dict[str, Any]]:
        """Get resolution failures formatted for gaps.md."""
        return [
            {
                "type": "entity_resolution_failure",
                "original_text": text,
                "location": location,
                "severity": "warning"
            }
            for text, location in self.failures
        ]
