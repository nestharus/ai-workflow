"""
Provenance tracking for spec content.

This module provides data structures and utilities for tracking where
content comes from and where it goes during spec processing.

The key insight is that we cannot verify semantic equivalence between
transformations, but we CAN track that every line is accounted for.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class UnitType(Enum):
    """Types of content units in specs - including GAP as first-class."""

    ALGORITHM = "algorithm"           # Algorithm #
    CLAIM = "claim"                   # C#, P#C#
    DATA_STRUCTURE = "data_structure"  # D#
    INVARIANT = "invariant"           # I#, P#I#
    GOAL = "goal"                     # G# (legacy, maps to invariant)
    PROOF = "proof"                   # Proof sketch
    LEAN = "lean"                     # Lean skeleton
    PROSE = "prose"                   # Explanatory text
    MATH = "math"                     # Mathematical content (P#.#)
    PSEUDOCODE = "pseudocode"         # ```pseudo blocks
    GAP = "gap"                       # FIRST-CLASS GAP ELEMENT
    PATCH = "patch"                   # Patch content (P#C# or P#I#)
    UNKNOWN = "unknown"


class GranularityLevel(Enum):
    """
    Membership granularity levels - finer = more tracking, lower loss risk.

    The cleaning/decomposition phase explicitly chooses granularity
    based on input messiness.
    """
    LINE = 1        # Dirty prose, maximum tracking
    SENTENCE = 2    # Semi-structured content
    CLAUSE = 3      # Complex compound statements
    SECTION = 4     # Clean, annotated content
    PARAGRAPH = 5   # Paragraph-level
    FILE = 6        # Entire file


class UnitStatus(Enum):
    """Status of a tracked unit during processing."""

    PENDING = "pending"      # Not yet processed
    MAPPED = "mapped"        # Successfully mapped to target
    DROPPED = "dropped"      # Intentionally dropped (explanatory)
    MERGED = "merged"        # Merged with another unit
    CONFLICT = "conflict"    # Conflicts with another unit
    PROCESSED = "processed"  # Successfully processed
    REJECTED = "rejected"    # Rejected (conflict, invalid, etc.)
    REMAINDER = "remainder"  # Leftover after extraction


@dataclass
class SourceLocation:
    """A location in a source file."""

    file: str
    line_start: int
    line_end: int
    column_start: int | None = None
    column_end: int | None = None
    patch_id: str | None = None  # e.g., "p1", "p5"

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line_start}"
        if self.line_end != self.line_start:
            loc += f"-{self.line_end}"
        if self.patch_id:
            loc = f"[{self.patch_id}] {loc}"
        return loc


@dataclass
class TargetLocation:
    """A location in a target file."""

    file: str
    line_start: int
    line_end: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line_start}-{self.line_end}"


@dataclass
class MembershipEvidence:
    """Evidence for a membership mapping (many-to-many)."""
    rationale: str                   # Why this mapping was made
    confidence: float                # 0.0-1.0 confidence
    method: str                      # "exact", "llm_inference", "similarity", etc.


@dataclass
class TrackedUnit:
    """
    An atomic unit of content with full provenance.

    This is the core data structure for tracking content through
    transformations. Every piece of meaningful content becomes a
    TrackedUnit so we can verify nothing is lost.

    The provenance chain allows us to trace:
    - Where did this content originate?
    - Which patches modified it?
    - Where did it end up?
    - Why was it dropped (if dropped)?

    MANY-TO-MANY MEMBERSHIP:
    With prose fragments scattered across sources, mapping is often
    "many source atoms -> one structured element" or vice versa.
    - source_atom_ids: IDs of source atoms that contributed to this unit
    - target_element_ids: IDs of elements this unit contributed to
    - membership_evidence: Evidence/rationale for each mapping
    """

    # Identity
    id: str                          # Unique identifier (may be annotation ID)
    content: str                     # The actual text content
    unit_type: UnitType              # What kind of content this is

    # Provenance - where it came from
    source: SourceLocation           # Original location
    introduced_by: str               # Patch that introduced this (e.g., "p1")
    modified_by: list[str] = field(default_factory=list)  # Patches that modified

    # Annotations found in this unit
    declarations: list[str] = field(default_factory=list)  # ([=ID])
    references: list[str] = field(default_factory=list)    # (@[+ID]), (@[=ID])
    annotations: list[str] = field(default_factory=list)   # All annotations as strings

    # Many-to-many membership tracking
    source_atom_ids: list[str] = field(default_factory=list)  # Source atoms -> this
    target_element_ids: list[str] = field(default_factory=list)  # This -> target elements
    membership_evidence: dict[str, MembershipEvidence] = field(default_factory=dict)  # target_id -> evidence

    # Explicit lineage edges (Gap 12)
    # With heavy rewriting, decomposition, and recomposition, we need explicit lineage
    # edges to reconstruct "what became what" - beyond just a string in drop_reason.
    parents: list[str] = field(default_factory=list)    # Unit IDs this was created from
    children: list[str] = field(default_factory=list)   # Unit IDs created from this

    # Processing state
    status: UnitStatus = UnitStatus.PENDING
    target: TargetLocation | None = None  # Where it ended up (single target, backward compat)
    drop_reason: str | None = None        # If dropped, why

    # Library discovery (Phase C will populate these)
    candidate_libraries: dict[str, float] = field(default_factory=dict)
    primary_library: str | None = None
    relation_libraries: list[str] = field(default_factory=list)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def derive(
        self,
        new_content: str,
        new_id: str | None = None,
        modifier: str | None = None
    ) -> TrackedUnit:
        """Create a derived unit preserving provenance."""
        modified_by = self.modified_by.copy()
        if modifier:
            modified_by.append(modifier)

        return TrackedUnit(
            id=new_id or self.id,
            content=new_content,
            unit_type=self.unit_type,
            source=self.source,
            introduced_by=self.introduced_by,
            modified_by=modified_by,
            declarations=self.declarations.copy(),
            references=self.references.copy(),
            annotations=self.annotations.copy(),
            status=self.status,
            metadata=self.metadata.copy()
        )

    def add_membership(
        self,
        target_id: str,
        rationale: str,
        confidence: float = 1.0,
        method: str = "exact"
    ) -> None:
        """Add a membership mapping with evidence."""
        if target_id not in self.target_element_ids:
            self.target_element_ids.append(target_id)
        self.membership_evidence[target_id] = MembershipEvidence(
            rationale=rationale,
            confidence=confidence,
            method=method
        )
        self.updated_at = datetime.now()

    def get_handled_by(self) -> list[tuple[str, MembershipEvidence | None]]:
        """Get all targets this unit contributed to, with evidence."""
        return [
            (tid, self.membership_evidence.get(tid))
            for tid in self.target_element_ids
        ]

    def mark_mapped(self, target: TargetLocation) -> None:
        """Mark this unit as successfully mapped to a target."""
        self.status = UnitStatus.MAPPED
        self.target = target
        self.updated_at = datetime.now()

    def mark_dropped(self, reason: str) -> None:
        """Mark this unit as intentionally dropped."""
        self.status = UnitStatus.DROPPED
        self.drop_reason = reason
        self.updated_at = datetime.now()

    def mark_merged(self, into_unit_id: str) -> None:
        """Mark this unit as merged into another."""
        self.status = UnitStatus.MERGED
        self.drop_reason = f"Merged into {into_unit_id}"
        self.updated_at = datetime.now()

    def add_modification(self, patch_id: str) -> None:
        """Record that a patch modified this unit."""
        if patch_id not in self.modified_by:
            self.modified_by.append(patch_id)
        self.updated_at = datetime.now()

    # =========================================================================
    # Explicit Lineage Methods (Gap 12)
    # =========================================================================

    def add_parent(self, parent_id: str) -> None:
        """Record that this unit was created from a parent unit."""
        if parent_id not in self.parents:
            self.parents.append(parent_id)
        self.updated_at = datetime.now()

    def add_child(self, child_id: str) -> None:
        """Record that this unit was split/transformed into a child unit."""
        if child_id not in self.children:
            self.children.append(child_id)
        self.updated_at = datetime.now()

    def get_lineage_chain(self) -> list[str]:
        """Get the full lineage chain (parents of parents)."""
        chain = []
        visited: set[str] = set()
        queue = list(self.parents)

        while queue:
            parent_id = queue.pop(0)
            if parent_id in visited:
                continue
            visited.add(parent_id)
            chain.append(parent_id)
            # Note: Full implementation would look up parent unit and add its parents

        return chain

    def set_lineage_from(
        self,
        parent_units: list["TrackedUnit"],
        transformation: str = "transform"
    ) -> None:
        """
        Set lineage from multiple parent units (e.g., after LLM inference).

        Args:
            parent_units: Units this was created from
            transformation: Description of the transformation
        """
        for parent in parent_units:
            self.add_parent(parent.id)
            parent.add_child(self.id)
        self.updated_at = datetime.now()


@dataclass
class LineageEdge:
    """An edge in the lineage graph."""
    from_unit: str
    to_unit: str
    transformation: str        # "split", "merge", "infer", "transform"
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)


class LineageTable:
    """
    Separate lineage table for workspace state (Gap 12).

    This provides a global view of all lineage edges, making it easy to:
    - Trace what became what
    - Reconstruct transformation history
    - Debug information loss
    """

    def __init__(self) -> None:
        self.edges: list[LineageEdge] = []
        self._by_from: dict[str, list[LineageEdge]] = defaultdict(list)
        self._by_to: dict[str, list[LineageEdge]] = defaultdict(list)

    def add_edge(
        self,
        from_unit: str,
        to_unit: str,
        transformation: str,
        details: dict[str, Any] | None = None
    ) -> None:
        """Record a lineage edge."""
        edge = LineageEdge(
            from_unit=from_unit,
            to_unit=to_unit,
            transformation=transformation,
            timestamp=datetime.now(),
            details=details or {}
        )
        self.edges.append(edge)
        self._by_from[from_unit].append(edge)
        self._by_to[to_unit].append(edge)

    def get_ancestors(self, unit_id: str) -> list[str]:
        """Get all ancestors of a unit (transitive)."""
        ancestors = []
        visited: set[str] = set()
        queue = [e.from_unit for e in self._by_to.get(unit_id, [])]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            ancestors.append(current)
            queue.extend(e.from_unit for e in self._by_to.get(current, []))

        return ancestors

    def get_descendants(self, unit_id: str) -> list[str]:
        """Get all descendants of a unit (transitive)."""
        descendants = []
        visited: set[str] = set()
        queue = [e.to_unit for e in self._by_from.get(unit_id, [])]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            descendants.append(current)
            queue.extend(e.to_unit for e in self._by_from.get(current, []))

        return descendants

    def trace_transformation(
        self,
        from_unit: str,
        to_unit: str
    ) -> list[LineageEdge] | None:
        """Find the path of transformations from one unit to another."""
        # BFS to find path
        visited: set[str] = set()
        queue: list[tuple[str, list[LineageEdge]]] = [(from_unit, [])]

        while queue:
            current, path = queue.pop(0)
            if current == to_unit:
                return path
            if current in visited:
                continue
            visited.add(current)

            for edge in self._by_from.get(current, []):
                queue.append((edge.to_unit, path + [edge]))

        return None

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize for storage."""
        return [
            {
                'from': e.from_unit,
                'to': e.to_unit,
                'transformation': e.transformation,
                'timestamp': e.timestamp.isoformat(),
                'details': e.details
            }
            for e in self.edges
        ]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "LineageTable":
        """Deserialize from storage."""
        table = cls()
        for item in data:
            table.add_edge(
                from_unit=item['from'],
                to_unit=item['to'],
                transformation=item['transformation'],
                details=item.get('details', {})
            )
        return table


