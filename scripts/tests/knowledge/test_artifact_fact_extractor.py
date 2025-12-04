"""Tests for scripts.knowledge.artifact_fact_extractor module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.knowledge.artifact_fact_extractor import (
    ArtifactExtractionError,
    ExtractionSummary,
    InvariantViolation,
    _assert_localized_rewrites,
    _assert_monotonic_or_handle,
    _assert_non_target_preservation,
    _assert_text_is_state,
    _compute_hash,
    apply_rewrite,
    extract_artifact_facts,
    load_artifact_manifest,
    load_artifact_text,
    parse_args,
    persist_pass,
    resolve_entity,
)
from scripts.knowledge.surgeon_orchestrator import RewriteResult, SpanInput


class TestComputeHash:
    """Tests for _compute_hash function."""

    def test_returns_sha256_hash(self) -> None:
        """Should return SHA256 hash of text."""
        text = "Sample artifact text"

        result = _compute_hash(text)

        assert len(result) == 64  # SHA256 produces 64 hex characters
        assert result.isalnum()

    def test_same_text_same_hash(self) -> None:
        """Should return same hash for same text."""
        text = "Consistent text content"

        hash1 = _compute_hash(text)
        hash2 = _compute_hash(text)

        assert hash1 == hash2

    def test_different_text_different_hash(self) -> None:
        """Should return different hash for different text."""
        text1 = "First text"
        text2 = "Second text"

        hash1 = _compute_hash(text1)
        hash2 = _compute_hash(text2)

        assert hash1 != hash2

    def test_handles_empty_string(self) -> None:
        """Should handle empty string."""
        result = _compute_hash("")

        assert len(result) == 64

    def test_handles_unicode(self) -> None:
        """Should handle unicode characters."""
        text = "Unicode: \u00e9\u00e8\u00ea \u4e2d\u6587"

        result = _compute_hash(text)

        assert len(result) == 64


class TestLoadArtifactManifest:
    """Tests for load_artifact_manifest function."""

    def test_loads_manifest_from_yaml(self, tmp_path: Path) -> None:
        """Should load artifact manifest from YAML file."""
        knowledge_path = tmp_path / ".knowledge"
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest_data = {
            "artifact_id": "artifact-123",
            "inline_text": "Test artifact content",
        }
        manifest_path = artifacts_dir / "artifact-123.yml"
        manifest_path.write_text(yaml.dump(manifest_data), encoding="utf-8")

        result = load_artifact_manifest("artifact-123", knowledge_path)

        assert result["artifact_id"] == "artifact-123"
        assert result["inline_text"] == "Test artifact content"

    def test_raises_error_for_missing_manifest(self, tmp_path: Path) -> None:
        """Should raise ArtifactExtractionError when manifest not found."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "artifacts").mkdir(parents=True)

        with pytest.raises(ArtifactExtractionError, match="not found"):
            load_artifact_manifest("nonexistent", knowledge_path)

    def test_raises_error_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ArtifactExtractionError for invalid YAML."""
        knowledge_path = tmp_path / ".knowledge"
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest_path = artifacts_dir / "invalid.yml"
        manifest_path.write_text("{ invalid: yaml: content", encoding="utf-8")

        with pytest.raises(ArtifactExtractionError, match="Failed to parse"):
            load_artifact_manifest("invalid", knowledge_path)


class TestLoadArtifactText:
    """Tests for load_artifact_text function."""

    def test_loads_inline_text(self, tmp_path: Path) -> None:
        """Should load inline text from manifest."""
        manifest = {"inline_text": "Test artifact content"}

        result = load_artifact_text(manifest, tmp_path)

        assert result == "Test artifact content"

    def test_loads_from_source_file(self, tmp_path: Path) -> None:
        """Should load text from source file."""
        source_file = tmp_path / "source.txt"
        source_file.write_text("Content from source file", encoding="utf-8")

        manifest = {"source_file": str(source_file)}

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            result = load_artifact_text(manifest, tmp_path)

        assert result == "Content from source file"

    def test_raises_error_for_missing_source(self, tmp_path: Path) -> None:
        """Should raise ArtifactExtractionError for missing source file."""
        manifest = {"source_file": "nonexistent.txt"}

        with patch("scripts.knowledge.artifact_fact_extractor.REPO_ROOT", tmp_path):
            with pytest.raises(ArtifactExtractionError, match="Source file not found"):
                load_artifact_text(manifest, tmp_path)

    def test_raises_error_when_no_text_source(self, tmp_path: Path) -> None:
        """Should raise ArtifactExtractionError when no text source."""
        manifest = {"artifact_id": "test"}  # No inline_text or source_file

        with pytest.raises(ArtifactExtractionError, match="must contain"):
            load_artifact_text(manifest, tmp_path)


class TestAssertTextIsState:
    """Tests for _assert_text_is_state function."""

    def test_passes_for_valid_state(self) -> None:
        """Should not raise for non-None state."""
        _assert_text_is_state("Valid state text")  # Should not raise

    def test_raises_for_none_state(self) -> None:
        """Should raise InvariantViolation for None state."""
        with pytest.raises(InvariantViolation, match="cannot be None"):
            _assert_text_is_state(None)  # type: ignore[arg-type]


class TestAssertMonotonicOrHandle:
    """Tests for _assert_monotonic_or_handle function."""

    def test_returns_false_when_text_shrinks(self) -> None:
        """Should return False when text is monotonically shrinking."""
        result = _assert_monotonic_or_handle(
            old_len=100,
            new_len=50,
            state_hash="new_hash",
            seen_hashes=set(),
        )

        assert result is False  # Not a no-op

    def test_returns_false_when_text_same_length(self) -> None:
        """Should return False when text same length (new hash)."""
        result = _assert_monotonic_or_handle(
            old_len=100,
            new_len=100,
            state_hash="new_hash",
            seen_hashes=set(),
        )

        assert result is False  # Not a no-op

    def test_returns_true_when_hash_repeated(self) -> None:
        """Should return True (no-op) when hash seen before."""
        seen_hashes = {"old_hash", "another_hash"}

        result = _assert_monotonic_or_handle(
            old_len=100,
            new_len=90,
            state_hash="old_hash",  # Seen before
            seen_hashes=seen_hashes,
        )

        assert result is True  # No-op detected

    def test_raises_when_text_grows(self) -> None:
        """Should raise InvariantViolation when text grows."""
        with pytest.raises(InvariantViolation, match="length increased"):
            _assert_monotonic_or_handle(
                old_len=50,
                new_len=100,  # Increased
                state_hash="new_hash",
                seen_hashes=set(),
            )


class TestAssertLocalizedRewrites:
    """Tests for _assert_localized_rewrites function."""

    def test_passes_when_changes_localized(self) -> None:
        """Should not raise when changes are within target spans."""
        original_text = "The create_app function is defined in factory.py."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="The create_app function",
                target_facts=[],
                anchor_facts=[],
            )
        ]
        rewrites = [
            RewriteResult(
                span_id="span_1",
                replacement_text="The function",
                validation={},
                review=None,
                success=True,
            )
        ]

        # Should not raise
        _assert_localized_rewrites(original_text, rewrites, spans)

    def test_raises_for_unknown_span_id(self) -> None:
        """Should raise InvariantViolation for unknown span ID."""
        original_text = "Some text."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Some",
                target_facts=[],
                anchor_facts=[],
            )
        ]
        rewrites = [
            RewriteResult(
                span_id="unknown_span",  # Not in spans
                replacement_text="New",
                validation={},
                review=None,
                success=True,
            )
        ]

        with pytest.raises(InvariantViolation, match="unknown span"):
            _assert_localized_rewrites(original_text, rewrites, spans)


class TestAssertNonTargetPreservation:
    """Tests for _assert_non_target_preservation function."""

    def test_passes_when_non_targets_preserved(self) -> None:
        """Should not raise when non-target content is preserved."""
        original_text = "Target sentence. Non-target sentence. Another non-target."
        new_text = "Modified target. Non-target sentence. Another non-target."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Target sentence",
                target_facts=[],
                anchor_facts=[],
            )
        ]
        rewrites = []

        # Should not raise
        _assert_non_target_preservation(original_text, new_text, spans, rewrites)

    def test_raises_when_non_targets_removed(self) -> None:
        """Should raise InvariantViolation when non-target removed."""
        original_text = "Target sentence. Important non-target sentence. Another non-target sentence. Third non-target."
        new_text = "Target sentence."  # All non-targets removed
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Target sentence",
                target_facts=[],
                anchor_facts=[],
            )
        ]
        rewrites = []

        with pytest.raises(InvariantViolation, match="non-target-preservation"):
            _assert_non_target_preservation(original_text, new_text, spans, rewrites)


class TestApplyRewrite:
    """Tests for apply_rewrite function."""

    def test_replaces_span_text(self) -> None:
        """Should replace span text in state."""
        state_text = "The create_app function initializes the app."
        span = SpanInput(
            span_id="span_1",
            original_text="create_app function",
            target_facts=[],
            anchor_facts=[],
        )

        result = apply_rewrite(state_text, span, "function")

        assert result == "The function initializes the app."

    def test_returns_unchanged_when_span_not_found(self) -> None:
        """Should return unchanged text when span not in state."""
        state_text = "Some other text."
        span = SpanInput(
            span_id="span_1",
            original_text="nonexistent",
            target_facts=[],
            anchor_facts=[],
        )

        result = apply_rewrite(state_text, span, "replacement")

        assert result == state_text


class TestResolveEntity:
    """Tests for resolve_entity function."""

    def test_returns_mention_passthrough(self, tmp_path: Path) -> None:
        """Should return entity mention (pass-through until Task 9)."""
        result = resolve_entity("create_app", "artifact_123", tmp_path)

        assert result == "create_app"


class TestPersistPass:
    """Tests for persist_pass function."""

    def test_creates_pass_record(self, tmp_path: Path) -> None:
        """Should create pass record in CSV."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)

        span = SpanInput(
            span_id="span_1",
            original_text="Original text",
            target_facts=["fact1"],
            anchor_facts=[],
        )

        persist_pass(
            pass_id="pass_001",
            artifact_id="artifact_123",
            entity_id="entity_1",
            entity_mention="create_app",
            span=span,
            facts_removed=["fact1"],
            replacement_text="New text",
            state_hash_before="hash_before",
            state_hash_after="hash_after",
            similarity_score=0.75,
            status="success",
            knowledge_path=knowledge_path,
        )

        csv_path = knowledge_path / "facts" / "passes.csv"
        assert csv_path.exists()


