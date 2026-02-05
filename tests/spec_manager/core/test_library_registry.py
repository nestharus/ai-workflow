"""Tests for library ID allocator (ALG-CORE-0006).

Tests:
- test_allocate_new_id: Fresh allocation increments sequence
- test_allocate_existing_returns_same: Idempotent on same stability key
- test_persistence_roundtrip: Save/load preserves state
- test_stability_key_generation: Generate stability keys from various inputs
"""

from pathlib import Path

import pytest

from spec_manager.core.library_registry import (
    LibraryEntry,
    LibraryIdAllocator,
    generate_stability_key,
)


class TestLibraryIdAllocator:
    """Tests for LibraryIdAllocator (ALG-CORE-0006)."""

    def test_allocate_new_library_id(self) -> None:
        """Fresh allocation increments sequence."""
        allocator = LibraryIdAllocator()
        lib_id, is_new = allocator.allocate_library_id("key1", "Library One")

        assert lib_id == "LIB-0001"
        assert is_new is True
        assert allocator.next_seq == 2

    def test_allocate_existing_returns_same_id(self) -> None:
        """Idempotent on same stability key."""
        allocator = LibraryIdAllocator()
        lib_id1, is_new1 = allocator.allocate_library_id("key1", "Library One")
        lib_id2, is_new2 = allocator.allocate_library_id("key1", "Library One Updated")

        assert lib_id1 == lib_id2 == "LIB-0001"
        assert is_new1 is True
        assert is_new2 is False
        assert allocator.next_seq == 2  # Should not increment again

    def test_allocate_different_keys_get_different_ids(self) -> None:
        """Different stability keys get different IDs."""
        allocator = LibraryIdAllocator()
        lib_id1, _ = allocator.allocate_library_id("key1", "Library One")
        lib_id2, _ = allocator.allocate_library_id("key2", "Library Two")
        lib_id3, _ = allocator.allocate_library_id("key3", "Library Three")

        assert lib_id1 == "LIB-0001"
        assert lib_id2 == "LIB-0002"
        assert lib_id3 == "LIB-0003"

    def test_get_lib_id_returns_existing(self) -> None:
        """get_lib_id returns existing lib_id."""
        allocator = LibraryIdAllocator()
        allocator.allocate_library_id("key1", "Library One")

        assert allocator.get_lib_id("key1") == "LIB-0001"

    def test_get_lib_id_returns_none_for_unknown(self) -> None:
        """get_lib_id returns None for unknown key."""
        allocator = LibraryIdAllocator()
        assert allocator.get_lib_id("unknown_key") is None

    def test_get_entry_by_lib_id(self) -> None:
        """get_entry_by_lib_id returns correct entry."""
        allocator = LibraryIdAllocator()
        allocator.allocate_library_id("key1", "Library One")

        entry = allocator.get_entry_by_lib_id("LIB-0001")
        assert entry is not None
        assert entry.name == "Library One"
        assert entry.stability_key == "key1"

    def test_get_entry_by_lib_id_returns_none_for_unknown(self) -> None:
        """get_entry_by_lib_id returns None for unknown lib_id."""
        allocator = LibraryIdAllocator()
        assert allocator.get_entry_by_lib_id("LIB-9999") is None

    def test_get_all_lib_ids(self) -> None:
        """get_all_lib_ids returns all IDs in order."""
        allocator = LibraryIdAllocator()
        allocator.allocate_library_id("key1", "Lib 1")
        allocator.allocate_library_id("key2", "Lib 2")
        allocator.allocate_library_id("key3", "Lib 3")

        all_ids = allocator.get_all_lib_ids()
        assert all_ids == ["LIB-0001", "LIB-0002", "LIB-0003"]

    def test_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Save/load preserves state."""
        allocator = LibraryIdAllocator()
        allocator.allocate_library_id("key1", "Library One")
        allocator.allocate_library_id("key2", "Library Two")

        # Save
        registry_path = tmp_path / "library_ids.json"
        allocator.save(registry_path)

        # Load
        loaded = LibraryIdAllocator.load(registry_path)
        assert loaded.next_seq == allocator.next_seq
        assert len(loaded.entries) == 2
        assert loaded.get_lib_id("key1") == "LIB-0001"
        assert loaded.get_lib_id("key2") == "LIB-0002"

    def test_load_creates_empty_if_file_missing(self, tmp_path: Path) -> None:
        """load returns empty allocator if file doesn't exist."""
        allocator = LibraryIdAllocator.load(tmp_path / "nonexistent.json")
        assert allocator.next_seq == 1
        assert len(allocator.entries) == 0

    def test_to_dict_includes_schema_version(self) -> None:
        """Serialization includes schema version."""
        allocator = LibraryIdAllocator()
        data = allocator.to_dict()
        assert data["schema_version"] == "1.0"

    def test_name_update_on_reallocate(self) -> None:
        """Name is updated when reallocating with different name."""
        allocator = LibraryIdAllocator()
        allocator.allocate_library_id("key1", "Original Name")
        allocator.allocate_library_id("key1", "Updated Name")

        entry = allocator.get_entry_by_lib_id("LIB-0001")
        assert entry is not None
        assert entry.name == "Updated Name"


class TestLibraryEntry:
    """Tests for LibraryEntry serialization."""

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """Serialization roundtrip preserves all fields."""
        entry = LibraryEntry(
            lib_id="LIB-0001",
            stability_key="test_key",
            name="Test Library",
            created_at="2024-01-15T10:30:00",
        )
        data = entry.to_dict()
        restored = LibraryEntry.from_dict(data)

        assert restored.lib_id == entry.lib_id
        assert restored.stability_key == entry.stability_key
        assert restored.name == entry.name
        assert restored.created_at == entry.created_at


class TestGenerateStabilityKey:
    """Tests for generate_stability_key function."""

    def test_from_entity_ids(self) -> None:
        """Test stability key from entity IDs."""
        key = generate_stability_key(seed_entity_ids=["ENT-0003", "ENT-0001", "ENT-0002"])
        # Should be sorted
        assert key == "ENT:ENT-0001|ENT-0002|ENT-0003"

    def test_from_atom_ids(self) -> None:
        """Test stability key from atom IDs."""
        key = generate_stability_key(seed_atom_ids=["ATOM-3", "ATOM-1", "ATOM-2"])
        assert key == "ATOM:ATOM-1|ATOM-2|ATOM-3"

    def test_from_proposed_name(self) -> None:
        """Test stability key from proposed name."""
        key = generate_stability_key(proposed_name="User Authentication System")
        assert key == "NAME:user_authentication_system"

    def test_priority_entity_over_atom(self) -> None:
        """Test entity IDs take priority over atom IDs."""
        key = generate_stability_key(
            seed_entity_ids=["ENT-0001"],
            seed_atom_ids=["ATOM-1"],
        )
        assert key.startswith("ENT:")

    def test_priority_atom_over_name(self) -> None:
        """Test atom IDs take priority over name."""
        key = generate_stability_key(
            seed_atom_ids=["ATOM-1"],
            proposed_name="Test",
        )
        assert key.startswith("ATOM:")

    def test_empty_inputs(self) -> None:
        """Test empty inputs return EMPTY key."""
        key = generate_stability_key()
        assert key == "EMPTY"

    def test_empty_lists_fallback(self) -> None:
        """Test empty lists fall back to next option."""
        key = generate_stability_key(
            seed_entity_ids=[],
            seed_atom_ids=["ATOM-1"],
        )
        assert key.startswith("ATOM:")
