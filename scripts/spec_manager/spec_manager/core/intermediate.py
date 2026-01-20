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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .provenance import ProvenanceTracker

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
    version: int  # Increments each pass
    phase: str  # cleaning, discovery, review, finalize
    timestamp: datetime = field(default_factory=datetime.now)

    # Description of what this state represents
    description: str = ""

    # All tracked units at this state - FULL CONTENT, not previews
    units: dict[str, dict[str, Any]] = field(default_factory=dict)  # Serialized TrackedUnits

    # Units that haven't been placed yet
    remainder_ids: list[str] = field(default_factory=list)

    # File states
    file_snapshots: dict[str, FileSnapshot] = field(default_factory=dict)

    # Reconstructed intermediate markdown for diffing (FULL content)
    intermediate_files: dict[str, str] = field(default_factory=dict)

    # Membership tracking for verification
    atom_mapping: dict[str, str] = field(default_factory=dict)  # atom_id -> target_location

    # Library discovery state (Phase C)
    candidate_libraries: list[str] = field(default_factory=list)
    library_shapes: dict[str, dict[str, Any]] = field(default_factory=dict)

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

    def __init__(self, workspace_path: Path) -> None:
        self.workspace_path = workspace_path
        self.intermediates_dir = workspace_path / "intermediates"
        self.intermediates_dir.mkdir(parents=True, exist_ok=True)

    def create_snapshot(
        self,
        phase: str,
        description: str,
        tracker: ProvenanceTracker,
        candidate_libraries: list[str] | None = None,
        library_shapes: dict[str, dict[str, Any]] | None = None,
        # Gap 4 fix: Accept additional snapshot data
        intermediate_files: dict[str, str] | None = None,
        atom_mapping: dict[str, str] | None = None,
    ) -> IntermediateState:
        """
        Create a snapshot of current processing state.

        Gap 4 fix: Snapshots now ACTUALLY PERSIST:
        1. file_snapshots - state of processed files
        2. intermediate_files - reconstructed markdown for each pass
        3. atom_mapping - atom_id -> target_location mapping

        These are REQUIRED for the "trace" workflow to replay mapping
        using stored intermediate states.
        """
        # Get next version number
        existing = list(self.intermediates_dir.glob("state_*.json"))
        version = len(existing) + 1

        # Serialize units
        units: dict[str, dict[str, Any]] = {}
        for uid, unit in tracker.units.items():
            units[uid] = self._serialize_unit(unit)

        # Get remainders
        remainder_ids = [u.id for u in tracker.get_unaccounted()]

        # Compute metrics
        report = tracker.get_coverage_report()

        # Gap 4 fix: Build file_snapshots from tracker state
        file_snapshots: dict[str, FileSnapshot] = {}
        seen_files: set[str] = set()
        for unit in tracker.units.values():
            if unit.source.file and unit.source.file not in seen_files:
                seen_files.add(unit.source.file)
                # Create FileSnapshot for this source file
                file_snapshots[unit.source.file] = FileSnapshot(
                    path=unit.source.file,
                    content_hash=hashlib.md5(unit.content.encode()).hexdigest(),
                    line_count=unit.source.line_end - unit.source.line_start + 1,
                    unit_count=sum(
                        1
                        for u in tracker.units.values()
                        if u.source.file == unit.source.file
                    ),
                )

        # Gap 4 fix: Build atom_mapping from tracker state if not provided
        computed_atom_mapping = atom_mapping or {}
        if not computed_atom_mapping:
            for uid, unit in tracker.units.items():
                if unit.target:
                    # Map source atoms to target locations
                    for i, line in enumerate(unit.content.split("\n")):
                        if line.strip():
                            atom_id = f"{uid}_L{i+1}_{hash(line) % 10000:04d}"
                            target_loc = f"{unit.target.file}:{unit.target.line_start + i}"
                            computed_atom_mapping[atom_id] = target_loc

        # Gap 4 fix: Build intermediate_files if not provided
        computed_intermediate_files = intermediate_files or {}
        if not computed_intermediate_files:
            # Reconstruct per-library intermediate markdown
            by_library: dict[str, list[str]] = {}
            for uid, unit in tracker.units.items():
                lib = unit.primary_library or "unassigned"
                if lib not in by_library:
                    by_library[lib] = []
                by_library[lib].append(unit.content)

            for lib_name, contents in by_library.items():
                computed_intermediate_files[f"{lib_name}.md"] = "\n\n".join(contents)

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
                "coverage_percent": report["coverage_percent"],
            },
        )

    def _serialize_unit(self, unit: TrackedUnit) -> dict[str, Any]:
        """
        Serialize a TrackedUnit to dict.

        CRITICAL: Store FULL content (not just preview/hash) so that
        line-by-line membership checks can be performed between states.
        This enables "diff lines with lines" verification.
        """
        return {
            "id": unit.id,
            "content": unit.content,  # FULL content, not preview
            "content_hash": hashlib.md5(unit.content.encode()).hexdigest(),
            "unit_type": unit.unit_type.value,
            "source": {
                "file": unit.source.file,
                "line_start": unit.source.line_start,
                "line_end": unit.source.line_end,
                "patch_id": unit.source.patch_id,
            },
            "introduced_by": unit.introduced_by,
            "modified_by": unit.modified_by,
            "declarations": unit.declarations,
            "references": unit.references,
            "status": unit.status.value,
            "target": {
                "file": unit.target.file,
                "line_start": unit.target.line_start,
                "line_end": unit.target.line_end,
            }
            if unit.target
            else None,
            "drop_reason": unit.drop_reason,
            "primary_library": unit.primary_library,
            "candidate_libraries": unit.candidate_libraries,
            "relation_libraries": unit.relation_libraries,
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
        serialized_file_snapshots: dict[str, dict[str, Any]] = {}
        for path, snapshot in state.file_snapshots.items():
            serialized_file_snapshots[path] = {
                "path": snapshot.path,
                "content_hash": snapshot.content_hash,
                "line_count": snapshot.line_count,
                "unit_count": snapshot.unit_count,
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
            "atom_mapping": state.atom_mapping,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        # Gap 4 fix: Also persist intermediate files to disk for easy access
        intermediates_content_dir = self.intermediates_dir / f"v{state.version:04d}"
        intermediates_content_dir.mkdir(exist_ok=True)
        for filename_key, content in state.intermediate_files.items():
            intermediate_path = intermediates_content_dir / filename_key
            intermediate_path.write_text(content, encoding="utf-8")

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

        with open(matches[0], "r", encoding="utf-8") as f:
            data = json.load(f)

        # Gap 4 fix: Deserialize FileSnapshot objects
        file_snapshots: dict[str, FileSnapshot] = {}
        for path, snapshot_data in data.get("file_snapshots", {}).items():
            file_snapshots[path] = FileSnapshot(
                path=snapshot_data["path"],
                content_hash=snapshot_data["content_hash"],
                line_count=snapshot_data["line_count"],
                unit_count=snapshot_data["unit_count"],
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
            atom_mapping=data.get("atom_mapping", {}),
        )

    def load_latest(self) -> IntermediateState | None:
        """
        Load the most recent intermediate state.

        Gap 4 fix: Now deserializes file_snapshots, intermediate_files, and atom_mapping.
        """
        existing = sorted(self.intermediates_dir.glob("state_*.json"))
        if not existing:
            return None

        with open(existing[-1], "r", encoding="utf-8") as f:
            data = json.load(f)

        # Gap 4 fix: Deserialize FileSnapshot objects
        file_snapshots: dict[str, FileSnapshot] = {}
        for path, snapshot_data in data.get("file_snapshots", {}).items():
            file_snapshots[path] = FileSnapshot(
                path=snapshot_data["path"],
                content_hash=snapshot_data["content_hash"],
                line_count=snapshot_data["line_count"],
                unit_count=snapshot_data["unit_count"],
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
            atom_mapping=data.get("atom_mapping", {}),
        )

    def compare(
        self,
        state1: IntermediateState,
        state2: IntermediateState,
    ) -> dict[str, Any]:
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
                status_changes.append({"unit": uid, "from": s1, "to": s2})

        return {
            "from_version": state1.version,
            "to_version": state2.version,
            "units_added": list(added),
            "units_removed": list(removed),
            "status_changes": status_changes,
            "coverage_change": {
                "from": state1.metrics.get("coverage_percent", 0),
                "to": state2.metrics.get("coverage_percent", 0),
            },
            "remainder_change": {
                "from": len(state1.remainder_ids),
                "to": len(state2.remainder_ids),
            },
        }

    def list_states(self) -> list[dict[str, Any]]:
        """List all intermediate states with summary info."""
        states = []
        for filepath in sorted(self.intermediates_dir.glob("state_*.json")):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            states.append(
                {
                    "version": data["version"],
                    "phase": data["phase"],
                    "timestamp": data["timestamp"],
                    "description": data["description"],
                    "coverage_percent": data.get("metrics", {}).get(
                        "coverage_percent", 0
                    ),
                }
            )
        return states

    def clear(self) -> int:
        """Clear all intermediate states. Returns count deleted."""
        count = 0
        for filepath in self.intermediates_dir.glob("state_*.json"):
            filepath.unlink()
            count += 1
        # Also clear content directories
        for dir_path in self.intermediates_dir.glob("v*"):
            if dir_path.is_dir():
                for file in dir_path.iterdir():
                    file.unlink()
                dir_path.rmdir()
        return count
