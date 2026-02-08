"""Tests for test signature baselining and persistence."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.projection.lineage.test_pin_baseline import (
    TestPinBaselineStore,
    TestSignatureBaseline,
    build_baseline,
    load_baseline,
    save_baseline,
    update_baseline,
)
from spec_manager.projection.lineage.test_pin_discovery import (
    TestPinAssociation,
    TestPinMap,
)


def _write_test_file(tmp_path: Path, name: str, content: str) -> Path:
    """Write a test file with the given content."""
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def _make_test_pin_map(
    test_file: str,
    associations: list[tuple[str, str, str]] | None = None,
) -> TestPinMap:
    """Create a TestPinMap with given associations.

    Each tuple is (test_function, pin_func_id, pin_function_name).
    """
    assocs = []
    if associations:
        for test_func, pin_id, pin_name in associations:
            assocs.append(
                TestPinAssociation(
                    test_file=test_file,
                    test_function=test_func,
                    pin_func_id=pin_id,
                    pin_function_name=pin_name,
                    association_type="direct_import",
                    confidence=1.0,
                )
            )
    return TestPinMap(
        associations=assocs,
        scan_timestamp="2024-01-01T00:00:00Z",
        test_roots_scanned=[],
    )


class TestBuildBaseline:
    """Test building baseline from a TestPinMap with known test files."""

    def test_builds_baseline_from_map(self, tmp_path: Path) -> None:
        """Builds baseline with correct signature hashes."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            def test_valid_payment(amount: float) -> bool:
                assert amount > 0
                return True
            """,
        )
        test_map = _make_test_pin_map(
            str(test_file),
            [("test_valid_payment", "PFUNC-0001", "validate_payment")],
        )
        store = build_baseline(test_map)

        assert len(store.baselines) == 1
        bl = store.baselines[0]
        assert bl.test_function == "test_valid_payment"
        assert bl.pin_func_id == "PFUNC-0001"
        assert bl.signature_hash != ""
        assert bl.signature_text != ""
        assert bl.recorded_at != ""

    def test_class_qualified_test_function(self, tmp_path: Path) -> None:
        """Handles class-qualified names like TestClass.test_method."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            class TestPayment:
                def test_valid(self, amount: float) -> None:
                    assert amount > 0
            """,
        )
        test_map = _make_test_pin_map(
            str(test_file),
            [("TestPayment.test_valid", "PFUNC-0001", "validate_payment")],
        )
        store = build_baseline(test_map)

        assert len(store.baselines) == 1
        bl = store.baselines[0]
        assert bl.test_function == "TestPayment.test_valid"
        assert bl.signature_hash != ""

    def test_deduplicates_same_test_function(self, tmp_path: Path) -> None:
        """Same test function associated with multiple pins only gets one baseline."""
        test_file = _write_test_file(
            tmp_path,
            "test_multi.py",
            """\
            def test_workflow():
                pass
            """,
        )
        test_map = _make_test_pin_map(
            str(test_file),
            [
                ("test_workflow", "PFUNC-0001", "validate_payment"),
                ("test_workflow", "PFUNC-0002", "process_order"),
            ],
        )
        store = build_baseline(test_map)

        # Only one baseline entry per unique (test_file, test_function)
        assert len(store.baselines) == 1


class TestSaveLoadRoundTrip:
    """Test round-trip save/load preserves all fields."""

    def test_round_trip_preserves_all_fields(self, tmp_path: Path) -> None:
        """Save then load produces identical data."""
        store = TestPinBaselineStore(
            schema_version="1.0",
            baselines=[
                TestSignatureBaseline(
                    test_file="test_payment.py",
                    test_function="test_valid_payment",
                    pin_func_id="PFUNC-0001",
                    signature_hash="abc123def456",
                    signature_text="test_valid_payment|arg:amount:float",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
                TestSignatureBaseline(
                    test_file="test_order.py",
                    test_function="TestOrder.test_create",
                    pin_func_id="PFUNC-0002",
                    signature_hash="789xyz",
                    signature_text="test_create|arg:self:",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
            ],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T12:00:00Z",
        )

        path = tmp_path / ".spec" / "test_pin_baselines.json"
        save_baseline(store, path)
        loaded = load_baseline(path)

        assert loaded.schema_version == store.schema_version
        assert loaded.created_at == store.created_at
        assert loaded.updated_at == store.updated_at
        assert len(loaded.baselines) == len(store.baselines)

        for orig, loaded_bl in zip(store.baselines, loaded.baselines, strict=False):
            assert loaded_bl.test_file == orig.test_file
            assert loaded_bl.test_function == orig.test_function
            assert loaded_bl.pin_func_id == orig.pin_func_id
            assert loaded_bl.signature_hash == orig.signature_hash
            assert loaded_bl.signature_text == orig.signature_text
            assert loaded_bl.recorded_at == orig.recorded_at


class TestLoadBaseline:
    """Test loading baselines."""

    def test_load_nonexistent_returns_empty(self, tmp_path: Path) -> None:
        """Loading from a nonexistent path returns an empty store."""
        path = tmp_path / "does_not_exist.json"
        store = load_baseline(path)

        assert store.schema_version == "1.0"
        assert len(store.baselines) == 0
        assert store.created_at == ""
        assert store.updated_at == ""


class TestUpdateBaseline:
    """Test baseline update/merge logic."""

    def test_adds_new_baselines(self, tmp_path: Path) -> None:
        """New associations are added to the store."""
        test_file = _write_test_file(
            tmp_path,
            "test_new.py",
            """\
            def test_new_feature():
                pass
            """,
        )
        existing = TestPinBaselineStore(
            schema_version="1.0",
            baselines=[],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        new_map = _make_test_pin_map(
            str(test_file),
            [("test_new_feature", "PFUNC-0003", "new_feature")],
        )

        updated, changes = update_baseline(existing, new_map)

        assert len(updated.baselines) == 1
        assert len(changes) == 1
        assert "Added new baseline" in changes[0]

    def test_no_overwrite_without_force(self, tmp_path: Path) -> None:
        """Changed signatures are not overwritten without force=True."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            def test_valid_payment(amount: float, currency: str) -> bool:
                return True
            """,
        )
        existing = TestPinBaselineStore(
            schema_version="1.0",
            baselines=[
                TestSignatureBaseline(
                    test_file=str(test_file),
                    test_function="test_valid_payment",
                    pin_func_id="PFUNC-0001",
                    signature_hash="old_hash",
                    signature_text="old_text",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
            ],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        new_map = _make_test_pin_map(
            str(test_file),
            [("test_valid_payment", "PFUNC-0001", "validate_payment")],
        )

        updated, changes = update_baseline(existing, new_map, force=False)

        # Signature should NOT be overwritten
        assert updated.baselines[0].signature_hash == "old_hash"
        assert len(changes) == 1
        assert "Drift detected" in changes[0]

    def test_overwrite_with_force(self, tmp_path: Path) -> None:
        """Changed signatures are overwritten with force=True."""
        test_file = _write_test_file(
            tmp_path,
            "test_payment.py",
            """\
            def test_valid_payment(amount: float, currency: str) -> bool:
                return True
            """,
        )
        existing = TestPinBaselineStore(
            schema_version="1.0",
            baselines=[
                TestSignatureBaseline(
                    test_file=str(test_file),
                    test_function="test_valid_payment",
                    pin_func_id="PFUNC-0001",
                    signature_hash="old_hash",
                    signature_text="old_text",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
            ],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        new_map = _make_test_pin_map(
            str(test_file),
            [("test_valid_payment", "PFUNC-0001", "validate_payment")],
        )

        updated, changes = update_baseline(existing, new_map, force=True)

        # Signature SHOULD be overwritten
        assert updated.baselines[0].signature_hash != "old_hash"
        assert len(changes) == 1
        assert "Updated" in changes[0]

    def test_preserves_existing_when_adding_new(self, tmp_path: Path) -> None:
        """Adding new baselines does not affect existing ones."""
        test_file_new = _write_test_file(
            tmp_path,
            "test_new.py",
            """\
            def test_new():
                pass
            """,
        )
        existing = TestPinBaselineStore(
            schema_version="1.0",
            baselines=[
                TestSignatureBaseline(
                    test_file="test_old.py",
                    test_function="test_old",
                    pin_func_id="PFUNC-0001",
                    signature_hash="existing_hash",
                    signature_text="existing_text",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
            ],
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-01T00:00:00Z",
        )
        new_map = _make_test_pin_map(
            str(test_file_new),
            [("test_new", "PFUNC-0002", "new_feature")],
        )

        updated, _changes = update_baseline(existing, new_map)

        assert len(updated.baselines) == 2
        # Existing baseline is preserved
        assert updated.baselines[0].signature_hash == "existing_hash"
        # New baseline was added
        assert updated.baselines[1].test_function == "test_new"


class TestGetBaseline:
    """Test the get_baseline lookup method."""

    def test_finds_existing_baseline(self) -> None:
        """Gets a baseline by file and function name."""
        store = TestPinBaselineStore(
            baselines=[
                TestSignatureBaseline(
                    test_file="test_a.py",
                    test_function="test_foo",
                    pin_func_id="PFUNC-0001",
                    signature_hash="hash1",
                    signature_text="text1",
                    recorded_at="2024-01-01T00:00:00Z",
                ),
            ],
        )
        bl = store.get_baseline("test_a.py", "test_foo")
        assert bl is not None
        assert bl.signature_hash == "hash1"

    def test_returns_none_for_missing(self) -> None:
        """Returns None when baseline is not found."""
        store = TestPinBaselineStore()
        bl = store.get_baseline("nonexistent.py", "test_missing")
        assert bl is None
