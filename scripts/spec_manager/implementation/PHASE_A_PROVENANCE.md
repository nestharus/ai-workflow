# Phase A: Provenance and Intermediate File Tracking

## Overview

This phase adds the foundation for tracking where content comes from and ensuring nothing is lost during transformations. This is critical because:

1. **Inputs are messy** - patches reference other patches vaguely
2. **Transformations are lossy** - prose → structure can lose meaning
3. **We need accountability** - must know what came from where

## The Core Problem

When processing spec patches:
- p5 might say "patch the relaxation algorithm" but which one?
- Content flows: patches → plan.md → libraries
- At each step, content can be lost, merged, or transformed
- Without tracking, we can't verify nothing was dropped

## The Solution: Provenance Stamps

During processing, every piece of content gets stamped with:
- **Where it came from** (source file, line numbers)
- **When it was introduced** (which patch)
- **How it was modified** (subsequent patches)
- **Where it went** (target file, line numbers)

**Critical**: These stamps are TEMPORARY. They exist only during the current ingest operation. Once ingest is complete, stamps are discarded and libraries become authoritative. The next ingest starts fresh.

## Implementation

### File 1: `spec_manager/core/provenance.py`

```python
"""
Provenance tracking for spec content.

This module provides data structures and utilities for tracking where
content comes from and where it goes during spec processing.

The key insight is that we cannot verify semantic equivalence between
transformations, but we CAN track that every line is accounted for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal


class UnitType(Enum):
    """Types of content units in specs - including GAP as first-class."""

    ALGORITHM = "algorithm"        # Algorithm #
    CLAIM = "claim"                # C#, P#C#
    DATA_STRUCTURE = "data_structure"  # D#
    INVARIANT = "invariant"        # I#, P#I#
    GOAL = "goal"                  # G# (legacy, maps to invariant)
    PROOF = "proof"                # Proof sketch
    LEAN = "lean"                  # Lean skeleton
    PROSE = "prose"                # Explanatory text
    MATH = "math"                  # Mathematical content (P#.#)
    PSEUDOCODE = "pseudocode"      # ```pseudo blocks
    GAP = "gap"                    # ← FIRST-CLASS GAP ELEMENT
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


class UnitStatus(Enum):
    """Status of a tracked unit during processing."""

    PENDING = "pending"      # Not yet processed
    MAPPED = "mapped"        # Successfully mapped to target
    DROPPED = "dropped"      # Intentionally dropped (explanatory)
    MERGED = "merged"        # Merged with another unit
    CONFLICT = "conflict"    # Conflicts with another unit


@dataclass
class SourceLocation:
    """A location in a source file."""

    file: str
    line_start: int
    line_end: int
    patch_id: str | None = None  # e.g., "p1", "p5"

    def __str__(self) -> str:
        if self.patch_id:
            return f"{self.patch_id}:{self.line_start}-{self.line_end}"
        return f"{self.file}:{self.line_start}-{self.line_end}"


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
    "many source atoms → one structured element" or vice versa.
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

    # Many-to-many membership tracking
    source_atom_ids: list[str] = field(default_factory=list)  # Source atoms → this
    target_element_ids: list[str] = field(default_factory=list)  # This → target elements
    membership_evidence: dict[str, MembershipEvidence] = field(default_factory=dict)  # target_id → evidence

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
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

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

    def get_handled_by(self) -> list[tuple[str, MembershipEvidence]]:
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
        visited = set()
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

    def __init__(self):
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
        visited = set()
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
        visited = set()
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
        visited = set()
        queue = [(from_unit, [])]

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

    def to_dict(self) -> list[dict]:
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
    def from_dict(cls, data: list[dict]) -> "LineageTable":
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

    def __init__(self):
        self.units: dict[str, TrackedUnit] = {}
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
        - Sections with ([=ID]) declarations
        - Prose blocks between sections
        - Code blocks (pseudo, lean, etc.)

        Each becomes a TrackedUnit with provenance.
        """
        units = []
        lines = content.splitlines()

        # Pattern for section declarations
        declaration_pattern = re.compile(r'\(\[=([^\]]+)\]\)')

        current_unit_lines: list[str] = []
        current_unit_start = 1
        current_declarations: list[str] = []

        for line_num, line in enumerate(lines, start=1):
            # Check for declaration
            decl_match = declaration_pattern.search(line)

            if decl_match and current_unit_lines:
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
                current_declarations = [decl_match.group(1)]
            else:
                current_unit_lines.append(line)
                if decl_match:
                    current_declarations.append(decl_match.group(1))

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

    def get_unaccounted(self) -> list[TrackedUnit]:
        """Get all units that haven't been mapped or dropped."""
        return [
            u for u in self.units.values()
            if u.status == UnitStatus.PENDING
        ]

    def get_coverage_report(self) -> dict:
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

    result = {}
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
```

### File 2: `spec_manager/core/intermediate.py`

```python
"""
Intermediate state management for spec processing.

This module handles saving and loading processing state between passes.
The key principle is that we keep ALL intermediate states so we can:
1. Verify nothing was lost between steps
2. Debug issues by examining any point in processing
3. Roll back if needed

Intermediate files are stored in .workspace/intermediates/
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .provenance import TrackedUnit, UnitStatus, UnitType, SourceLocation


@dataclass
class FileSnapshot:
    """Snapshot of a file's state."""

    path: str
    content_hash: str
    line_count: int
    unit_count: int  # Number of tracked units from this file


