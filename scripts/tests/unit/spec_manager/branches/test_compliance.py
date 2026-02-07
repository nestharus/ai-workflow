"""Tests for ComplianceChecker gate checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.compliance import ComplianceChecker, ComplianceGateResult
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import AtomDescriptor, AtomKind, VerticalSlice


@pytest.fixture
def layout(tmp_path: Path) -> BranchLayout:
    bl = BranchLayout(run_root=tmp_path)
    bl.initialize()
    return bl


@pytest.fixture
def atom_registry(layout: BranchLayout) -> AtomRegistry:
    return AtomRegistry(layout)


@pytest.fixture
def checker(layout: BranchLayout, atom_registry: AtomRegistry) -> ComplianceChecker:
    return ComplianceChecker(layout, atom_registry)


def _make_atom(atom_id: str, kind: AtomKind = AtomKind.ALGORITHM) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=kind,
        file_path=f"{atom_id}.py",
        function_name=atom_id,
        signature="()",
        content_hash="h" + atom_id,
        introduced_by="plan-1",
    )


class TestCheckNoComments:
    """Tests for the no-comments compliance gate."""

    def test_passes_with_no_files(self, checker: ComplianceChecker) -> None:
        ok, errors = checker.check_no_comments()
        assert ok is True
        assert errors == []

    def test_fails_with_comments(self, layout: BranchLayout, checker: ComplianceChecker) -> None:
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    # todo: implement\n    return 1\n",
            encoding="utf-8",
        )
        ok, errors = checker.check_no_comments()
        assert ok is False
        assert len(errors) >= 1

    def test_passes_without_comments(self, layout: BranchLayout, checker: ComplianceChecker) -> None:
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    return 1\n",
            encoding="utf-8",
        )
        ok, errors = checker.check_no_comments()
        assert ok is True


class TestCheckNoStubs:
    """Tests for the no-stubs compliance gate."""

    def test_passes_with_no_files(self, checker: ComplianceChecker) -> None:
        ok, errors = checker.check_no_stubs()
        assert ok is True

    def test_fails_with_stub(self, layout: BranchLayout, checker: ComplianceChecker) -> None:
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    pass\n",
            encoding="utf-8",
        )
        ok, errors = checker.check_no_stubs()
        assert ok is False

    def test_passes_with_implemented(self, layout: BranchLayout, checker: ComplianceChecker) -> None:
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    return 42\n",
            encoding="utf-8",
        )
        ok, errors = checker.check_no_stubs()
        assert ok is True


class TestCheckTestsPass:
    """Tests for the tests-pass compliance gate."""

    def test_passes_by_default(self, checker: ComplianceChecker) -> None:
        ok, errors = checker.check_tests_pass()
        assert ok is True
        assert errors == []


class TestCheckCallGraphConnected:
    """Tests for the call graph connected compliance gate."""

    def test_passes_with_no_atoms(self, checker: ComplianceChecker) -> None:
        ok, errors = checker.check_call_graph_connected()
        assert ok is True

    def test_passes_with_single_atom(
        self, atom_registry: AtomRegistry, checker: ComplianceChecker,
    ) -> None:
        atom_registry.register(_make_atom("solo"))
        ok, errors = checker.check_call_graph_connected()
        assert ok is True


class TestCheckStoreMonogamy:
    """Tests for the store monogamy compliance gate."""

    def test_passes_with_no_violations(self, checker: ComplianceChecker) -> None:
        slices = [
            VerticalSlice(slice_id="VS-0001", name="Payment", store_ids=["s1"]),
            VerticalSlice(slice_id="VS-0002", name="Order", store_ids=["s2"]),
        ]
        ok, errors = checker.check_store_monogamy(slices)
        assert ok is True
        assert errors == []

    def test_fails_with_shared_store(self, checker: ComplianceChecker) -> None:
        slices = [
            VerticalSlice(slice_id="VS-0001", name="Payment", store_ids=["shared_store"]),
            VerticalSlice(slice_id="VS-0002", name="Order", store_ids=["shared_store"]),
        ]
        ok, errors = checker.check_store_monogamy(slices)
        assert ok is False
        assert any("shared_store" in e for e in errors)


class TestCheckAll:
    """Tests for the combined compliance check."""

    def test_passes_when_all_pass(self, checker: ComplianceChecker) -> None:
        result = checker.check_all()
        assert result.passed is True
        assert result.no_comments is True
        assert result.no_stubs is True
        assert result.tests_pass is True
        assert result.call_graph_connected is True
        assert result.store_monogamy is True

    def test_fails_when_comments_present(
        self, layout: BranchLayout, checker: ComplianceChecker,
    ) -> None:
        atoms_dir = layout.algorithmic_dir() / "atoms"
        atoms_dir.mkdir(parents=True, exist_ok=True)
        (atoms_dir / "a1.py").write_text(
            "def a1():\n    # todo\n    return 1\n",
            encoding="utf-8",
        )
        result = checker.check_all()
        assert result.passed is False
        assert result.no_comments is False


class TestComplianceGateResultSerialization:
    """Tests for ComplianceGateResult serialization."""

    def test_roundtrip(self) -> None:
        original = ComplianceGateResult(
            passed=False,
            no_comments=False,
            no_stubs=True,
            tests_pass=True,
            call_graph_connected=True,
            store_monogamy=True,
            errors=["Comment at line 5"],
            warnings=["Minor issue"],
        )
        data = original.to_dict()
        restored = ComplianceGateResult.from_dict(data)
        assert restored.passed == original.passed
        assert restored.no_comments == original.no_comments
        assert restored.errors == original.errors
        assert restored.warnings == original.warnings
