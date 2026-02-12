"""Unitizer strategies - implement the granularity ladder.

When annotations are sparse, emit fine atoms (line/sentence/clause) even
with zero declarations. Don't rely solely on ([=...]) boundaries.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Any

from spec_manager.core.provenance import (
    GranularityLevel,
    SourceLocation,
    TrackedUnit,
    UnitType,
)


class Unitizer(ABC):
    """Base class for unitizers."""

    @property
    @abstractmethod
    def granularity(self) -> GranularityLevel:
        """The granularity level this unitizer produces."""
        pass

    @abstractmethod
    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        """Split content into tracked units."""
        pass


class LineUnitizer(Unitizer):
    """Line-level unitization - maximum tracking granularity.
    Use for dirty prose with sparse/no annotations.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.LINE

    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []

        for line_num, line in enumerate(content.splitlines(), start=1):
            if line.strip():  # Skip empty lines
                content_hash = hashlib.sha256(line.encode()).hexdigest()
                units.append(
                    TrackedUnit(
                        id=f"_line_{file_path}_{line_num}",
                        content=line,
                        unit_type=UnitType.PROSE,
                        source=SourceLocation(
                            file=file_path,
                            line_start=line_num,
                            line_end=line_num,
                            patch_id=patch_id,
                        ),
                        introduced_by=patch_id or "unknown",
                        granularity=self.granularity,
                        content_hash=content_hash,
                    )
                )

        return units


class SentenceUnitizer(Unitizer):
    """Sentence-level unitization using spaCy.
    Use for semi-structured text.
    """

    def __init__(self) -> None:
        self._nlp: Any = None

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.SENTENCE

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            try:
                import spacy

                self._nlp = spacy.load("en_core_web_sm")
            except (ImportError, OSError):
                # Fallback: simple sentence splitting
                self._nlp = "fallback"
        return self._nlp

    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []
        nlp = self._get_nlp()

        if nlp == "fallback":
            # Simple fallback: split on sentence-ending punctuation
            sentences = re.split(r"(?<=[.!?])\s+", content)
        else:
            doc = nlp(content)
            sentences = [sent.text for sent in doc.sents]

        # Track line numbers approximately
        current_pos = 0
        line_num = 1

        for i, sent in enumerate(sentences):
            sent = sent.strip()
            if not sent:
                continue

            # Find position in original content
            pos = content.find(sent, current_pos)
            if pos >= 0:
                line_num = content[:pos].count("\n") + 1
                current_pos = pos + len(sent)

            content_hash = hashlib.sha256(sent.encode()).hexdigest()
            units.append(
                TrackedUnit(
                    id=f"_sent_{file_path}_{i + 1}",
                    content=sent,
                    unit_type=UnitType.PROSE,
                    source=SourceLocation(
                        file=file_path, line_start=line_num, line_end=line_num, patch_id=patch_id
                    ),
                    introduced_by=patch_id or "unknown",
                    granularity=self.granularity,
                    content_hash=content_hash,
                )
            )

        return units


class ClauseUnitizer(Unitizer):
    """Clause-level unitization using spaCy dependency parsing.
    Use for complex compound statements.
    """

    def __init__(self) -> None:
        self._nlp: Any = None

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.CLAUSE

    def _get_nlp(self) -> Any:
        if self._nlp is None:
            try:
                import spacy

                self._nlp = spacy.load("en_core_web_sm")
            except (ImportError, OSError):
                self._nlp = "fallback"
        return self._nlp

    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        units = []
        nlp = self._get_nlp()

        if nlp == "fallback":
            # Fallback: split on conjunction and semicolons
            clauses = re.split(r";\s*|\s+and\s+|\s+or\s+", content)
        else:
            doc = nlp(content)
            clauses = []
            for sent in doc.sents:
                # Find clause roots (verbs with subjects)
                for token in sent:
                    if token.dep_ in ("ROOT", "conj") and token.pos_ == "VERB":
                        clause = " ".join([t.text for t in token.subtree])
                        if clause.strip():
                            clauses.append(clause)

                if not clauses:
                    clauses = [sent.text for sent in doc.sents]

        line_num = 1
        for i, clause in enumerate(clauses):
            clause = clause.strip()
            if not clause:
                continue

            content_hash = hashlib.sha256(clause.encode()).hexdigest()
            units.append(
                TrackedUnit(
                    id=f"_clause_{file_path}_{i + 1}",
                    content=clause,
                    unit_type=UnitType.PROSE,
                    source=SourceLocation(
                        file=file_path, line_start=line_num, line_end=line_num, patch_id=patch_id
                    ),
                    introduced_by=patch_id or "unknown",
                    granularity=self.granularity,
                    content_hash=content_hash,
                )
            )

        return units


