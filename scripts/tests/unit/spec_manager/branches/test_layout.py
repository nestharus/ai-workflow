"""Tests for BranchLayout directory creation and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import BranchKind


class TestBranchLayout:
    """Tests for BranchLayout path properties, initialization, and validation."""

    @pytest.fixture
    def layout(self, tmp_path: Path) -> BranchLayout:
        return BranchLayout(run_root=tmp_path)

    def test_branches_dir(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.branches_dir == tmp_path / "branches"

    def test_atoms_dir(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.atoms_dir == tmp_path / "branches" / "atoms"

    def test_atom_registry_path(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.atom_registry_path == tmp_path / "branches" / "atoms" / "__registry__.json"

    def test_pin_registry_path(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.pin_registry_path == tmp_path / "branches" / "__pins__.json"

    def test_slices_path(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.slices_path == tmp_path / "branches" / "__slices__.json"

    def test_branch_dir_by_kind(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.branch_dir(BranchKind.ALGORITHMIC) == tmp_path / "branches" / "algorithmic"
        assert layout.branch_dir(BranchKind.ARCHITECTURAL) == tmp_path / "branches" / "architectural"
        assert layout.branch_dir(BranchKind.ANALYSIS) == tmp_path / "branches" / "analysis"

    def test_convenience_dirs(self, layout: BranchLayout, tmp_path: Path) -> None:
        assert layout.algorithmic_dir() == tmp_path / "branches" / "algorithmic"
        assert layout.architectural_dir() == tmp_path / "branches" / "architectural"
        assert layout.analysis_dir() == tmp_path / "branches" / "analysis"

    def test_initialize_creates_all_dirs(self, layout: BranchLayout) -> None:
        layout.initialize()

        assert layout.branches_dir.exists()
        assert layout.atoms_dir.exists()
        assert (layout.algorithmic_dir() / "atoms").exists()
        assert (layout.algorithmic_dir() / "compositions").exists()
        assert (layout.algorithmic_dir() / "stores").exists()
        assert (layout.algorithmic_dir() / "shapes").exists()
        assert (layout.architectural_dir() / "services").exists()
        assert (layout.architectural_dir() / "events").exists()
        assert (layout.architectural_dir() / "middleware").exists()
        assert (layout.architectural_dir() / "infrastructure").exists()
        assert layout.analysis_dir().exists()

    def test_initialize_is_idempotent(self, layout: BranchLayout) -> None:
        layout.initialize()
        layout.initialize()
        errors = layout.validate()
        assert errors == []

    def test_validate_passes_after_init(self, layout: BranchLayout) -> None:
        layout.initialize()
        assert layout.validate() == []

    def test_validate_fails_before_init(self, layout: BranchLayout) -> None:
        errors = layout.validate()
        assert len(errors) > 0
        assert any("Missing directory" in e for e in errors)