@dataclass
class IntermediateState:
    """
    Snapshot of processing state at a point in time.

    This captures everything needed to:
    - Understand what processing has been done
    - Verify nothing was lost
    - Continue from this point
    - Compare with other states

    CRITICAL: Stores FULL content (not just previews/hashes) so that
    line-by-line membership checks can be performed between states.
    This enables "diff lines with lines" verification.
    """

    # Identity
    version: int                     # Increments each pass
    phase: str                       # cleaning, discovery, review, finalize
    timestamp: datetime = field(default_factory=datetime.now)

    # Description of what this state represents
    description: str = ""

    # All tracked units at this state - FULL CONTENT, not previews
    units: dict[str, dict] = field(default_factory=dict)  # Serialized TrackedUnits

    # Units that haven't been placed yet
    remainder_ids: list[str] = field(default_factory=list)

    # File states
    file_snapshots: dict[str, FileSnapshot] = field(default_factory=dict)

    # Reconstructed intermediate markdown for diffing (FULL content)
    intermediate_files: dict[str, str] = field(default_factory=dict)

    # Membership tracking for verification
    atom_mapping: dict[str, str] = field(default_factory=dict)  # atom_id → target_location

    # Library discovery state (Phase C)
    candidate_libraries: list[str] = field(default_factory=list)
    library_shapes: dict[str, dict] = field(default_factory=dict)

    # Processing metrics
    metrics: dict[str, Any] = field(default_factory=dict)


