"""Tests for spec_manager.core.id_registry module.

Tests for FileUidRegistry (ALG-CORE-0001) and RevisionRegistry (ALG-CORE-0002)
covering allocation, persistence, and constraint compliance.
"""

from __future__ import annotations

from pathlib import Path

from spec_manager.core.id_registry import (
    FileUidEntry,
    FileUidRegistry,
    RevisionEntry,
    RevisionRegistry,
)


class TestFileUidRegistry:
    """Tests for FileUidRegistry (ALG-CORE-0001)."""

    def test_allocate_new_file_uid(self) -> None:
        """Fresh allocation increments sequence."""
        registry = FileUidRegistry()
        uid = registry.allocate("requirements/core.md", "run_001")
        assert uid == "F0001"
        assert registry.next_seq == 2

    def test_allocate_existing_returns_same_uid(self) -> None:
        """Idempotent on same path."""
        registry = FileUidRegistry()
        uid1 = registry.allocate("requirements/core.md", "run_001")
        uid2 = registry.allocate("requirements/core.md", "run_002")
        assert uid1 == uid2 == "F0001"
        assert registry.next_seq == 2  # Should not increment again

    def test_registry_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Save/load preserves state."""
        registry = FileUidRegistry()
        registry.allocate("file1.md", "run_001")
        registry.allocate("file2.md", "run_001")

        # Save
        registry_path = tmp_path / "file_uids.json"
        registry.save(registry_path)

        # Load
        loaded = FileUidRegistry.load(registry_path)
        assert loaded.next_seq == registry.next_seq
        assert len(loaded.entries) == 2
        assert loaded.get_uid("file1.md") == "F0001"
        assert loaded.get_uid("file2.md") == "F0002"

    def test_concurrent_paths_get_unique_uids(self) -> None:
        """No collisions when allocating multiple paths."""
        registry = FileUidRegistry()
        uids = set()
        for i in range(100):
            uid = registry.allocate(f"file_{i:03d}.md", "run_001")
            uids.add(uid)
        assert len(uids) == 100

    def test_get_uid_returns_none_for_unknown_path(self) -> None:
        """get_uid returns None for unregistered paths."""
        registry = FileUidRegistry()
        assert registry.get_uid("unknown.md") is None

    def test_get_path_returns_canonical_path(self) -> None:
        """get_path retrieves canonical path for file UID."""
        registry = FileUidRegistry()
        registry.allocate("requirements/core.md", "run_001")
        path = registry.get_path("F0001")
        assert path == "requirements/core.md"

    def test_get_path_returns_none_for_unknown_uid(self) -> None:
        """get_path returns None for unregistered UIDs."""
        registry = FileUidRegistry()
        assert registry.get_path("F9999") is None

    def test_entry_stores_first_seen_run_id(self) -> None:
        """FileUidEntry stores the run_id when first seen."""
        registry = FileUidRegistry()
        registry.allocate("file.md", "run_001")
        entry = registry.entries["file.md"]
        assert entry.first_seen_run_id == "run_001"

        # Subsequent allocation doesn't change first_seen_run_id
        registry.allocate("file.md", "run_002")
        entry = registry.entries["file.md"]
        assert entry.first_seen_run_id == "run_001"

    def test_entry_has_created_at_timestamp(self) -> None:
        """FileUidEntry has ISO8601 timestamp."""
        registry = FileUidRegistry()
        registry.allocate("file.md", "run_001")
        entry = registry.entries["file.md"]
        assert "T" in entry.created_at  # ISO8601 format check

    def test_to_dict_includes_schema_version(self) -> None:
        """Serialization includes schema version."""
        registry = FileUidRegistry()
        data = registry.to_dict()
        assert data["schema_version"] == "1.0"

    def test_load_creates_empty_registry_if_file_missing(self, tmp_path: Path) -> None:
        """Load returns empty registry if file doesn't exist."""
        registry = FileUidRegistry.load(tmp_path / "nonexistent.json")
        assert registry.next_seq == 1
        assert len(registry.entries) == 0