class TestExtractArtifactFacts:
    """Tests for extract_artifact_facts function."""

    def test_returns_extraction_summary(self, tmp_path: Path) -> None:
        """Should return ExtractionSummary structure."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        # Create artifact manifest
        manifest = {"artifact_id": "artifact-123", "inline_text": "Test artifact text."}
        manifest_path = artifacts_dir / "artifact-123.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        result = extract_artifact_facts(
            "artifact-123",
            knowledge_path,
            use_mock=True,
        )

        assert "artifact_id" in result
        assert "total_passes" in result
        assert "total_facts_extracted" in result
        assert "final_state_hash" in result
        assert "audit_result" in result

    def test_handles_empty_artifact(self, tmp_path: Path) -> None:
        """Should handle empty artifact text gracefully."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {"artifact_id": "empty-artifact", "inline_text": ""}
        manifest_path = artifacts_dir / "empty-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        result = extract_artifact_facts(
            "empty-artifact",
            knowledge_path,
            use_mock=True,
        )

        assert result["total_facts_extracted"] == 0

    def test_full_loop_with_mock(self, tmp_path: Path) -> None:
        """Should complete full extraction loop with mock agents."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "test-artifact",
            "inline_text": "The create_app function initializes the FastAPI application.",
        }
        manifest_path = artifacts_dir / "test-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        result = extract_artifact_facts(
            "test-artifact",
            knowledge_path,
            use_mock=True,
            max_iterations=5,
        )

        assert result["artifact_id"] == "test-artifact"
        assert result["total_passes"] >= 0

    def test_no_op_detection(self, tmp_path: Path) -> None:
        """Should detect no-op and break loop."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        # Create artifact that will result in no-op after first pass
        manifest = {
            "artifact_id": "no-op-artifact",
            "inline_text": "Static text with no entities.",
        }
        manifest_path = artifacts_dir / "no-op-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        result = extract_artifact_facts(
            "no-op-artifact",
            knowledge_path,
            use_mock=True,
            max_iterations=10,
        )

        # Should complete without hitting max_iterations
        assert result["total_passes"] < 10

    def test_max_iterations_limit(self, tmp_path: Path) -> None:
        """Should stop at max iterations."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {
            "artifact_id": "test-artifact",
            "inline_text": "The create_app function creates applications.",
        }
        manifest_path = artifacts_dir / "test-artifact.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        with patch("scripts.knowledge.artifact_fact_extractor.invoke_hunter_mock") as mock_hunter:
            # Hunter never signals done
            mock_hunter.return_value = {
                "mode": "entities",
                "entities": [
                    {"mention": "test", "type_hint": "IDENTIFIER", "evidence_span_id": "s1"}
                ],
                "target_entity": None,
                "facts": [],
                "spans": [],
                "done": False,
                "reason": None,
            }

            result = extract_artifact_facts(
                "test-artifact",
                knowledge_path,
                use_mock=True,
                max_iterations=3,
            )

        # Should hit the stuck_reason for max_iterations
        assert result["audit_result"].get("recommended_action") is not None


class TestDesignInvariants:
    """Tests for design invariant assertions."""

    def test_assert_text_is_state_none_raises(self) -> None:
        """Should raise InvariantViolation when state is None."""
        with pytest.raises(InvariantViolation, match="cannot be None"):
            _assert_text_is_state(None)  # type: ignore[arg-type]

    def test_assert_monotonic_or_handle_increase_raises(self) -> None:
        """Should raise InvariantViolation when length increases."""
        with pytest.raises(InvariantViolation, match="length increased"):
            _assert_monotonic_or_handle(
                old_len=50,
                new_len=100,
                state_hash="new_hash",
                seen_hashes=set(),
            )

    def test_assert_localized_rewrites_outside_spans_raises(self) -> None:
        """Should raise InvariantViolation for changes outside spans."""
        original_text = "Start. Target span here. End."
        new_text = "Modified start. Target span here. End."
        spans = [
            SpanInput(
                span_id="span_1",
                original_text="Target span here",
                target_facts=[],
                anchor_facts=[],
            )
        ]
        rewrites = [
            RewriteResult(
                span_id="span_1",
                replacement_text="Target span here",
                validation={},
                review=None,
                success=True,
            )
        ]

        with pytest.raises(InvariantViolation, match="outside all targeted spans"):
            _assert_localized_rewrites(original_text, rewrites, spans, new_text)

    def test_assert_non_target_preservation_reverts(self) -> None:
        """Should raise when non-target sentences are lost."""
        original = "Sentence A. Sentence B. Sentence C. Sentence D."
        new_text = "Sentence A."  # B, C, D removed
        spans = [
            SpanInput(
                span_id="s1",
                original_text="Sentence A",
                target_facts=[],
                anchor_facts=[],
            )
        ]

        with pytest.raises(InvariantViolation, match="non-target-preservation"):
            _assert_non_target_preservation(original, new_text, spans, [])


class TestParseArgs:
    """Tests for parse_args function."""

    def test_required_artifact_id(self) -> None:
        """Should require artifact-id argument."""
        args = parse_args(["--artifact-id", "artifact-123"])

        assert args.artifact_id == "artifact-123"

    def test_default_knowledge_path(self) -> None:
        """Should use default knowledge path."""
        args = parse_args(["--artifact-id", "test"])

        assert args.knowledge_path == Path(".knowledge")

    def test_custom_knowledge_path(self) -> None:
        """Should accept custom knowledge path."""
        args = parse_args(
            [
                "--artifact-id",
                "test",
                "--knowledge-path",
                "custom/.knowledge",
            ]
        )

        assert args.knowledge_path == Path("custom/.knowledge")

    def test_max_iterations_option(self) -> None:
        """Should accept max-iterations option."""
        args = parse_args(
            [
                "--artifact-id",
                "test",
                "--max-iterations",
                "50",
            ]
        )

        assert args.max_iterations == 50

    def test_mock_flag(self) -> None:
        """Should accept mock flag."""
        args = parse_args(
            [
                "--artifact-id",
                "test",
                "--mock",
            ]
        )

        assert args.mock is True


class TestExtractionSummaryTypedDict:
    """Tests for ExtractionSummary TypedDict structure."""

    def test_valid_extraction_summary(self) -> None:
        """Should accept valid ExtractionSummary structure."""
        result: ExtractionSummary = {
            "artifact_id": "artifact-123",
            "total_passes": 5,
            "total_facts_extracted": 15,
            "final_state_hash": "abc123def456",
            "audit_result": {
                "has_remaining_facts": False,
                "recommended_action": "complete",
            },
        }

        assert result["artifact_id"] == "artifact-123"
        assert result["total_facts_extracted"] == 15
        assert result["audit_result"]["recommended_action"] == "complete"

    def test_extraction_summary_with_stuck(self) -> None:
        """Should accept ExtractionSummary with stuck audit result."""
        result: ExtractionSummary = {
            "artifact_id": "artifact-456",
            "total_passes": 10,
            "total_facts_extracted": 3,
            "final_state_hash": "def456",
            "audit_result": {
                "has_remaining_facts": True,
                "recommended_action": "escalate",
                "notes": "Max iterations reached",
            },
        }

        assert result["audit_result"]["has_remaining_facts"] is True


class TestPersistPassAndAuditWrites:
    """Tests for persist_pass and audit writing."""

    def test_persist_pass_writes_csv(self, tmp_path: Path) -> None:
        """Should write pass record to CSV."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)

        span = SpanInput(
            span_id="span_1",
            original_text="Original",
            target_facts=["fact1"],
            anchor_facts=[],
        )

        persist_pass(
            pass_id="pass_001",
            artifact_id="artifact_123",
            entity_id="entity_1",
            entity_mention="test",
            span=span,
            facts_removed=["fact1"],
            replacement_text="New",
            state_hash_before="before",
            state_hash_after="after",
            similarity_score=0.8,
            status="success",
            knowledge_path=knowledge_path,
        )

        csv_path = knowledge_path / "facts" / "passes.csv"
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "pass_001" in content

    def test_audit_writes_json(self, tmp_path: Path) -> None:
        """Should write audit report as JSON."""
        knowledge_path = tmp_path / ".knowledge"
        (knowledge_path / "facts").mkdir(parents=True)
        (knowledge_path / "facts" / "residue").mkdir(parents=True)
        artifacts_dir = knowledge_path / "artifacts"
        artifacts_dir.mkdir(parents=True)

        manifest = {"artifact_id": "audit-test", "inline_text": "Test."}
        manifest_path = artifacts_dir / "audit-test.yml"
        manifest_path.write_text(yaml.dump(manifest), encoding="utf-8")

        result = extract_artifact_facts(
            "audit-test",
            knowledge_path,
            use_mock=True,
        )

        audit_file = knowledge_path / "facts" / "residue" / "audit-test.audit.json"
        assert audit_file.exists()