class ProvenanceTracker:
    """
    Tracks provenance of all content units during processing.

    This class is the main interface for provenance tracking. It:
    - Extracts units from source files
    - Tracks where each unit goes
    - Verifies nothing is unaccounted for
    - Reports gaps (untracked content)
    """

    def __init__(self) -> None:
        self.units: dict[str, TrackedUnit] = {}
        self.transformations: list[dict[str, Any]] = []
        self._next_id = 1

    def extract_units_from_file(
        self,
        content: str,
        file_path: str,
        patch_id: str | None = None
    ) -> list[TrackedUnit]:
        """
        Extract trackable units from a file.

        This identifies:
        - Sections with ([=ID]) declarations (annotated format)
        - Markdown headers like ## Algorithm N (standard format)
        - Prose blocks between sections
        - Code blocks (pseudo, lean, etc.)

        Each becomes a TrackedUnit with provenance.
        """
        units = []
        lines = content.splitlines()

        # Pattern for explicit annotation declarations
        declaration_pattern = re.compile(r'\(\[=([^\]]+)\]\)')

        # Patterns for markdown headers that indicate new units
        # Matches: ## Algorithm 1, ### Algorithm 10: Title, ## Data Structure D1, etc.
        header_patterns = [
            re.compile(r'^#{1,4}\s*Algorithm\s+(\d+)(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Data\s+Structure\s+(D?\d+)(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Claim\s+(C?\d+)(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Invariant\s+(I?\d+)(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Goal\s+(G?\d+)(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Proof\s+(P?\d+)?(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
            re.compile(r'^#{1,4}\s*Lean\s+(L?\d+)?(?:\s*[:\-—]\s*.*)?$', re.IGNORECASE),
        ]

        current_unit_lines: list[str] = []
        current_unit_start = 1
        current_declarations: list[str] = []

        def check_header_declaration(line: str) -> str | None:
            """Check if line is a markdown header that declares a unit."""
            for pattern in header_patterns:
                match = pattern.match(line.strip())
                if match:
                    # Extract the ID type from the pattern
                    if 'Algorithm' in pattern.pattern:
                        return f"Algorithm {match.group(1)}"
                    elif 'Data' in pattern.pattern:
                        num = match.group(1)
                        return f"D{num}" if not num.startswith('D') else num
                    elif 'Claim' in pattern.pattern:
                        num = match.group(1)
                        return f"C{num}" if not num.startswith('C') else num
                    elif 'Invariant' in pattern.pattern:
                        num = match.group(1)
                        return f"I{num}" if not num.startswith('I') else num
                    elif 'Goal' in pattern.pattern:
                        num = match.group(1)
                        return f"G{num}" if not num.startswith('G') else num
                    elif 'Proof' in pattern.pattern:
                        num = match.group(1) or ""
                        return f"Proof {num}".strip()
                    elif 'Lean' in pattern.pattern:
                        num = match.group(1) or ""
                        return f"Lean {num}".strip()
            return None

        for line_num, line in enumerate(lines, start=1):
            # Check for explicit annotation declaration
            decl_match = declaration_pattern.search(line)

            # Check for markdown header declaration
            header_decl = check_header_declaration(line) if not decl_match else None

            # Determine if we should start a new unit
            new_unit_decl = None
            if decl_match:
                new_unit_decl = decl_match.group(1)
            elif header_decl:
                new_unit_decl = header_decl

            if new_unit_decl and current_unit_lines:
                # Save previous unit
                unit = self._create_unit(
                    lines=current_unit_lines,
                    file_path=file_path,
                    line_start=current_unit_start,
                    line_end=line_num - 1,
                    patch_id=patch_id,
                    declarations=current_declarations
                )
                units.append(unit)
                self.units[unit.id] = unit

                # Start new unit
                current_unit_lines = [line]
                current_unit_start = line_num
                current_declarations = [new_unit_decl]
            else:
                current_unit_lines.append(line)
                if decl_match:
                    current_declarations.append(decl_match.group(1))
                elif header_decl and not current_declarations:
                    # First line is a header declaration
                    current_declarations = [header_decl]

        # Don't forget last unit
        if current_unit_lines:
            unit = self._create_unit(
                lines=current_unit_lines,
                file_path=file_path,
                line_start=current_unit_start,
                line_end=len(lines),
                patch_id=patch_id,
                declarations=current_declarations
            )
            units.append(unit)
            self.units[unit.id] = unit

        return units

    def _create_unit(
        self,
        lines: list[str],
        file_path: str,
        line_start: int,
        line_end: int,
        patch_id: str | None,
        declarations: list[str]
    ) -> TrackedUnit:
        """Create a TrackedUnit from extracted lines."""
        content = '\n'.join(lines)

        # Determine unit type from content
        unit_type = self._infer_unit_type(content, declarations)

        # Use declaration as ID if available, otherwise generate
        if declarations:
            unit_id = declarations[0]
        else:
            unit_id = f"_unit_{self._next_id}"
            self._next_id += 1

        # Extract references
        ref_pattern = re.compile(r'\(@\[([+=])([^\]]+)\]\)')
        references = [m.group(2) for m in ref_pattern.finditer(content)]

        return TrackedUnit(
            id=unit_id,
            content=content,
            unit_type=unit_type,
            source=SourceLocation(
                file=file_path,
                line_start=line_start,
                line_end=line_end,
                patch_id=patch_id
            ),
            introduced_by=patch_id or "unknown",
            declarations=declarations,
            references=references
        )

    def _infer_unit_type(self, content: str, declarations: list[str]) -> UnitType:
        """Infer the type of content from its structure."""
        # Check declarations first
        for decl in declarations:
            if decl.startswith("Algorithm "):
                return UnitType.ALGORITHM
            if re.match(r'^P?\d*C\d+$', decl):
                return UnitType.CLAIM
            if re.match(r'^D\d+$', decl):
                return UnitType.DATA_STRUCTURE
            if re.match(r'^P?\d*I\d+$', decl) or re.match(r'^I\d+$', decl):
                return UnitType.INVARIANT
            if re.match(r'^G\d+$', decl):
                return UnitType.GOAL
            if decl.startswith("Lean"):
                return UnitType.LEAN
            if decl.startswith("Proof"):
                return UnitType.PROOF

        # Check content patterns
        if '```pseudo' in content:
            return UnitType.PSEUDOCODE
        if '```lean' in content:
            return UnitType.LEAN
        if re.search(r'\\[.*?\\]', content) or '$$' in content:
            return UnitType.MATH

        return UnitType.PROSE

    def record_mapping(self, unit_id: str, target: TargetLocation) -> None:
        """Record that a unit was mapped to a target location."""
        if unit_id in self.units:
            self.units[unit_id].mark_mapped(target)

    def record_drop(self, unit_id: str, reason: str) -> None:
        """Record that a unit was intentionally dropped."""
        if unit_id in self.units:
            self.units[unit_id].mark_dropped(reason)

    def record_transformation(
        self,
        source_ids: list[str],
        target_ids: list[str],
        strategy: str,
        description: str
    ) -> None:
        """Record a transformation for audit trail."""
        self.transformations.append({
            "source_ids": source_ids,
            "target_ids": target_ids,
            "strategy": strategy,
            "description": description
        })

    def get_unaccounted(self) -> list[TrackedUnit]:
        """Get all units that haven't been mapped or dropped."""
        return [
            u for u in self.units.values()
            if u.status == UnitStatus.PENDING
        ]

    def get_lineage(self, unit_id: str) -> list[str]:
        """Get the modification history for a unit."""
        if unit_id not in self.units:
            return []

        unit = self.units[unit_id]
        return [unit.introduced_by] + unit.modified_by

    def get_coverage_report(self) -> dict[str, Any]:
        """Generate a coverage report."""
        total = len(self.units)
        mapped = sum(1 for u in self.units.values() if u.status == UnitStatus.MAPPED)
        dropped = sum(1 for u in self.units.values() if u.status == UnitStatus.DROPPED)
        merged = sum(1 for u in self.units.values() if u.status == UnitStatus.MERGED)
        pending = sum(1 for u in self.units.values() if u.status == UnitStatus.PENDING)

        return {
            "total_units": total,
            "mapped": mapped,
            "dropped": dropped,
            "merged": merged,
            "unaccounted": pending,
            "coverage_percent": (mapped + dropped + merged) / total * 100 if total > 0 else 100
        }

    def generate_report(self) -> str:
        """Generate a provenance report."""
        lines = [
            "# Provenance Report",
            "",
            f"## Units Tracked: {len(self.units)}",
            ""
        ]

        # Group by type
        by_type: dict[UnitType, list[TrackedUnit]] = {}
        for unit in self.units.values():
            by_type.setdefault(unit.unit_type, []).append(unit)

        for unit_type, type_units in sorted(by_type.items(), key=lambda x: x[0].value):
            lines.append(f"### {unit_type.value}: {len(type_units)}")
            for unit in type_units[:5]:  # Show first 5
                lines.append(f"- {unit.id}: {unit.source}")
            if len(type_units) > 5:
                lines.append(f"- ... and {len(type_units) - 5} more")
            lines.append("")

        lines.append(f"## Transformations: {len(self.transformations)}")
        lines.append("")
        for t in self.transformations[-10:]:  # Last 10
            lines.append(f"- [{t['strategy']}] {t['description']}")
        if len(self.transformations) > 10:
            lines.append(f"- ... and {len(self.transformations) - 10} more")

        return "\n".join(lines)


def parse_stamp(text: str) -> dict[str, str | list[str]] | None:
    """
    Parse a provenance stamp from text.

    Stamps look like: <!-- @from:p1 @modified:p5,p7 @line:234 -->

    Returns dict with parsed values or None if no stamp found.
    """
    stamp_pattern = re.compile(
        r'<!--\s*'
        r'(?:@from:(\w+)\s*)?'
        r'(?:@modified:([\w,]+)\s*)?'
        r'(?:@line:(\d+)\s*)?'
        r'-->'
    )

    match = stamp_pattern.search(text)
    if not match:
        return None

    result: dict[str, str | list[str]] = {}
    if match.group(1):
        result['from'] = match.group(1)
    if match.group(2):
        result['modified'] = match.group(2).split(',')
    if match.group(3):
        result['line'] = match.group(3)

    return result if result else None


def generate_stamp(
    introduced_by: str,
    modified_by: list[str] | None = None,
    source_line: int | None = None
) -> str:
    """
    Generate a provenance stamp.

    Returns: <!-- @from:p1 @modified:p5,p7 @line:234 -->
    """
    parts = [f"@from:{introduced_by}"]

    if modified_by:
        parts.append(f"@modified:{','.join(modified_by)}")

    if source_line:
        parts.append(f"@line:{source_line}")

    return f"<!-- {' '.join(parts)} -->"
