"""Entity resolution engine - FIRST-CLASS requirement.

When patch prose has vague references like "the algorithm" or "it",
we need to resolve them using:
- Annotations from the same file
- Prior patch versions
- Original inputs the patch references
- Intermediate composites ("smeared state")

Entity resolution failure -> gaps.md entry + keep remainder unit
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ResolutionContext:
    """Context available for resolving references."""

    # Patch dependency graph
    patch_chain: list[str]  # e.g., ["p1", "p3", "p5"] - p5 patches p3 patches p1

    # Available contexts in priority order
    current_file_ids: set[str] = field(default_factory=set)  # IDs declared in current file
    prior_patch_ids: dict[str, set[str]] = field(default_factory=dict)  # patch_id -> IDs it defined
    intermediate_ids: dict[str, set[str]] = field(default_factory=dict)  # intermediate_file -> IDs
    original_ids: dict[str, set[str]] = field(default_factory=dict)  # original_file -> IDs


@dataclass
class ResolutionResult:
    """Result of attempting to resolve a reference."""

    original_text: str
    resolved_to: str | None
    confidence: float
    evidence: list[str]  # Why we resolved to this
    context_used: str  # "current", "prior_patch", "intermediate", "original"


class ReferenceStore:
    """Interface for retrieving context to resolve references.

    Given a vague mention, retrieve top-k candidate contexts.

    Index primarily from DECLARED IDs + HEADINGS + KEYPHRASES,
    NOT hardcoded domain phrases. Domain-specific phrase lists are configurable.
    """

    def __init__(self, spec_folder: Path, config_path: Path | None = None) -> None:
        self.spec_folder = spec_folder
        self.index: dict[str, list[str]] = {}  # term -> [id, id, ...]
        self.phrase_config: dict[str, str] = {}  # Optional domain phrase config
        self.diagnostics: list[dict[str, str]] = []

        # Load optional domain phrase config (data-driven, not hardcoded)
        if config_path and config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                self.phrase_config = yaml.safe_load(f).get("domain_phrases", {})

    def index_file(self, path: Path, content: str, file_type: str) -> None:
        """Index a file's content for later retrieval.

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
            r"^(#{1,6})\s+(Algorithm\s+\d+|D\d+|G\d+|P\d+C\d+|P\d+I\d+|Lean\d+)", re.MULTILINE
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
        except (ImportError, OSError) as exc:
            diagnostic = {
                "type": "keyphrase_index_unavailable",
                "file": path.name,
                "reason": exc.__class__.__name__,
            }
            self.diagnostics.append(diagnostic)
            logger.info(
                "Skipping keyphrase indexing for %s (%s)",
                path.name,
                exc.__class__.__name__,
            )

    @staticmethod
    def _normalize_id_set(values: set[str]) -> set[str]:
        return {value.lower() for value in values}

    @staticmethod
    def _entry_identifier(entry: str) -> str:
        return entry.split(":")[-1].lower()

    def _candidate_tier(self, entry: str, context: ResolutionContext) -> tuple[int, int]:
        """Rank candidates by context authority.

        Lower values are higher authority:
        current file -> prior patches -> intermediates -> originals -> unknown.
        """
        entry_id = self._entry_identifier(entry)
        source = entry.split(":", 1)[0]

        if entry_id in self._normalize_id_set(context.current_file_ids):
            return (0, 0)

        patch_rank = {patch_id: idx for idx, patch_id in enumerate(reversed(context.patch_chain))}
        prior_matches = [
            patch_rank.get(patch_id, len(patch_rank))
            for patch_id, ids in context.prior_patch_ids.items()
            if entry_id in self._normalize_id_set(ids)
        ]
        if prior_matches:
            return (1, min(prior_matches))

        for index, key in enumerate(sorted(context.intermediate_ids)):
            if entry_id in self._normalize_id_set(context.intermediate_ids[key]):
                return (2, index)

        for index, key in enumerate(sorted(context.original_ids)):
            if entry_id in self._normalize_id_set(context.original_ids[key]):
                return (3, index)

        if source.startswith("current"):
            return (4, 0)
        if source.startswith("prior_patch"):
            return (5, 0)
        if source.startswith("intermediate"):
            return (6, 0)
        if source.startswith("original"):
            return (7, 0)
        return (8, 0)

    def candidate_tier(self, entry: str, context: ResolutionContext) -> tuple[int, int]:
        """Expose candidate tier for ambiguity checks in the resolver."""
        return self._candidate_tier(entry, context)

    def candidate_context(self, entry: str, context: ResolutionContext) -> str:
        """Return the context label used for a ranked candidate."""
        tier, _ = self._candidate_tier(entry, context)
        if tier in {0, 4}:
            return "current"
        if tier in {1, 5}:
            return "prior_patch"
        if tier in {2, 6}:
            return "intermediate"
        if tier in {3, 7}:
            return "original"
        return "unknown"

    def retrieve(
        self, mention: str, context: ResolutionContext, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Retrieve candidate resolutions for a mention.

        Returns list of (candidate_id, confidence) pairs.
        """
        candidates: dict[str, float] = {}

        # Normalize mention
        mention_lower = mention.lower().strip()

        # Check exact matches first
        if mention_lower in self.index:
            for entry in self.index[mention_lower]:
                candidates[entry] = max(candidates.get(entry, 0.0), 1.0)

        # Check partial matches
        for term, entries in self.index.items():
            if term in mention_lower or mention_lower in term:
                for entry in entries:
                    candidates[entry] = max(candidates.get(entry, 0.0), 0.7)

        ranked = [
            (entry, confidence, self._candidate_tier(entry, context))
            for entry, confidence in candidates.items()
        ]
        ranked.sort(key=lambda item: (item[2], -item[1], item[0]))
        return [(entry, confidence) for entry, confidence, _ in ranked[:top_k]]


class EntityResolver:
    """Resolves vague references in patch content.

    This is a FIRST-CLASS component, not just a strategy stub.
    """

    def __init__(self, reference_store: ReferenceStore) -> None:
        self.store = reference_store
        self.failures: list[dict[str, Any]] = []

    @staticmethod
    def _failure_location(context: ResolutionContext) -> dict[str, Any]:
        return {
            "patch_chain": list(context.patch_chain),
            "current_file_ids": sorted(context.current_file_ids),
            "prior_patch_ids": {
                patch_id: sorted(ids) for patch_id, ids in sorted(context.prior_patch_ids.items())
            },
            "intermediate_ids": {
                key: sorted(ids) for key, ids in sorted(context.intermediate_ids.items())
            },
            "original_ids": {key: sorted(ids) for key, ids in sorted(context.original_ids.items())},
        }

    def resolve(self, text: str, context: ResolutionContext) -> ResolutionResult:
        """Attempt to resolve a vague reference."""
        # Find candidates
        candidates = self.store.retrieve(text, context)

        if not candidates:
            # Failed to resolve
            self.failures.append(
                {
                    "original_text": text,
                    "reason": "no_candidates",
                    "location": self._failure_location(context),
                    "candidates": [],
                }
            )
            return ResolutionResult(
                original_text=text,
                resolved_to=None,
                confidence=0.0,
                evidence=["No candidates found in any context"],
                context_used="none",
            )

        # Take best candidate unless there is unresolved ambiguity at the same authority tier.
        best_id, confidence = candidates[0]
        best_tier = self.store.candidate_tier(best_id, context)
        if len(candidates) > 1:
            second_id, second_confidence = candidates[1]
            second_tier = self.store.candidate_tier(second_id, context)
            if best_tier == second_tier and abs(confidence - second_confidence) <= 0.1:
                ambiguous_candidates = [entry for entry, _ in candidates[:3]]
                self.failures.append(
                    {
                        "original_text": text,
                        "reason": "ambiguous_candidates",
                        "location": self._failure_location(context),
                        "candidates": ambiguous_candidates,
                    }
                )
                return ResolutionResult(
                    original_text=text,
                    resolved_to=None,
                    confidence=confidence,
                    evidence=[f"Ambiguous candidates: {ambiguous_candidates}"],
                    context_used="ambiguous",
                )

        # Determine which context it came from
        context_used = self.store.candidate_context(best_id, context)

        return ResolutionResult(
            original_text=text,
            resolved_to=best_id.split(":")[-1],  # Extract actual ID
            confidence=confidence,
            evidence=[f"Found in {best_id}"],
            context_used=context_used,
        )

    def get_failures_as_gaps(self) -> list[dict[str, Any]]:
        """Get resolution failures formatted for gaps.md."""
        return [
            {
                "type": "entity_resolution_failure",
                "original_text": failure["original_text"],
                "location": failure["location"],
                "reason": failure["reason"],
                "candidates": failure.get("candidates", []),
                "severity": "warning",
            }
            for failure in self.failures
        ]
