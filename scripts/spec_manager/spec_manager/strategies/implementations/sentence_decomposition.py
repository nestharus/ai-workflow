"""
Sentence decomposition strategy.

This strategy splits compound sentences into atomic units so each
can be tracked independently. This reduces risk of losing part of
a compound statement during transformation.

Example:
  Input: "The algorithm must handle edge cases and log errors"
  Output:
    - "The algorithm must handle edge cases"
    - "The algorithm must log errors"
"""

from __future__ import annotations

import re
from typing import Any

from spec_manager.core.provenance import TrackedUnit, UnitType
from spec_manager.strategies.base import (
    Strategy,
    StrategyDefinition,
    ProcessingContext,
    StrategyResult,
    StrategyPhase,
    Tool,
)


class SentenceDecompositionStrategy(Strategy):
    """Decomposes compound sentences into atomic units."""

    def __init__(
        self,
        definition: StrategyDefinition | None = None,
        tools: dict[str, Tool] | None = None
    ) -> None:
        self.definition = definition
        self.tools = tools or {}
        self._splitter = self.tools.get('spacy_splitter') or self._simple_split

    @property
    def name(self) -> str:
        return "sentence_decomposition"

    @property
    def purpose(self) -> str:
        return "Split compound sentences to track atomic claims independently"

    @property
    def risk_addressed(self) -> str:
        return "Compound meaning lost in translation - 'A and B' becomes just 'A'"

    @property
    def phases(self) -> list[StrategyPhase]:
        return [StrategyPhase.DECOMPOSITION, StrategyPhase.CLEANING]

    def applies_to(self, context: ProcessingContext) -> bool:
        """Check if any units have compound sentences."""
        compound_indicators = [' and ', ' or ', '; ', ', and ', ', or ']

        for unit in context.units:
            # Only decompose prose, not structured content
            if unit.unit_type not in (UnitType.PROSE, UnitType.UNKNOWN):
                continue

            content_lower = unit.content.lower()
            if any(indicator in content_lower for indicator in compound_indicators):
                return True

        return False

    def execute(self, context: ProcessingContext) -> StrategyResult:
        """Execute sentence decomposition."""
        output_units: list[TrackedUnit] = []
        actions: list[str] = []
        issues: list[str] = []

        for unit in context.units:
            # Don't decompose structured content
            if unit.unit_type not in (UnitType.PROSE, UnitType.UNKNOWN):
                output_units.append(unit)
                continue

            # Split into sentences
            sentences = self._splitter(unit.content)

            if len(sentences) <= 1:
                output_units.append(unit)
                continue

            # Create new units for each sentence
            actions.append(f"Split {unit.id} into {len(sentences)} atoms")

            for i, sentence in enumerate(sentences):
                new_unit = TrackedUnit(
                    id=f"{unit.id}_atom_{i+1}",
                    content=sentence.strip(),
                    unit_type=unit.unit_type,
                    source=unit.source,  # Same source
                    introduced_by=unit.introduced_by,
                    modified_by=unit.modified_by.copy(),
                    declarations=unit.declarations if i == 0 else [],
                    references=self._extract_refs(sentence)
                )
                output_units.append(new_unit)

        return StrategyResult(
            units=output_units,
            actions_taken=actions,
            issues=issues,
            metrics={
                "input_units": len(context.units),
                "output_units": len(output_units),
                "splits_performed": len(actions)
            }
        )

    def _simple_split(self, text: str) -> list[str]:
        """Simple sentence splitting without spaCy."""
        # Split on common compound indicators
        # This is a fallback - spaCy does better

        # First, protect certain patterns
        protected = text
        protected = re.sub(r'e\.g\.', 'EG_PROTECTED', protected)
        protected = re.sub(r'i\.e\.', 'IE_PROTECTED', protected)

        # Split on sentence boundaries
        sentences = re.split(r'(?<=[.!?])\s+', protected)

        # For each sentence, also split on ' and ' if it creates valid parts
        result: list[str] = []
        for sent in sentences:
            # Check for compound structure with 'and'
            if ' and ' in sent.lower() and sent.lower().count(' and ') == 1:
                parts = re.split(r'\s+and\s+', sent, flags=re.IGNORECASE)
                # Both parts should have some substance (at least 2 words each)
                if all(len(p.split()) >= 2 for p in parts):
                    # Try to extract subject to carry forward
                    first_part = parts[0]
                    second_part = parts[1]

                    # Simple heuristic: if first part has "must/should/shall" pattern,
                    # extract subject and modal for second part
                    modal_match = re.match(
                        r'^(.+?)\s+(must|should|shall|will|can|may)\s+',
                        first_part,
                        re.IGNORECASE
                    )
                    if modal_match:
                        subject = modal_match.group(1)
                        modal = modal_match.group(2)
                        # Add subject + modal to second part if it looks like a verb phrase
                        if not re.match(r'^[A-Z]', second_part):  # Doesn't start with capital
                            second_part = f"{subject} {modal} {second_part}"

                    result.append(first_part)
                    result.append(second_part)
                    continue

            # Check for semicolon-separated clauses
            if '; ' in sent:
                clauses = sent.split('; ')
                if all(len(c.split()) >= 2 for c in clauses):
                    result.extend(clauses)
                    continue

            result.append(sent)

        # Restore protected patterns
        result = [
            s.replace('EG_PROTECTED', 'e.g.')
             .replace('IE_PROTECTED', 'i.e.')
            for s in result
        ]

        return [s for s in result if s.strip()]

    def _extract_refs(self, text: str) -> list[str]:
        """Extract references from text."""
        ref_pattern = re.compile(r'\(@\[([+=])([^\]]+)\]\)')
        return [m.group(2) for m in ref_pattern.finditer(text)]
