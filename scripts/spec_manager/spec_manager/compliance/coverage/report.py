"""Data structures for entity coverage reports.

Defines the report types used to represent the results of cross-referencing
hollowed spec entities (ENT-####) against registered atom functions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CoverageMatch:
    """A matched entity-to-atom pair.

    Attributes:
        entity_id: Entity identifier (ENT-####).
        atom_id: Atom identifier.
        match_method: How the match was found (explicit/naming/keyword).
        confidence: Confidence score (0.0-1.0).
        entity_name: Human-readable entity name.
        atom_function_name: The atom's Python function name.
    """

    entity_id: str
    atom_id: str
    match_method: str
    confidence: float
    entity_name: str
    atom_function_name: str


@dataclass
class UnmatchedEntity:
    """An entity with no corresponding atom function.

    Attributes:
        entity_id: Entity identifier (ENT-####).
        name: Human-readable entity name.
        kind: Entity kind classification.
        paragraph_ids: Paragraph IDs where the entity appears.
        lib_ids: Library IDs where the entity is referenced.
    """

    entity_id: str
    name: str
    kind: str
    paragraph_ids: list[str] = field(default_factory=list)
    lib_ids: list[str] = field(default_factory=list)


@dataclass
class UnmatchedAtom:
    """An atom function with no entity reference in any spec.

    Attributes:
        atom_id: Atom identifier.
        function_name: The Python function name.
        kind: Atom kind classification.
        vertical_slice: Which vertical slice this atom belongs to.
    """

    atom_id: str
    function_name: str
    kind: str
    vertical_slice: str | None = None


@dataclass
class EntityCoverageReport:
    """Full entity coverage report.

    Enumerates matched pairs, unmatched entities, and unmatched atoms,
    along with coverage ratios.

    Attributes:
        matched: List of entity-to-atom matches.
        unmatched_entities: Entities with no atom match.
        unmatched_atoms: Atoms with no entity match.
        entity_coverage: Ratio of matched entities to total entities.
        atom_coverage: Ratio of matched atoms to total atoms.
        total_entities: Total number of entities considered.
        total_atoms: Total number of atoms considered.
    """

    matched: list[CoverageMatch] = field(default_factory=list)
    unmatched_entities: list[UnmatchedEntity] = field(default_factory=list)
    unmatched_atoms: list[UnmatchedAtom] = field(default_factory=list)
    entity_coverage: float = 0.0
    atom_coverage: float = 0.0
    total_entities: int = 0
    total_atoms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a dictionary."""
        return {
            "matched": [
                {
                    "entity_id": m.entity_id,
                    "atom_id": m.atom_id,
                    "match_method": m.match_method,
                    "confidence": m.confidence,
                    "entity_name": m.entity_name,
                    "atom_function_name": m.atom_function_name,
                }
                for m in self.matched
            ],
            "unmatched_entities": [
                {
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "kind": e.kind,
                    "paragraph_ids": e.paragraph_ids,
                    "lib_ids": e.lib_ids,
                }
                for e in self.unmatched_entities
            ],
            "unmatched_atoms": [
                {
                    "atom_id": a.atom_id,
                    "function_name": a.function_name,
                    "kind": a.kind,
                    "vertical_slice": a.vertical_slice,
                }
                for a in self.unmatched_atoms
            ],
            "entity_coverage": self.entity_coverage,
            "atom_coverage": self.atom_coverage,
            "total_entities": self.total_entities,
            "total_atoms": self.total_atoms,
        }

    def save(self, path: Path) -> None:
        """Write the coverage report to disk as JSON.

        Args:
            path: Destination file path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