class LLMUnitizer(Unitizer):
    """LLM-assisted unitization for hard-to-segment prose.

    Uses LLM to identify:
    - Clause boundaries in run-on sentences
    - Implicit requirements hidden in narrative
    - Logical units that span multiple sentences
    """

    def __init__(self, llm_client: Any = None) -> None:
        self._llm = llm_client

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.CLAUSE

    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        """LLM-assisted unitization.

        If no LLM available, falls back to sentence unitizer.
        """
        if not self._llm:
            # Fallback to sentence unitizer
            return SentenceUnitizer().unitize(content, file_path, patch_id)

        # Prompt LLM for clause extraction
        prompt = (
            "Split the following text into logical units "
            "(clauses, requirements, or statements).\n"
            "Each unit should express ONE idea or requirement.\n"
            "Return as JSON array of strings.\n\n"
            f"Text:\n{content}\n\n"
            'Output format: ["unit 1", "unit 2", ...]'
        )

        try:
            response = self._llm.complete(prompt)
            import json

            clauses = json.loads(response)
        except Exception:
            # Fallback on error
            return SentenceUnitizer().unitize(content, file_path, patch_id)

        units = []
        for i, clause in enumerate(clauses):
            clause = clause.strip()
            if not clause:
                continue

            content_hash = hashlib.sha256(clause.encode()).hexdigest()
            units.append(
                TrackedUnit(
                    id=f"_llm_unit_{file_path}_{i + 1}",
                    content=clause,
                    unit_type=UnitType.PROSE,
                    source=SourceLocation(
                        file=file_path,
                        line_start=1,  # LLM doesn't track line numbers
                        line_end=1,
                        patch_id=patch_id,
                    ),
                    introduced_by=patch_id or "unknown",
                    granularity=self.granularity,
                    content_hash=content_hash,
                )
            )

        return units


class SectionUnitizer(Unitizer):
    """Section-level unitization using ([=...]) annotations and headers.
    Use for clean, well-annotated content.
    """

    @property
    def granularity(self) -> GranularityLevel:
        return GranularityLevel.SECTION

    def unitize(
        self, content: str, file_path: str, patch_id: str | None = None
    ) -> list[TrackedUnit]:
        # Existing provenance tracker logic handles this case
        from spec_manager.core.provenance import ProvenanceTracker

        tracker = ProvenanceTracker()
        return tracker.extract_units_from_file(content, file_path, patch_id)


class UnitizationSelector:
    """Selects appropriate unitizer based on content analysis.

    Key principle: When annotations are sparse, emit FINE atoms.
    """

    def select_unitizer(self, content: str) -> Unitizer:
        """Select unitizer based on content characteristics."""
        # Count annotation density
        decl_count = content.count("([=")
        line_count = len(content.splitlines())
        density = decl_count / max(line_count, 1)

        # Check for clear sentence structure
        sentence_ends = len(re.findall(r"[.!?]\s+[A-Z]", content))
        has_sentences = sentence_ends > 2

        # Check for complex structure (conjunctions, semicolons)
        has_complex = bool(re.search(r";\s|\s+and\s+.*\s+and\s+", content))

        if density > 0.1:
            # Well-annotated: use section boundaries
            return SectionUnitizer()
        elif has_complex:
            # Complex statements: clause-level
            return ClauseUnitizer()
        elif has_sentences:
            # Clear sentences: sentence-level
            return SentenceUnitizer()
        else:
            # Messy prose: line-level for maximum tracking
            return LineUnitizer()
