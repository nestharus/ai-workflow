"""Physical directory layout for branches within a run.

This module defines the directory structure used by the branch
organization system within a run folder. It handles creation and
validation of the full branch directory tree.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .types import BranchKind


@dataclass
class BranchLayout:
    """Physical directory layout for branches within a run.

    Attributes:
        run_root: Root of the run directory.
    """

    run_root: Path

    @property
    def branches_dir(self) -> Path:
        """Root of the branches directory tree."""
        return self.run_root / "branches"

    @property
    def atoms_dir(self) -> Path:
        """Single source of truth for atom files."""
        return self.branches_dir / "atoms"

    @property
    def atom_registry_path(self) -> Path:
        """Path to the atom registry JSON file."""
        return self.atoms_dir / "__registry__.json"

    @property
    def pin_registry_path(self) -> Path:
        """Path to the pin registry JSON file."""
        return self.branches_dir / "__pins__.json"

    @property
    def slices_path(self) -> Path:
        """Path to the vertical slices JSON file."""
        return self.branches_dir / "__slices__.json"

    def branch_dir(self, kind: BranchKind) -> Path:
        """Get the directory for a specific branch kind."""
        return self.branches_dir / kind.value

    def algorithmic_dir(self) -> Path:
        """Get the algorithmic branch directory."""
        return self.branch_dir(BranchKind.ALGORITHMIC)

    def architectural_dir(self) -> Path:
        """Get the architectural branch directory."""
        return self.branch_dir(BranchKind.ARCHITECTURAL)

    def analysis_dir(self) -> Path:
        """Get the analysis branch directory."""
        return self.branch_dir(BranchKind.ANALYSIS)

    def _get_subdirs(self) -> list[Path]:
        """Return all subdirectories that should exist in the branch layout."""
        return [
            self.branches_dir,
            self.atoms_dir,
            # Algorithmic branch subdirectories
            self.algorithmic_dir() / "atoms",
            self.algorithmic_dir() / "compositions",
            self.algorithmic_dir() / "stores",
            self.algorithmic_dir() / "shapes",
            # Architectural branch subdirectories
            self.architectural_dir() / "services",
            self.architectural_dir() / "events",
            self.architectural_dir() / "middleware",
            self.architectural_dir() / "infrastructure",
            # Analysis branch (flat)
            self.analysis_dir(),
        ]

    def initialize(self) -> None:
        """Create the full branch directory structure."""
        for subdir in self._get_subdirs():
            subdir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> list[str]:
        """Validate the branch directory structure exists.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors: list[str] = []
        for subdir in self._get_subdirs():
            if not subdir.exists():
                errors.append(f"Missing directory: {subdir}")
        return errors
