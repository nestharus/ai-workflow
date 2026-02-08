"""Tests for AtomRegistry registration, lookup, and persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.branches.atoms import AtomRegistry
from spec_manager.branches.layout import BranchLayout
from spec_manager.branches.types import AtomDescriptor, AtomKind, StoreType


@pytest.fixture
def layout(tmp_path: Path) -> BranchLayout:
    bl = BranchLayout(run_root=tmp_path)
    bl.initialize()
    return bl


@pytest.fixture
def registry(layout: BranchLayout) -> AtomRegistry:
    return AtomRegistry(layout)


def _make_atom(
    atom_id: str = "validate_payment",
    kind: AtomKind = AtomKind.ALGORITHM,
    **kwargs,
) -> AtomDescriptor:
    defaults = {
        "atom_id": atom_id,
        "kind": kind,
        "file_path": f"{atom_id}.py",
        "function_name": atom_id,
        "signature": "()",
        "content_hash": "h" + atom_id,
        "introduced_by": "plan-1",
    }
    defaults.update(kwargs)
    return AtomDescriptor(**defaults)


class TestAtomRegistry:
    """Tests for AtomRegistry CRUD and queries."""

    def test_register_and_get(self, registry: AtomRegistry) -> None:
        atom = _make_atom()
        registry.register(atom)
        assert registry.get("validate_payment") is atom

    def test_get_nonexistent(self, registry: AtomRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_unregister(self, registry: AtomRegistry) -> None:
        atom = _make_atom()
        registry.register(atom)
        registry.unregister("validate_payment")
        assert registry.get("validate_payment") is None

    def test_unregister_nonexistent_raises(self, registry: AtomRegistry) -> None:
        with pytest.raises(KeyError, match="Atom not registered"):
            registry.unregister("nonexistent")

    def test_list_all(self, registry: AtomRegistry) -> None:
        a1 = _make_atom("a1")
        a2 = _make_atom("a2")
        registry.register(a1)
        registry.register(a2)
        assert len(registry.list_all()) == 2

    def test_list_by_kind(self, registry: AtomRegistry) -> None:
        algo = _make_atom("algo", AtomKind.ALGORITHM)
        store = _make_atom("store", AtomKind.STORE)
        shape = _make_atom("shape", AtomKind.SHAPE)
        for a in (algo, store, shape):
            registry.register(a)

        assert len(registry.list_by_kind(AtomKind.ALGORITHM)) == 1
        assert len(registry.list_by_kind(AtomKind.STORE)) == 1
        assert len(registry.list_by_kind(AtomKind.SHAPE)) == 1

    def test_list_by_slice(self, registry: AtomRegistry) -> None:
        a1 = _make_atom("a1", vertical_slice="payment")
        a2 = _make_atom("a2", vertical_slice="payment")
        a3 = _make_atom("a3", vertical_slice="order")
        for a in (a1, a2, a3):
            registry.register(a)

        assert len(registry.list_by_slice("payment")) == 2
        assert len(registry.list_by_slice("order")) == 1
        assert len(registry.list_by_slice("nonexistent")) == 0

    def test_detect_changes_no_file(self, registry: AtomRegistry) -> None:
        atom = _make_atom()
        registry.register(atom)
        # File doesn't exist, so no changes detected
        assert registry.detect_changes() == []

    def test_detect_changes_with_modified_file(self, layout: BranchLayout) -> None:
        registry = AtomRegistry(layout)
        # Write a file
        atom_file = layout.atoms_dir / "validate_payment.py"
        atom_file.write_text("def validate_payment(): pass", encoding="utf-8")

        import hashlib

        content_hash = hashlib.sha256(b"def validate_payment(): pass").hexdigest()

        atom = _make_atom(content_hash=content_hash)
        registry.register(atom)

        # No changes yet
        assert registry.detect_changes() == []

        # Modify the file
        atom_file.write_text("def validate_payment(): return True", encoding="utf-8")
        changes = registry.detect_changes()
        assert len(changes) == 1
        assert changes[0][0] == "validate_payment"
        assert changes[0][1] == content_hash  # old hash
        assert changes[0][2] != content_hash  # new hash

    def test_save_and_load(self, layout: BranchLayout) -> None:
        registry = AtomRegistry(layout)
        a1 = _make_atom("a1", AtomKind.ALGORITHM, vertical_slice="payment")
        a2 = _make_atom("a2", AtomKind.STORE, store_type=StoreType.PERSISTED)
        registry.register(a1)
        registry.register(a2)
        registry.save()

        loaded = AtomRegistry.load(layout)
        assert loaded.get("a1") is not None
        assert loaded.get("a2") is not None
        assert loaded.get("a1").kind == AtomKind.ALGORITHM
        assert loaded.get("a2").store_type == StoreType.PERSISTED

    def test_load_empty(self, layout: BranchLayout) -> None:
        loaded = AtomRegistry.load(layout)
        assert loaded.list_all() == []
