"""Tests for scripts.knowledge.passes_manager module."""

from __future__ import annotations

from pathlib import Path

from scripts.knowledge.passes_manager import (
    PASSES_CSV_COLUMNS,
    PassRecord,
    append_pass,
    count_passes,
    ensure_passes_csv_exists,
    get_pass_by_id,
    query_passes,
)


class TestEnsurePassesCsvExists:
    """Tests for ensure_passes_csv_exists function."""

    def test_creates_csv_with_header_if_missing(self, tmp_path: Path) -> None:
        """Should create CSV file with header row if missing."""
        csv_path = tmp_path / "facts" / "passes.csv"

        ensure_passes_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        # Check header row exists
        for col in PASSES_CSV_COLUMNS:
            assert col in content

    def test_does_not_overwrite_existing_csv(self, tmp_path: Path) -> None:
        """Should not overwrite existing CSV file."""
        csv_path = tmp_path / "passes.csv"
        existing_content = (
            "pass_id,artifact_id,entity_id,entity_mention,span_id,chunk_id,"
            "span_before,span_after,facts_removed,similarity_score,status,"
            "failure_reason,created_at\n"
            "id-1,art-1,ent-1,mention,span-1,chunk-1,before,after,[],0.9,"
            "success,,2024-01-01\n"
        )
        csv_path.write_text(existing_content)

        ensure_passes_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "id-1" in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if they don't exist."""
        csv_path = tmp_path / "deep" / "nested" / "passes.csv"

        ensure_passes_csv_exists(csv_path)

        assert csv_path.exists()
        assert csv_path.parent.exists()


class TestAppendPass:
    """Tests for append_pass function."""

    def test_appends_pass_to_new_csv(self, tmp_path: Path) -> None:
        """Should create CSV and append pass record."""
        csv_path = tmp_path / "passes.csv"
        record = PassRecord(
            pass_id="pass-001",
            artifact_id="artifact-123",
            entity_id="entity-456",
            entity_mention="create_app",
            span_id="span-001",
            chunk_id="artifact-123:pass1:span-001",
            span_before="original text",
            span_after="modified text",
            facts_removed='["fact about create_app"]',
            similarity_score="0.95",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )

        append_pass(csv_path, record)

        assert csv_path.exists()
        content = csv_path.read_text()
        assert "pass-001" in content
        assert "artifact-123" in content

    def test_appends_multiple_passes(self, tmp_path: Path) -> None:
        """Should append multiple pass records to existing CSV."""
        csv_path = tmp_path / "passes.csv"

        record1 = PassRecord(
            pass_id="pass-001",
            artifact_id="artifact-1",
            entity_id="ent-1",
            entity_mention="entity1",
            span_id="span-1",
            chunk_id="artifact-1:pass1:span-1",
            span_before="before1",
            span_after="after1",
            facts_removed="[]",
            similarity_score="0.9",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )

        record2 = PassRecord(
            pass_id="pass-002",
            artifact_id="artifact-1",
            entity_id="ent-2",
            entity_mention="entity2",
            span_id="span-2",
            chunk_id="artifact-1:pass2:span-2",
            span_before="before2",
            span_after="after2",
            facts_removed="[]",
            similarity_score="0.85",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:01Z",
        )

        append_pass(csv_path, record1)
        append_pass(csv_path, record2)

        content = csv_path.read_text()
        assert "pass-001" in content
        assert "pass-002" in content


class TestQueryPasses:
    """Tests for query_passes function."""

    def test_returns_empty_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return empty list when CSV doesn't exist."""
        csv_path = tmp_path / "nonexistent.csv"
        result = query_passes(csv_path)
        assert result == []

    def test_returns_empty_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return empty list for empty CSV."""
        csv_path = tmp_path / "passes.csv"
        csv_path.write_text("")
        result = query_passes(csv_path)
        assert result == []

    def test_filters_by_artifact_id(self, tmp_path: Path) -> None:
        """Should filter passes by artifact_id when provided."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        record1 = PassRecord(
            pass_id="pass-001",
            artifact_id="artifact-A",
            entity_id="ent-1",
            entity_mention="entity1",
            span_id="span-1",
            chunk_id="artifact-A:pass1:span-1",
            span_before="before",
            span_after="after",
            facts_removed="[]",
            similarity_score="0.9",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )
        record2 = PassRecord(
            pass_id="pass-002",
            artifact_id="artifact-B",
            entity_id="ent-2",
            entity_mention="entity2",
            span_id="span-2",
            chunk_id="artifact-B:pass1:span-2",
            span_before="before",
            span_after="after",
            facts_removed="[]",
            similarity_score="0.9",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:01Z",
        )

        append_pass(csv_path, record1)
        append_pass(csv_path, record2)

        result = query_passes(csv_path, artifact_id="artifact-A")

        assert len(result) == 1
        assert result[0]["artifact_id"] == "artifact-A"

    def test_filters_by_entity_id(self, tmp_path: Path) -> None:
        """Should filter passes by entity_id when provided."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        record = PassRecord(
            pass_id="pass-001",
            artifact_id="artifact-1",
            entity_id="target-entity",
            entity_mention="entity",
            span_id="span-1",
            chunk_id="artifact-1:pass1:span-1",
            span_before="before",
            span_after="after",
            facts_removed="[]",
            similarity_score="0.9",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )
        append_pass(csv_path, record)

        result = query_passes(csv_path, entity_id="target-entity")

        assert len(result) == 1
        assert result[0]["entity_id"] == "target-entity"

    def test_returns_all_passes_when_no_filter(self, tmp_path: Path) -> None:
        """Should return all passes when no filters provided."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        for i in range(3):
            record = PassRecord(
                pass_id=f"pass-{i:03d}",
                artifact_id=f"artifact-{i}",
                entity_id=f"entity-{i}",
                entity_mention=f"mention-{i}",
                span_id=f"span-{i}",
                chunk_id=f"artifact-{i}:pass1:span-{i}",
                span_before="before",
                span_after="after",
                facts_removed="[]",
                similarity_score="0.9",
                status="success",
                failure_reason="",
                created_at=f"2024-01-01T00:00:{i:02d}Z",
            )
            append_pass(csv_path, record)

        result = query_passes(csv_path)

        assert len(result) == 3