class TestRevisionRegistry:
    """Tests for RevisionRegistry (ALG-CORE-0002)."""

    def test_allocate_new_revision(self) -> None:
        """Fresh content gets R0001."""
        registry = RevisionRegistry()
        rev_id = registry.allocate("F0001", "abc123hash")
        assert rev_id == "R0001"

    def test_same_content_returns_same_revision(self) -> None:
        """Idempotent per CON-0001."""
        registry = RevisionRegistry()
        rev1 = registry.allocate("F0001", "abc123hash")
        rev2 = registry.allocate("F0001", "abc123hash")
        assert rev1 == rev2 == "R0001"
        assert len(registry.entries.get("F0001", [])) == 1

    def test_modified_content_increments_revision(self) -> None:
        """R0001 -> R0002 on content change."""
        registry = RevisionRegistry()
        rev1 = registry.allocate("F0001", "hash_v1")
        rev2 = registry.allocate("F0001", "hash_v2")
        assert rev1 == "R0001"
        assert rev2 == "R0002"

    def test_revisions_append_only(self) -> None:
        """Old revisions never removed (CON-0001)."""
        registry = RevisionRegistry()
        registry.allocate("F0001", "hash_v1")
        registry.allocate("F0001", "hash_v2")
        registry.allocate("F0001", "hash_v3")

        revisions = registry.get_all_revisions("F0001")
        assert len(revisions) == 3
        assert revisions[0].rev_id == "R0001"
        assert revisions[1].rev_id == "R0002"
        assert revisions[2].rev_id == "R0003"

    def test_revision_registry_persistence_roundtrip(self, tmp_path: Path) -> None:
        """Save/load preserves all revisions."""
        registry = RevisionRegistry()
        registry.allocate("F0001", "hash_v1")
        registry.allocate("F0001", "hash_v2")
        registry.allocate("F0002", "hash_a")

        # Save
        registry_path = tmp_path / "revisions.json"
        registry.save(registry_path)

        # Load
        loaded = RevisionRegistry.load(registry_path)
        assert loaded.get_revision("F0001", "hash_v1") == "R0001"
        assert loaded.get_revision("F0001", "hash_v2") == "R0002"
        assert loaded.get_revision("F0002", "hash_a") == "R0001"

    def test_get_revision_returns_none_for_unknown(self) -> None:
        """get_revision returns None for unregistered content."""
        registry = RevisionRegistry()
        assert registry.get_revision("F0001", "unknown_hash") is None

    def test_get_latest_revision(self) -> None:
        """get_latest_revision returns most recent revision."""
        registry = RevisionRegistry()
        registry.allocate("F0001", "hash_v1")
        registry.allocate("F0001", "hash_v2")
        assert registry.get_latest_revision("F0001") == "R0002"

    def test_get_latest_revision_returns_none_if_no_revisions(self) -> None:
        """get_latest_revision returns None for files with no revisions."""
        registry = RevisionRegistry()
        assert registry.get_latest_revision("F0001") is None

    def test_revision_entry_stores_sha256(self) -> None:
        """RevisionEntry stores content hash."""
        registry = RevisionRegistry()
        registry.allocate("F0001", "0" * 64)
        revisions = registry.get_all_revisions("F0001")
        assert revisions[0].sha256 == "0" * 64

    def test_revision_entry_has_created_at_timestamp(self) -> None:
        """RevisionEntry has ISO8601 timestamp."""
        registry = RevisionRegistry()
        registry.allocate("F0001", "hash")
        revisions = registry.get_all_revisions("F0001")
        assert "T" in revisions[0].created_at

    def test_to_dict_includes_schema_version(self) -> None:
        """Serialization includes schema version."""
        registry = RevisionRegistry()
        data = registry.to_dict()
        assert data["schema_version"] == "1.0"

    def test_load_creates_empty_registry_if_file_missing(self, tmp_path: Path) -> None:
        """Load returns empty registry if file doesn't exist."""
        registry = RevisionRegistry.load(tmp_path / "nonexistent.json")
        assert len(registry.entries) == 0

    def test_multiple_files_have_independent_revisions(self) -> None:
        """Each file_uid has independent revision sequences."""
        registry = RevisionRegistry()
        rev_f1_v1 = registry.allocate("F0001", "hash_a")
        rev_f2_v1 = registry.allocate("F0002", "hash_b")
        rev_f1_v2 = registry.allocate("F0001", "hash_c")
        rev_f2_v2 = registry.allocate("F0002", "hash_d")

        assert rev_f1_v1 == "R0001"
        assert rev_f2_v1 == "R0001"
        assert rev_f1_v2 == "R0002"
        assert rev_f2_v2 == "R0002"


class TestFileUidEntry:
    """Tests for FileUidEntry serialization."""

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """Serialization roundtrip preserves all fields."""
        entry = FileUidEntry(
            file_uid="F0001",
            canonical_path="requirements/core.md",
            first_seen_run_id="run_001",
            created_at="2024-01-15T10:30:00",
        )
        data = entry.to_dict()
        restored = FileUidEntry.from_dict(data)

        assert restored.file_uid == entry.file_uid
        assert restored.canonical_path == entry.canonical_path
        assert restored.first_seen_run_id == entry.first_seen_run_id
        assert restored.created_at == entry.created_at


class TestRevisionEntry:
    """Tests for RevisionEntry serialization."""

    def test_to_dict_from_dict_roundtrip(self) -> None:
        """Serialization roundtrip preserves all fields."""
        entry = RevisionEntry(
            rev_id="R0001",
            file_uid="F0001",
            sha256="0" * 64,
            created_at="2024-01-15T10:30:00",
        )
        data = entry.to_dict()
        restored = RevisionEntry.from_dict(data)

        assert restored.rev_id == entry.rev_id
        assert restored.file_uid == entry.file_uid
        assert restored.sha256 == entry.sha256
        assert restored.created_at == entry.created_at