class IntermediateManager:
    """
    Manages intermediate states during processing.

    Usage:
        manager = IntermediateManager(workspace_path)

        # After each processing pass
        state = manager.create_snapshot(
            phase="cleaning",
            description="Pass 1: Basic normalization",
            tracker=provenance_tracker
        )
        manager.save(state)

        # Compare states
        diff = manager.compare(state_v1, state_v2)

        # Load previous state
        old_state = manager.load(version=3)
    """

    def __init__(self, workspace_path: Path):
        self.workspace_path = workspace_path
        self.intermediates_dir = workspace_path / "intermediates"
        self.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        phase: str,
        description: str,
        tracker: "ProvenanceTracker",
        candidate_libraries: list[str] | None = None,
        library_shapes: dict | None = None,
        # Gap 4 fix: Accept additional snapshot data
        intermediate_files: dict[str, str] | None = None,
        atom_mapping: dict[str, str] | None = None
    ) -> IntermediateState:
        """
        Create a snapshot of current processing state.

        Gap 4 fix: Snapshots now ACTUALLY PERSIST:
        1. file_snapshots - state of processed files
        2. intermediate_files - reconstructed markdown for each pass
        3. atom_mapping - atom_id → target_location mapping

        These are REQUIRED for the "trace" workflow to replay mapping
        using stored intermediate states.
        """
        # Get next version number
        existing = list(self.intermediates_dir.glob("state_*.json"))
        version = len(existing) + 1

        # Serialize units
        units = {}
        for uid, unit in tracker.units.items():
            units[uid] = self._serialize_unit(unit)

        # Get remainders
        remainder_ids = [u.id for u in tracker.get_unaccounted()]

        # Compute metrics
        report = tracker.get_coverage_report()

        # Gap 4 fix: Build file_snapshots from tracker state
        file_snapshots = {}
        seen_files = set()
        for unit in tracker.units.values():
            if unit.source.file and unit.source.file not in seen_files:
                seen_files.add(unit.source.file)
                # Create FileSnapshot for this source file
                file_snapshots[unit.source.file] = FileSnapshot(
                    path=unit.source.file,
                    content_hash=hashlib.md5(unit.content.encode()).hexdigest(),
                    line_count=unit.source.line_end - unit.source.line_start + 1,
                    unit_count=sum(1 for u in tracker.units.values() if u.source.file == unit.source.file)
                )

        # Gap 4 fix: Build atom_mapping from tracker state if not provided
        computed_atom_mapping = atom_mapping or {}
        if not computed_atom_mapping:
            for uid, unit in tracker.units.items():
                if unit.target:
                    # Map source atoms to target locations
                    for i, line in enumerate(unit.content.split('\n')):
                        if line.strip():
                            atom_id = f"{uid}_L{i+1}_{hash(line) % 10000:04d}"
                            target_loc = f"{unit.target.file}:{unit.target.line_start + i}"
                            computed_atom_mapping[atom_id] = target_loc

        # Gap 4 fix: Build intermediate_files if not provided
        computed_intermediate_files = intermediate_files or {}
        if not computed_intermediate_files:
            # Reconstruct per-library intermediate markdown
            by_library: dict[str, list] = {}
            for uid, unit in tracker.units.items():
                lib = unit.primary_library or "unassigned"
                if lib not in by_library:
                    by_library[lib] = []
                by_library[lib].append(unit.content)

            for lib_name, contents in by_library.items():
                computed_intermediate_files[f"{lib_name}.md"] = '\n\n'.join(contents)

        return IntermediateState(
            version=version,
            phase=phase,
            description=description,
            units=units,
            remainder_ids=remainder_ids,
            # Gap 4 fix: Populate the fields that were previously empty
            file_snapshots=file_snapshots,
            intermediate_files=computed_intermediate_files,
            atom_mapping=computed_atom_mapping,
            candidate_libraries=candidate_libraries or [],
            library_shapes=library_shapes or {},
            metrics={
                "total_units": report["total_units"],
                "mapped": report["mapped"],
                "dropped": report["dropped"],
                "unaccounted": report["unaccounted"],
                "coverage_percent": report["coverage_percent"]
            }
        )

    def _serialize_unit(self, unit: TrackedUnit) -> dict:
        """
        Serialize a TrackedUnit to dict.

        CRITICAL: Store FULL content (not just preview/hash) so that
        line-by-line membership checks can be performed between states.
        This enables "diff lines with lines" verification.
        """
        return {
            "id": unit.id,
            "content": unit.content,  # ← FULL content, not preview
            "content_hash": hashlib.md5(unit.content.encode()).hexdigest(),
            "unit_type": unit.unit_type.value,
            "source": {
                "file": unit.source.file,
                "line_start": unit.source.line_start,
                "line_end": unit.source.line_end,
                "patch_id": unit.source.patch_id
            },
            "introduced_by": unit.introduced_by,
            "modified_by": unit.modified_by,
            "declarations": unit.declarations,
            "references": unit.references,
            "status": unit.status.value,
            "target": {
                "file": unit.target.file,
                "line_start": unit.target.line_start,
                "line_end": unit.target.line_end
            } if unit.target else None,
            "drop_reason": unit.drop_reason,
            "primary_library": unit.primary_library,
            "candidate_libraries": unit.candidate_libraries,
            "relation_libraries": unit.relation_libraries
        }

    def save(self, state: IntermediateState) -> Path:
        """
        Save intermediate state to file.

        Gap 4 fix: Now serializes file_snapshots, intermediate_files, and atom_mapping
        so that the "trace" workflow can replay mapping using stored states.
        """
        filename = f"state_{state.version:04d}_{state.phase}.json"
        filepath = self.intermediates_dir / filename

        # Gap 4 fix: Serialize FileSnapshot objects to dicts
        serialized_file_snapshots = {}
        for path, snapshot in state.file_snapshots.items():
            serialized_file_snapshots[path] = {
                "path": snapshot.path,
                "content_hash": snapshot.content_hash,
                "line_count": snapshot.line_count,
                "unit_count": snapshot.unit_count
            }

        data = {
            "version": state.version,
            "phase": state.phase,
            "timestamp": state.timestamp.isoformat(),
            "description": state.description,
            "units": state.units,
            "remainder_ids": state.remainder_ids,
            "candidate_libraries": state.candidate_libraries,
            "library_shapes": state.library_shapes,
            "metrics": state.metrics,
            # Gap 4 fix: Persist the fields that were previously missing
            "file_snapshots": serialized_file_snapshots,
            "intermediate_files": state.intermediate_files,
            "atom_mapping": state.atom_mapping
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        # Gap 4 fix: Also persist intermediate files to disk for easy access
        intermediates_content_dir = self.intermediates_dir / f"v{state.version:04d}"
        intermediates_content_dir.mkdir(exist_ok=True)
        for filename_key, content in state.intermediate_files.items():
            intermediate_path = intermediates_content_dir / filename_key
            intermediate_path.write_text(content, encoding='utf-8')

        return filepath

    def load(self, version: int) -> IntermediateState | None:
        """
        Load intermediate state by version number.

        Gap 4 fix: Now deserializes file_snapshots, intermediate_files, and atom_mapping.
        """
        pattern = f"state_{version:04d}_*.json"
        matches = list(self.intermediates_dir.glob(pattern))

        if not matches:
            return None

        with open(matches[0], 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Gap 4 fix: Deserialize FileSnapshot objects
        file_snapshots = {}
        for path, snapshot_data in data.get("file_snapshots", {}).items():
            file_snapshots[path] = FileSnapshot(
                path=snapshot_data["path"],
                content_hash=snapshot_data["content_hash"],
                line_count=snapshot_data["line_count"],
                unit_count=snapshot_data["unit_count"]
            )

        return IntermediateState(
            version=data["version"],
            phase=data["phase"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            description=data["description"],
            units=data["units"],
            remainder_ids=data["remainder_ids"],
            candidate_libraries=data.get("candidate_libraries", []),
            library_shapes=data.get("library_shapes", {}),
            metrics=data.get("metrics", {}),
            # Gap 4 fix: Load the previously missing fields
            file_snapshots=file_snapshots,
            intermediate_files=data.get("intermediate_files", {}),
            atom_mapping=data.get("atom_mapping", {})
        )

    def load_latest(self) -> IntermediateState | None:
        """
        Load the most recent intermediate state.

        Gap 4 fix: Now deserializes file_snapshots, intermediate_files, and atom_mapping.
        """
        existing = sorted(self.intermediates_dir.glob("state_*.json"))
        if not existing:
            return None

        with open(existing[-1], 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Gap 4 fix: Deserialize FileSnapshot objects
        file_snapshots = {}
        for path, snapshot_data in data.get("file_snapshots", {}).items():
            file_snapshots[path] = FileSnapshot(
                path=snapshot_data["path"],
                content_hash=snapshot_data["content_hash"],
                line_count=snapshot_data["line_count"],
                unit_count=snapshot_data["unit_count"]
            )

        return IntermediateState(
            version=data["version"],
            phase=data["phase"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            description=data["description"],
            units=data["units"],
            remainder_ids=data["remainder_ids"],
            candidate_libraries=data.get("candidate_libraries", []),
            library_shapes=data.get("library_shapes", {}),
            metrics=data.get("metrics", {}),
            # Gap 4 fix: Load the previously missing fields
            file_snapshots=file_snapshots,
            intermediate_files=data.get("intermediate_files", {}),
            atom_mapping=data.get("atom_mapping", {})
        )

    def compare(
        self,
        state1: IntermediateState,
        state2: IntermediateState
    ) -> dict:
        """
        Compare two intermediate states.

        Returns details about what changed between states:
        - Units added
        - Units removed
        - Units whose status changed
        - Coverage change
        """
        units1 = set(state1.units.keys())
        units2 = set(state2.units.keys())

        added = units2 - units1
        removed = units1 - units2
        common = units1 & units2

        # Check for status changes
        status_changes = []
        for uid in common:
            s1 = state1.units[uid].get("status")
            s2 = state2.units[uid].get("status")
            if s1 != s2:
                status_changes.append({
                    "unit": uid,
                    "from": s1,
                    "to": s2
                })

        return {
            "from_version": state1.version,
            "to_version": state2.version,
            "units_added": list(added),
            "units_removed": list(removed),
            "status_changes": status_changes,
            "coverage_change": {
                "from": state1.metrics.get("coverage_percent", 0),
                "to": state2.metrics.get("coverage_percent", 0)
            },
            "remainder_change": {
                "from": len(state1.remainder_ids),
                "to": len(state2.remainder_ids)
            }
        }

    def list_states(self) -> list[dict]:
        """List all intermediate states with summary info."""
        states = []
        for filepath in sorted(self.intermediates_dir.glob("state_*.json")):
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            states.append({
                "version": data["version"],
                "phase": data["phase"],
                "timestamp": data["timestamp"],
                "description": data["description"],
                "coverage_percent": data.get("metrics", {}).get("coverage_percent", 0)
            })
        return states

    def clear(self) -> int:
        """Clear all intermediate states. Returns count deleted."""
        count = 0
        for filepath in self.intermediates_dir.glob("state_*.json"):
            filepath.unlink()
            count += 1
        return count
```

## Testing

Create a test file to verify the implementation:

```python
# tests/test_provenance.py

import pytest
from spec_manager.core.provenance import (
    TrackedUnit, ProvenanceTracker, UnitType, UnitStatus,
    SourceLocation, TargetLocation, parse_stamp, generate_stamp
)
from spec_manager.core.intermediate import IntermediateManager, IntermediateState


def test_tracked_unit_creation():
    unit = TrackedUnit(
        id="Algorithm 1",
        content="## Algorithm 1\n\nSome content here",
        unit_type=UnitType.ALGORITHM,
        source=SourceLocation(file="p1.md", line_start=10, line_end=20, patch_id="p1"),
        introduced_by="p1"
    )

    assert unit.id == "Algorithm 1"
    assert unit.status == UnitStatus.PENDING
    assert unit.introduced_by == "p1"


def test_tracker_extracts_units():
    tracker = ProvenanceTracker()

    content = '''## Algorithm 1 ([=Algorithm 1])

First algorithm content.

## Algorithm 2 ([=Algorithm 2])

Second algorithm content.
'''

    units = tracker.extract_units_from_file(content, "test.md", patch_id="p1")

    assert len(units) == 2
    assert units[0].id == "Algorithm 1"
    assert units[1].id == "Algorithm 2"


def test_coverage_tracking():
    tracker = ProvenanceTracker()
    content = "## Test ([=Test1])\n\nContent"
    units = tracker.extract_units_from_file(content, "test.md", "p1")

    # Initially unaccounted
    report = tracker.get_coverage_report()
    assert report["unaccounted"] == 1

    # Map the unit
    tracker.record_mapping("Test1", TargetLocation("output.md", 1, 5))

    report = tracker.get_coverage_report()
    assert report["mapped"] == 1
    assert report["unaccounted"] == 0


def test_stamp_parsing():
    stamp = "<!-- @from:p1 @modified:p5,p7 @line:234 -->"
    parsed = parse_stamp(stamp)

    assert parsed["from"] == "p1"
    assert parsed["modified"] == ["p5", "p7"]
    assert parsed["line"] == "234"


def test_stamp_generation():
    stamp = generate_stamp("p1", ["p5", "p7"], 234)
    assert "@from:p1" in stamp
    assert "@modified:p5,p7" in stamp
    assert "@line:234" in stamp
```

## Integration Points

This phase provides the foundation that other phases build on:

- **Phase B (Strategies)**: Strategies use TrackedUnits as their input/output
- **Phase C (Discovery)**: Multi-labeling populates TrackedUnit.candidate_libraries
- **Phase D (Scripts)**: Gap detection uses provenance to report dropped content
- **Phase E (Workflow)**: Orchestrator creates IntermediateStates at each step

## Success Criteria

1. Can extract TrackedUnits from any spec file
2. Can track where each unit goes (mapped, dropped, merged)
3. Can generate coverage report showing nothing unaccounted
4. Can save/load intermediate states
5. Can compare states to see what changed
6. Stamps can be parsed and generated correctly

## Common Pitfalls to Avoid

1. **Don't persist stamps permanently** - They're only for current ingest
2. **Don't skip prose units** - They may contain requirements
3. **Don't assume unit boundaries** - A line might span multiple units
4. **Don't lose the content hash** - Needed for duplicate detection