class TestGetPassById:
    """Tests for get_pass_by_id function."""

    def test_returns_none_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return None when CSV doesn't exist."""
        csv_path = tmp_path / "nonexistent.csv"
        result = get_pass_by_id(csv_path, "pass-001")
        assert result is None

    def test_returns_none_for_nonexistent_pass(self, tmp_path: Path) -> None:
        """Should return None when pass not found."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        record = PassRecord(
            pass_id="existing-pass",
            artifact_id="artifact-1",
            entity_id="entity-1",
            entity_mention="mention",
            span_id="span-1",
            chunk_id="artifact-1:pass1:span-1",
            span_before="before",
            span_after="after",
            facts_removed="[]",
            similarity_score="0.9",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )
        append_pass(csv_path, record)

        result = get_pass_by_id(csv_path, "nonexistent-pass")

        assert result is None

    def test_returns_pass_for_valid_id(self, tmp_path: Path) -> None:
        """Should return pass record when ID found."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        record = PassRecord(
            pass_id="target-pass",
            artifact_id="artifact-123",
            entity_id="entity-456",
            entity_mention="create_app",
            span_id="span-001",
            chunk_id="artifact-123:pass1:span-001",
            span_before="before text",
            span_after="after text",
            facts_removed='["fact1"]',
            similarity_score="0.95",
            status="success",
            failure_reason="",
            created_at="2024-01-01T00:00:00Z",
        )
        append_pass(csv_path, record)

        result = get_pass_by_id(csv_path, "target-pass")

        assert result is not None
        assert result["pass_id"] == "target-pass"
        assert result["artifact_id"] == "artifact-123"


class TestCountPasses:
    """Tests for count_passes function."""

    def test_returns_zero_for_missing_csv(self, tmp_path: Path) -> None:
        """Should return 0 when CSV doesn't exist."""
        csv_path = tmp_path / "nonexistent.csv"
        result = count_passes(csv_path)
        assert result == 0

    def test_returns_zero_for_empty_csv(self, tmp_path: Path) -> None:
        """Should return 0 for empty CSV."""
        csv_path = tmp_path / "passes.csv"
        csv_path.write_text("")
        result = count_passes(csv_path)
        assert result == 0

    def test_counts_all_passes(self, tmp_path: Path) -> None:
        """Should count all passes when no filter."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        for i in range(5):
            record = PassRecord(
                pass_id=f"pass-{i:03d}",
                artifact_id="artifact-1",
                entity_id=f"entity-{i}",
                entity_mention=f"mention-{i}",
                span_id=f"span-{i}",
                chunk_id=f"artifact-1:pass{i + 1}:span-{i}",
                span_before="before",
                span_after="after",
                facts_removed="[]",
                similarity_score="0.9",
                status="success",
                failure_reason="",
                created_at=f"2024-01-01T00:00:{i:02d}Z",
            )
            append_pass(csv_path, record)

        result = count_passes(csv_path)

        assert result == 5

    def test_counts_passes_by_artifact_id(self, tmp_path: Path) -> None:
        """Should count passes filtered by artifact_id."""
        csv_path = tmp_path / "passes.csv"
        ensure_passes_csv_exists(csv_path)

        # Add 3 passes for artifact-A
        for i in range(3):
            record = PassRecord(
                pass_id=f"pass-A-{i:03d}",
                artifact_id="artifact-A",
                entity_id=f"entity-{i}",
                entity_mention=f"mention-{i}",
                span_id=f"span-{i}",
                chunk_id=f"artifact-A:pass{i + 1}:span-{i}",
                span_before="before",
                span_after="after",
                facts_removed="[]",
                similarity_score="0.9",
                status="success",
                failure_reason="",
                created_at=f"2024-01-01T00:00:{i:02d}Z",
            )
            append_pass(csv_path, record)

        # Add 2 passes for artifact-B
        for i in range(2):
            record = PassRecord(
                pass_id=f"pass-B-{i:03d}",
                artifact_id="artifact-B",
                entity_id=f"entity-{i}",
                entity_mention=f"mention-{i}",
                span_id=f"span-{i}",
                chunk_id=f"artifact-B:pass{i + 1}:span-{i}",
                span_before="before",
                span_after="after",
                facts_removed="[]",
                similarity_score="0.9",
                status="success",
                failure_reason="",
                created_at=f"2024-01-01T00:01:{i:02d}Z",
            )
            append_pass(csv_path, record)

        result_a = count_passes(csv_path, artifact_id="artifact-A")
        result_b = count_passes(csv_path, artifact_id="artifact-B")
        result_all = count_passes(csv_path)

        assert result_a == 3
        assert result_b == 2
        assert result_all == 5
