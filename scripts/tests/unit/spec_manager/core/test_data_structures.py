"""Tests for spec_manager.core.data_structures module."""

from datetime import datetime

import pytest
from spec_manager.core.data_structures import (
    STATUS_OPEN,
    STATUS_PENDING,
    ComplianceMetrics,
    ConflictBundle,
    ConflictVariant,
    Gap,
    GapEvidence,
    RemainderQueue,
    StrategyRecord,
    _safe_serialize_details,
    compute_evidence_signature,
)
from spec_manager.core.gaps import Severity


class TestComplianceMetrics:
    """Tests for ComplianceMetrics class."""

    def test_valid_metrics(self):
        """Test that valid metrics in range [0.0, 1.0] are accepted."""
        metrics = ComplianceMetrics(
            format_compliance=0.98,
            annotation_coverage=0.95,
            id_normalization=0.99,
        )
        assert metrics.format_compliance == 0.98
        assert metrics.annotation_coverage == 0.95
        assert metrics.id_normalization == 0.99

    def test_gate_passed_all_above_threshold(self):
        """Test gate_passed returns True when all metrics meet threshold."""
        metrics = ComplianceMetrics(
            format_compliance=0.98,
            annotation_coverage=0.96,
            id_normalization=0.95,
        )
        assert metrics.gate_passed() is True

    def test_gate_failed_one_below_threshold(self):
        """Test gate_passed returns False when any metric is below threshold."""
        metrics = ComplianceMetrics(
            format_compliance=0.98,
            annotation_coverage=0.90,  # Below default 0.95 threshold
            id_normalization=0.99,
        )
        assert metrics.gate_passed() is False

    def test_invalid_metric_above_one(self):
        """Test that metrics above 1.0 raise ValueError."""
        with pytest.raises(ValueError, match="format_compliance must be in range"):
            ComplianceMetrics(
                format_compliance=1.5,
                annotation_coverage=0.95,
                id_normalization=0.99,
            )

    def test_invalid_metric_below_zero(self):
        """Test that metrics below 0.0 raise ValueError."""
        with pytest.raises(ValueError, match="annotation_coverage must be in range"):
            ComplianceMetrics(
                format_compliance=0.98,
                annotation_coverage=-0.1,
                id_normalization=0.99,
            )

    def test_invalid_threshold_above_one(self):
        """Test that threshold above 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="gate_threshold must be in range"):
            ComplianceMetrics(
                format_compliance=0.98,
                annotation_coverage=0.95,
                id_normalization=0.99,
                gate_threshold=1.5,
            )

    def test_boundary_values(self):
        """Test that boundary values 0.0 and 1.0 are accepted."""
        metrics = ComplianceMetrics(
            format_compliance=0.0,
            annotation_coverage=1.0,
            id_normalization=0.5,
        )
        assert metrics.format_compliance == 0.0
        assert metrics.annotation_coverage == 1.0

    def test_to_dict_from_dict_roundtrip(self):
        """Test serialization roundtrip."""
        metrics = ComplianceMetrics(
            format_compliance=0.98,
            annotation_coverage=0.95,
            id_normalization=0.99,
            gate_threshold=0.90,
        )
        data = metrics.to_dict()
        restored = ComplianceMetrics.from_dict(data)
        assert restored.format_compliance == metrics.format_compliance
        assert restored.annotation_coverage == metrics.annotation_coverage
        assert restored.id_normalization == metrics.id_normalization
        assert restored.gate_threshold == metrics.gate_threshold


class TestConflictVariant:
    """Tests for ConflictVariant class."""

    def test_field_naming_clarity(self):
        """Test that variant_id and conflicting_id are distinct and clear."""
        variant = ConflictVariant(
            variant_id="REQ-001-v1",  # Unique variant instance ID
            conflicting_id="REQ-001",  # The shared ID causing conflict
            content="Requirement content",
            source_location="spec.md:10",
            heuristic_score=0.8,
            reasons=["has_annotation"],
        )
        assert variant.variant_id == "REQ-001-v1"
        assert variant.conflicting_id == "REQ-001"

    def test_to_dict_serializes_conflicting_id(self):
        """Test that to_dict uses the new 'conflicting_id' key."""
        variant = ConflictVariant(
            variant_id="REQ-001-v1",
            conflicting_id="REQ-001",
            content="Content",
            source_location="file:1",
            heuristic_score=0.9,
        )
        data = variant.to_dict()
        assert "conflicting_id" in data
        assert data["conflicting_id"] == "REQ-001"
        # Old 'id' key should not be present
        assert "id" not in data or data.get("id") != "REQ-001"

    def test_from_dict_requires_canonical_keys(self):
        """Test that from_dict requires canonical v2.0 key names."""
        # Test with new canonical key
        canonical_data = {
            "variant_id": "REQ-001-v1",
            "conflicting_id": "REQ-001",
            "content": "Content",
            "source_location": "file:1",
            "heuristic_score": 0.9,
        }
        variant = ConflictVariant.from_dict(canonical_data)
        assert variant.conflicting_id == "REQ-001"

        # Test that old key names are not accepted (no backward compatibility)
        old_data = {
            "variant_id": "REQ-001-v1",
            "id": "REQ-001",  # Old key name - not accepted
            "content": "Content",
            "source_location": "file:1",
            "heuristic_score": 0.9,
        }
        with pytest.raises(KeyError):
            ConflictVariant.from_dict(old_data)


class TestConflictBundle:
    """Tests for ConflictBundle class."""

    def test_recommended_variant_id_field(self):
        """Test that recommended_variant_id clearly references a variant_id."""
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            recommended_variant_id="REQ-001-v2",
        )
        assert bundle.recommended_variant_id == "REQ-001-v2"

    def test_rank_variants_sets_recommended_variant_id(self):
        """Test that rank_variants sets recommended_variant_id to highest scored variant."""
        variant1 = ConflictVariant(
            variant_id="REQ-001-v1",
            conflicting_id="REQ-001",
            content="Short",
            source_location="file:1",
            heuristic_score=0.5,
        )
        variant2 = ConflictVariant(
            variant_id="REQ-001-v2",
            conflicting_id="REQ-001",
            content="Longer content with more detail",
            source_location="file:10",
            heuristic_score=0.9,
        )
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            variants=[variant1, variant2],
        )
        bundle.rank_variants()
        assert bundle.recommended_variant_id == "REQ-001-v2"

    def test_to_dict_serializes_recommended_variant_id(self):
        """Test that to_dict uses the new 'recommended_variant_id' key."""
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            recommended_variant_id="REQ-001-v1",
        )
        data = bundle.to_dict()
        assert "recommended_variant_id" in data
        assert data["recommended_variant_id"] == "REQ-001-v1"
        # Old 'recommended_variant' key should not be present
        assert "recommended_variant" not in data

    def test_from_dict_requires_canonical_keys(self):
        """Test that from_dict requires canonical v2.0 key names."""
        # Test with canonical key
        canonical_data = {
            "conflicting_id": "REQ-001",
            "recommended_variant_id": "REQ-001-v1",
        }
        bundle = ConflictBundle.from_dict(canonical_data)
        assert bundle.recommended_variant_id == "REQ-001-v1"

        # Test that old key names are not accepted (no backward compatibility)
        old_data = {
            "conflicting_id": "REQ-001",
            "recommended_variant": "REQ-001-v1",  # Old key name - not accepted
        }
        bundle_old = ConflictBundle.from_dict(old_data)
        # Old key is ignored, should be None
        assert bundle_old.recommended_variant_id is None


class TestRemainderQueue:
    """Tests for RemainderQueue class."""

    def test_stagnation_with_same_content_different_order(self):
        """Test that stagnation is detected even if order changes but content is same."""
        queue = RemainderQueue(stagnation_threshold=2)

        # First update
        queue.update(["item1", "item2", "item3"])
        assert queue.stagnation_count == 0
        assert not queue.is_stagnant

        # Second update - same items, different order
        queue.update(["item3", "item1", "item2"])
        assert queue.stagnation_count == 1
        assert not queue.is_stagnant

        # Third update - same items again
        queue.update(["item2", "item3", "item1"])
        assert queue.stagnation_count == 2
        assert queue.is_stagnant

    def test_no_stagnation_with_different_content_same_length(self):
        """Test that changing items resets stagnation even if length is same."""
        queue = RemainderQueue(stagnation_threshold=2)

        # First update
        queue.update(["item1", "item2", "item3"])
        assert queue.stagnation_count == 0

        # Second update - different items, same length
        queue.update(["item4", "item5", "item6"])
        assert queue.stagnation_count == 0  # Content changed, so reset
        assert not queue.is_stagnant

    def test_progress_when_item_removed(self):
        """Test that removing items indicates progress."""
        queue = RemainderQueue(stagnation_threshold=2)

        # First update
        queue.update(["item1", "item2", "item3"])
        assert queue.stagnation_count == 0

        # Second update - one item removed
        queue.update(["item1", "item2"])
        assert queue.stagnation_count == 0  # Progress was made

    def test_to_dict_includes_content_hash(self):
        """Test that serialization includes content hash."""
        queue = RemainderQueue()
        queue.update(["item1", "item2"])
        data = queue.to_dict()
        assert "last_content_hash" in data
        assert data["last_content_hash"] != ""

    def test_from_dict_deserializes_correctly(self):
        """Test that from_dict deserializes all fields correctly."""
        data = {
            "items": ["item1", "item2"],
            "stagnation_count": 1,
            "stagnation_threshold": 3,
            "last_content_hash": "abc123",
            "last_size": 2,
            "is_stagnant": False,
        }
        queue = RemainderQueue.from_dict(data)
        assert queue.items == ["item1", "item2"]
        assert queue.last_content_hash == "abc123"
        assert queue.last_size == 2
        assert queue.stagnation_count == 1
        assert not queue.is_stagnant

    def test_last_size_set_on_update(self):
        """Test that last_size is set to the length of items on each update."""
        queue = RemainderQueue()
        assert queue.last_size == 0  # Initial state

        queue.update(["item1", "item2", "item3"])
        assert queue.last_size == 3

        queue.update(["item1", "item2"])
        assert queue.last_size == 2

        queue.update([])
        assert queue.last_size == 0

    def test_to_dict_includes_last_size(self):
        """Test that serialization includes last_size."""
        queue = RemainderQueue()
        queue.update(["item1", "item2"])
        data = queue.to_dict()
        assert "last_size" in data
        assert data["last_size"] == 2

    def test_mark_progress_resets_stagnation(self):
        """Test that mark_progress resets stagnation count."""
        queue = RemainderQueue(stagnation_threshold=2)
        queue.update(["item1"])
        queue.update(["item1"])  # Same, stagnation_count = 1
        queue.update(["item1"])  # Same, stagnation_count = 2, is_stagnant = True
        assert queue.is_stagnant

        queue.mark_progress()
        assert queue.stagnation_count == 0
        assert not queue.is_stagnant


class TestComputeEvidenceSignature:
    """Tests for compute_evidence_signature function."""

    def test_empty_evidence_raises_error(self):
        """Test that empty evidence list raises ValueError."""
        with pytest.raises(ValueError, match="empty evidence list"):
            compute_evidence_signature([])

    def test_deterministic_signature(self):
        """Test that same evidence produces same signature."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Invalid ID",
                details={"expected": "P#I#"},
                confidence=0.95,
            )
        ]
        sig1 = compute_evidence_signature(evidence)
        sig2 = compute_evidence_signature(evidence)
        assert sig1 == sig2

    def test_order_independent(self):
        """Test that evidence order does not affect signature."""
        ev1 = GapEvidence(invariant_family="format", description="A")
        ev2 = GapEvidence(invariant_family="coverage", description="B")

        sig1 = compute_evidence_signature([ev1, ev2])
        sig2 = compute_evidence_signature([ev2, ev1])
        assert sig1 == sig2

    def test_fully_deterministic_with_ties(self):
        """Test that signature is deterministic even when primary keys match."""
        # Two evidence items with same family and description but different details
        ev1 = GapEvidence(
            invariant_family="format",
            description="Issue",
            details={"key": "value1"},
            location="file1:10",
        )
        ev2 = GapEvidence(
            invariant_family="format",
            description="Issue",
            details={"key": "value2"},
            location="file2:20",
        )

        # Run multiple times to verify determinism
        signatures = set()
        for _ in range(10):
            sig = compute_evidence_signature([ev1, ev2])
            signatures.add(sig)

        # All signatures should be identical
        assert len(signatures) == 1

    def test_confidence_rounding(self):
        """Test that confidence values are rounded to 2 decimals."""
        ev1 = GapEvidence(invariant_family="format", description="A", confidence=0.951)
        ev2 = GapEvidence(invariant_family="format", description="A", confidence=0.954)

        # Both round to 0.95, so signatures should match
        sig1 = compute_evidence_signature([ev1])
        sig2 = compute_evidence_signature([ev2])
        assert sig1 == sig2

    def test_different_confidence_different_signature(self):
        """Test that significantly different confidence values produce different signatures."""
        ev1 = GapEvidence(invariant_family="format", description="A", confidence=0.90)
        ev2 = GapEvidence(invariant_family="format", description="A", confidence=0.99)

        sig1 = compute_evidence_signature([ev1])
        sig2 = compute_evidence_signature([ev2])
        assert sig1 != sig2

    def test_signature_length(self):
        """Test that signature is 8 characters."""
        evidence = [GapEvidence(invariant_family="format", description="test")]
        sig = compute_evidence_signature(evidence)
        assert len(sig) == 8


class TestSafeSerializeDetails:
    """Tests for _safe_serialize_details helper function."""

    def test_empty_dict(self):
        """Test empty dict returns empty JSON object."""
        assert _safe_serialize_details({}) == "{}"

    def test_json_serializable_types(self):
        """Test normal JSON-serializable types."""
        details = {"key": "value", "number": 42, "flag": True, "items": [1, 2, 3]}
        result = _safe_serialize_details(details)
        assert '"key": "value"' in result
        assert '"number": 42' in result

    def test_non_serializable_datetime(self):
        """Test that datetime objects are converted via isoformat()."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        details = {"timestamp": dt}
        result = _safe_serialize_details(details)
        # Should use isoformat() for deterministic serialization
        assert '"2024-01-15T10:30:00' in result

    def test_non_serializable_path(self):
        """Test that Path objects are converted via str()."""
        from pathlib import Path

        path = Path("/some/absolute/path")
        details = {"location": path}
        result = _safe_serialize_details(details)
        # Should use str() for deterministic serialization
        assert '"/some/absolute/path"' in result

    def test_unsupported_type_raises_error(self):
        """Test that unsupported types raise ValueError."""
        class CustomObject:
            pass

        details = {"custom": CustomObject()}
        with pytest.raises(ValueError, match="Unsupported type.*CustomObject"):
            _safe_serialize_details(details)

    def test_nested_non_serializable(self):
        """Test nested structures with non-serializable values."""
        details = {
            "outer": {
                "inner": datetime(2024, 1, 1),
            }
        }
        result = _safe_serialize_details(details)
        # Should serialize datetime in nested structure
        assert '"2024-01-01T00:00:00' in result

    def test_deterministic_key_order(self):
        """Test that keys are always sorted for determinism."""
        details1 = {"z": 1, "a": 2, "m": 3}
        details2 = {"a": 2, "m": 3, "z": 1}
        assert _safe_serialize_details(details1) == _safe_serialize_details(details2)


class TestGapWithNewSignature:
    """Tests for Gap creation with the new signature behavior."""

    def test_gap_creation_with_evidence(self):
        """Test creating a gap with evidence and computed signature."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Invalid ID pattern",
                details={"expected": "P#I#"},
            )
        ]
        sig = compute_evidence_signature(evidence)
        gap = Gap(
            id=f"GAP-{sig}",
            severity=Severity.WARNING,
            evidence=evidence,
            status=STATUS_OPEN,
        )
        assert gap.id.startswith("GAP-")
        assert len(gap.id) == 12  # "GAP-" + 8 char signature
