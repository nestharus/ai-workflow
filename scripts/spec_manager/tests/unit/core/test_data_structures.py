"""Tests for spec_manager.core.data_structures module.

Comprehensive test coverage for:
- ComplianceMetrics: Quality gate metrics with validation
- ConflictVariant/ConflictBundle: Conflict resolution structures
- GapEvidence: Evidence supporting gap identification
- Gap: First-class gap element with evidence-based ID
- RemainderQueue: Queue with stagnation detection
- StrategyRecord: Strategy execution records
- compute_evidence_signature: Stable signature computation
"""

from datetime import datetime
from pathlib import Path

import pytest
from spec_manager.core.data_structures import (
    STATUS_AUTO_RESOLVED,
    STATUS_BYPASSED,
    STATUS_DEFERRED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_MANUAL_REQUIRED,
    STATUS_OPEN,
    STATUS_PASSED,
    STATUS_PENDING,
    STATUS_RESOLVED,
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
        """Test that id field is used for variant identification."""
        variant = ConflictVariant(
            id="REQ-001-v1",  # Unique variant instance ID
            content="Requirement content",
            source_location="spec.md:10",
            heuristic_score=0.8,
            reasons=["has_annotation"],
        )
        assert variant.id == "REQ-001-v1"

    def test_to_dict_serializes_id(self):
        """Test that to_dict uses the 'id' key."""
        variant = ConflictVariant(
            id="REQ-001-v1",
            content="Content",
            source_location="file:1",
            heuristic_score=0.9,
        )
        data = variant.to_dict()
        assert "id" in data
        assert data["id"] == "REQ-001-v1"

    def test_from_dict_requires_canonical_keys(self):
        """Test that from_dict requires canonical v2.0 key names."""
        # Test with canonical key
        canonical_data = {
            "id": "REQ-001-v1",
            "content": "Content",
            "source_location": "file:1",
            "heuristic_score": 0.9,
        }
        variant = ConflictVariant.from_dict(canonical_data)
        assert variant.id == "REQ-001-v1"

        # Test that old key names are not accepted (no backward compatibility)
        old_data = {
            "variant_id": "REQ-001-v1",  # Old key name - not accepted
            "content": "Content",
            "source_location": "file:1",
            "heuristic_score": 0.9,
        }
        with pytest.raises(KeyError):
            ConflictVariant.from_dict(old_data)


class TestConflictBundle:
    """Tests for ConflictBundle class."""

    def test_recommended_variant_field(self):
        """Test that recommended_variant clearly references a variant id."""
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            recommended_variant="REQ-001-v2",
        )
        assert bundle.recommended_variant == "REQ-001-v2"

    def test_rank_variants_with_empty_variants_list(self):
        """Test that rank_variants handles empty variants list correctly."""
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            variants=[],
            recommended_variant="old-value",  # Should be cleared
        )
        bundle.rank_variants()
        assert bundle.recommended_variant is None
        assert bundle.variants == []

    def test_rank_variants_sets_recommended_variant(self):
        """Test that rank_variants sets recommended_variant to highest scored variant."""
        variant1 = ConflictVariant(
            id="REQ-001-v1",
            content="Short",
            source_location="file:1",
            heuristic_score=0.5,
        )
        variant2 = ConflictVariant(
            id="REQ-001-v2",
            content="Longer content with more detail",
            source_location="file:10",
            heuristic_score=0.9,
        )
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            variants=[variant1, variant2],
        )
        bundle.rank_variants()
        assert bundle.recommended_variant == "REQ-001-v2"

    def test_to_dict_serializes_recommended_variant(self):
        """Test that to_dict uses the 'recommended_variant' key."""
        bundle = ConflictBundle(
            conflicting_id="REQ-001",
            recommended_variant="REQ-001-v1",
        )
        data = bundle.to_dict()
        assert "recommended_variant" in data
        assert data["recommended_variant"] == "REQ-001-v1"

    def test_from_dict_requires_canonical_keys(self):
        """Test that from_dict requires canonical v2.0 key names."""
        # Test with canonical key
        canonical_data = {
            "conflicting_id": "REQ-001",
            "recommended_variant": "REQ-001-v1",
        }
        bundle = ConflictBundle.from_dict(canonical_data)
        assert bundle.recommended_variant == "REQ-001-v1"

        # Test that old key names are not accepted (no backward compatibility)
        old_data = {
            "conflicting_id": "REQ-001",
            "recommended_variant_id": "REQ-001-v1",  # Old key name - not accepted
        }
        bundle_old = ConflictBundle.from_dict(old_data)
        # Old key is ignored, should be None
        assert bundle_old.recommended_variant is None


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


class TestGapEvidence:
    """Comprehensive tests for GapEvidence class."""

    def test_basic_creation(self):
        """Test basic GapEvidence creation with required fields."""
        evidence = GapEvidence(
            invariant_family="format",
            description="Invalid ID pattern",
        )
        assert evidence.invariant_family == "format"
        assert evidence.description == "Invalid ID pattern"
        assert evidence.details == {}
        assert evidence.confidence == 1.0
        assert evidence.location is None
        assert evidence.detector is None

    def test_creation_with_all_fields(self):
        """Test GapEvidence creation with all optional fields."""
        evidence = GapEvidence(
            invariant_family="coverage",
            description="Missing annotation",
            details={"expected": "SHALL", "found": None},
            confidence=0.85,
            location="spec.md:42",
            detector="annotation_detector",
        )
        assert evidence.invariant_family == "coverage"
        assert evidence.confidence == 0.85
        assert evidence.location == "spec.md:42"
        assert evidence.detector == "annotation_detector"
        assert evidence.details["expected"] == "SHALL"

    def test_serialization_roundtrip(self):
        """Test that to_dict/from_dict preserves all fields."""
        original = GapEvidence(
            invariant_family="sequence",
            description="Out of order",
            details={"position": 3, "expected": 2},
            confidence=0.92,
            location="file.md:100",
            detector="sequence_detector",
        )
        data = original.to_dict()
        restored = GapEvidence.from_dict(data)

        assert restored.invariant_family == original.invariant_family
        assert restored.description == original.description
        assert restored.details == original.details
        assert restored.confidence == original.confidence
        assert restored.location == original.location
        assert restored.detector == original.detector

    def test_serialization_with_path_objects(self):
        """Test that Path objects in details are converted to strings."""
        test_path = Path("/some/file/path.md")
        evidence = GapEvidence(
            invariant_family="format",
            description="File path issue",
            details={"path": test_path},
        )
        data = evidence.to_dict()
        assert data["details"]["path"] == str(test_path)
        assert isinstance(data["details"]["path"], str)

    def test_serialization_with_datetime_objects(self):
        """Test that datetime objects in details are converted to ISO format."""
        dt = datetime(2024, 6, 15, 14, 30, 45)
        evidence = GapEvidence(
            invariant_family="format",
            description="Timestamp issue",
            details={"timestamp": dt},
        )
        data = evidence.to_dict()
        assert data["details"]["timestamp"] == "2024-06-15T14:30:45"

    def test_serialization_with_nested_structures(self):
        """Test nested dicts/lists with Path/datetime are properly serialized."""
        inner_path = Path("/nested/path")
        list_path = Path("/list/path")
        evidence = GapEvidence(
            invariant_family="format",
            description="Complex details",
            details={
                "outer": {
                    "inner_path": inner_path,
                    "inner_time": datetime(2024, 1, 1),
                    "list_data": [list_path, "string"],
                }
            },
        )
        data = evidence.to_dict()
        assert data["details"]["outer"]["inner_path"] == str(inner_path)
        assert data["details"]["outer"]["inner_time"] == "2024-01-01T00:00:00"
        assert data["details"]["outer"]["list_data"][0] == str(list_path)

    def test_serialization_with_unsupported_types_raises_error(self):
        """Test that custom objects in details raise ValueError."""

        class CustomClass:
            pass

        evidence = GapEvidence(
            invariant_family="format",
            description="Custom object",
            details={"custom": CustomClass()},
        )
        with pytest.raises(ValueError, match="Unsupported type.*CustomClass"):
            evidence.to_dict()

    def test_empty_details_dict(self):
        """Test that empty details dict is handled correctly."""
        evidence = GapEvidence(
            invariant_family="format",
            description="No details",
            details={},
        )
        data = evidence.to_dict()
        assert data["details"] == {}

        restored = GapEvidence.from_dict(data)
        assert restored.details == {}

    def test_from_dict_with_missing_optional_fields(self):
        """Test deserialization handles missing optional fields."""
        data = {
            "invariant_family": "format",
            "description": "Minimal data",
        }
        evidence = GapEvidence.from_dict(data)
        assert evidence.details == {}
        assert evidence.confidence == 1.0
        assert evidence.location is None
        assert evidence.detector is None


class TestGap:
    """Comprehensive tests for Gap class."""

    def test_gap_creation_with_evidence_list(self):
        """Test Gap can be created with evidence list."""
        evidence = [
            GapEvidence(invariant_family="format", description="Issue 1"),
            GapEvidence(invariant_family="coverage", description="Issue 2"),
        ]
        gap = Gap(
            id="GAP-test123",
            severity=Severity.WARNING,
            evidence=evidence,
        )
        assert gap.id == "GAP-test123"
        assert len(gap.evidence) == 2
        assert gap.severity == Severity.WARNING

    def test_serialization_roundtrip(self):
        """Test that to_dict/from_dict preserves all fields."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Invalid pattern",
                details={"key": "value"},
                confidence=0.9,
            )
        ]
        original = Gap(
            id="GAP-abc12345",
            severity=Severity.ERROR,
            evidence=evidence,
            status=STATUS_RESOLVED,
            affected_elements=["REQ-001", "REQ-002"],
            created_at="2024-06-15T10:30:00",
            resolved_at="2024-06-16T14:00:00",
            resolution_notes="Fixed by updating format",
        )

        data = original.to_dict()
        restored = Gap.from_dict(data)

        assert restored.id == original.id
        assert restored.severity == original.severity
        assert len(restored.evidence) == len(original.evidence)
        assert restored.evidence[0].invariant_family == "format"
        assert restored.status == original.status
        assert restored.affected_elements == original.affected_elements
        assert restored.created_at == original.created_at
        assert restored.resolved_at == original.resolved_at
        assert restored.resolution_notes == original.resolution_notes

    def test_severity_serialization(self):
        """Test Severity enum is serialized as string and deserialized correctly."""
        gap = Gap(
            id="GAP-sev12345",
            severity=Severity.ERROR,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
        )
        data = gap.to_dict()
        assert data["severity"] == "error"  # Enum value string

        restored = Gap.from_dict(data)
        assert restored.severity == Severity.ERROR

    @pytest.mark.parametrize(
        "status",
        [
            STATUS_OPEN,
            STATUS_RESOLVED,
            STATUS_BYPASSED,
            STATUS_DEFERRED,
        ],
    )
    def test_valid_status_values(self, status):
        """Test Gap accepts valid status values."""
        gap = Gap(
            id="GAP-status12",
            severity=Severity.WARNING,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
            status=status,
        )
        assert gap.status == status

        data = gap.to_dict()
        restored = Gap.from_dict(data)
        assert restored.status == status

    def test_affected_elements_list(self):
        """Test affected_elements list is properly serialized/deserialized."""
        elements = ["REQ-001", "REQ-002", "REQ-003"]
        gap = Gap(
            id="GAP-elem1234",
            severity=Severity.INFO,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
            affected_elements=elements,
        )
        data = gap.to_dict()
        assert data["affected_elements"] == elements

        restored = Gap.from_dict(data)
        assert restored.affected_elements == elements

    def test_timestamps_auto_generated(self):
        """Test created_at is auto-generated and resolved_at defaults to None."""
        gap = Gap(
            id="GAP-time1234",
            severity=Severity.WARNING,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
        )
        assert gap.created_at is not None
        assert "T" in gap.created_at  # ISO format check
        assert gap.resolved_at is None

    def test_resolution_notes_optional(self):
        """Test resolution_notes field is optional and serialized correctly."""
        gap_without = Gap(
            id="GAP-note1234",
            severity=Severity.WARNING,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
        )
        assert gap_without.resolution_notes is None

        gap_with = Gap(
            id="GAP-note5678",
            severity=Severity.WARNING,
            evidence=[GapEvidence(invariant_family="format", description="Test")],
            resolution_notes="Manually resolved by user",
        )
        data = gap_with.to_dict()
        assert data["resolution_notes"] == "Manually resolved by user"

        restored = Gap.from_dict(data)
        assert restored.resolution_notes == "Manually resolved by user"

    def test_empty_evidence_list_deserialization(self):
        """Test Gap can be deserialized with empty evidence list."""
        data = {
            "id": "GAP-empty123",
            "severity": "warning",
            "evidence": [],
            "status": STATUS_OPEN,
        }
        gap = Gap.from_dict(data)
        assert gap.evidence == []

    def test_multiple_evidence_items(self):
        """Test multiple GapEvidence items are properly serialized/deserialized."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Issue 1",
                confidence=0.9,
                location="file1.md:10",
            ),
            GapEvidence(
                invariant_family="coverage",
                description="Issue 2",
                confidence=0.8,
                location="file2.md:20",
            ),
            GapEvidence(
                invariant_family="sequence",
                description="Issue 3",
                confidence=0.95,
                detector="seq_detector",
            ),
        ]
        gap = Gap(
            id="GAP-multi123",
            severity=Severity.ERROR,
            evidence=evidence,
        )

        data = gap.to_dict()
        assert len(data["evidence"]) == 3

        restored = Gap.from_dict(data)
        assert len(restored.evidence) == 3
        assert restored.evidence[0].location == "file1.md:10"
        assert restored.evidence[1].confidence == 0.8
        assert restored.evidence[2].detector == "seq_detector"


class TestStrategyRecord:
    """Comprehensive tests for StrategyRecord class."""

    def test_basic_creation(self):
        """Test basic StrategyRecord creation."""
        record = StrategyRecord(strategy_name="normalize_ids")
        assert record.strategy_name == "normalize_ids"
        assert record.validation_status == STATUS_PENDING
        assert record.validation_errors == []
        assert record.input_unit_ids == []
        assert record.output_unit_ids == []
        assert record.metrics == {}
        assert record.notes is None

    def test_mark_validated_passed(self):
        """Test mark_validated with passed=True sets status and clears errors."""
        record = StrategyRecord(strategy_name="test_strategy")
        record.validation_errors = ["old error"]  # Simulate previous failure
        record.mark_validated(passed=True)

        assert record.validation_status == STATUS_PASSED
        assert record.validation_errors == []

    def test_mark_validated_failed_with_errors(self):
        """Test mark_validated with passed=False sets status and error list."""
        record = StrategyRecord(strategy_name="test_strategy")
        errors = ["Error 1", "Error 2"]
        record.mark_validated(passed=False, errors=errors)

        assert record.validation_status == STATUS_FAILED
        assert record.validation_errors == errors

    def test_mark_validated_clears_stale_errors_on_pass(self):
        """Test passing validation after failure clears previous error list."""
        record = StrategyRecord(strategy_name="test_strategy")
        record.mark_validated(passed=False, errors=["Initial error"])
        assert record.validation_errors == ["Initial error"]

        record.mark_validated(passed=True)
        assert record.validation_status == STATUS_PASSED
        assert record.validation_errors == []

    def test_mark_validated_failed_with_none_errors(self):
        """Test mark_validated(False, None) sets empty error list."""
        record = StrategyRecord(strategy_name="test_strategy")
        record.mark_validated(passed=False, errors=None)

        assert record.validation_status == STATUS_FAILED
        assert record.validation_errors == []

    def test_serialization_roundtrip(self):
        """Test to_dict/from_dict preserves all fields."""
        original = StrategyRecord(
            strategy_name="complex_strategy",
            applied_at="2024-06-15T10:30:00",
            input_unit_ids=["UNIT-001", "UNIT-002"],
            output_unit_ids=["UNIT-003"],
            validation_status=STATUS_PASSED,
            validation_errors=[],
            metrics={"processed": 10, "skipped": 2, "ratio": 0.83},
            notes="Successfully applied strategy",
        )

        data = original.to_dict()
        restored = StrategyRecord.from_dict(data)

        assert restored.strategy_name == original.strategy_name
        assert restored.applied_at == original.applied_at
        assert restored.input_unit_ids == original.input_unit_ids
        assert restored.output_unit_ids == original.output_unit_ids
        assert restored.validation_status == original.validation_status
        assert restored.validation_errors == original.validation_errors
        assert restored.metrics == original.metrics
        assert restored.notes == original.notes

    def test_applied_at_auto_generated(self):
        """Test applied_at is auto-generated with ISO format."""
        record = StrategyRecord(strategy_name="test_strategy")
        assert record.applied_at is not None
        assert "T" in record.applied_at  # ISO format check

    def test_unit_ids_serialization(self):
        """Test input_unit_ids and output_unit_ids are properly serialized."""
        record = StrategyRecord(
            strategy_name="transform",
            input_unit_ids=["IN-001", "IN-002", "IN-003"],
            output_unit_ids=["OUT-001", "OUT-002"],
        )
        data = record.to_dict()
        assert data["input_unit_ids"] == ["IN-001", "IN-002", "IN-003"]
        assert data["output_unit_ids"] == ["OUT-001", "OUT-002"]

    def test_metrics_dict_serialization(self):
        """Test arbitrary metrics dict is properly serialized."""
        record = StrategyRecord(
            strategy_name="analyze",
            metrics={
                "total": 100,
                "processed": 95,
                "success_rate": 0.95,
                "categories": ["A", "B", "C"],
                "nested": {"key": "value"},
            },
        )
        data = record.to_dict()
        assert data["metrics"]["total"] == 100
        assert data["metrics"]["success_rate"] == 0.95
        assert data["metrics"]["nested"]["key"] == "value"

        restored = StrategyRecord.from_dict(data)
        assert restored.metrics == record.metrics

    def test_notes_field_optional(self):
        """Test optional notes field is serialized correctly."""
        record_without = StrategyRecord(strategy_name="no_notes")
        assert record_without.notes is None
        data_without = record_without.to_dict()
        assert data_without["notes"] is None

        record_with = StrategyRecord(strategy_name="with_notes", notes="Important observation")
        data_with = record_with.to_dict()
        assert data_with["notes"] == "Important observation"

        restored = StrategyRecord.from_dict(data_with)
        assert restored.notes == "Important observation"

    def test_default_validation_status_is_pending(self):
        """Test validation_status defaults to STATUS_PENDING."""
        record = StrategyRecord(strategy_name="test")
        assert record.validation_status == STATUS_PENDING

    def test_validation_errors_defaults_to_empty_list(self):
        """Test validation_errors defaults to empty list."""
        record = StrategyRecord(strategy_name="test")
        assert record.validation_errors == []

    def test_validation_state_transitions(self):
        """Test pending -> passed, pending -> failed, failed -> passed transitions."""
        record = StrategyRecord(strategy_name="test")
        assert record.validation_status == STATUS_PENDING

        # pending -> failed
        record.mark_validated(passed=False, errors=["Error occurred"])
        assert record.validation_status == STATUS_FAILED
        assert record.validation_errors == ["Error occurred"]

        # failed -> passed (retry scenario)
        record.mark_validated(passed=True)
        assert record.validation_status == STATUS_PASSED
        assert record.validation_errors == []


class TestDataStructuresIntegration:
    """Edge case and integration tests for data structures."""

    def test_gap_with_gap_evidence_serialization_chain(self):
        """Test Gap with multiple GapEvidence items serialize/deserialize correctly."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Invalid ID",
                details={"expected": "P#I#", "found": "X#"},
                confidence=0.95,
                location="spec.md:10",
                detector="format_detector",
            ),
            GapEvidence(
                invariant_family="coverage",
                description="Missing annotation",
                details={"element": "REQ-001"},
                confidence=0.88,
            ),
        ]
        sig = compute_evidence_signature(evidence)
        gap = Gap(
            id=f"GAP-{sig}",
            severity=Severity.WARNING,
            evidence=evidence,
            status=STATUS_OPEN,
            affected_elements=["REQ-001", "REQ-002"],
        )

        # Serialize and deserialize
        data = gap.to_dict()
        restored = Gap.from_dict(data)

        # Verify integrity
        assert restored.id == gap.id
        assert len(restored.evidence) == 2
        assert restored.evidence[0].invariant_family == "format"
        assert restored.evidence[0].details["expected"] == "P#I#"
        assert restored.evidence[1].confidence == 0.88
        assert restored.affected_elements == ["REQ-001", "REQ-002"]

    def test_conflict_bundle_with_multiple_variants_ranking(self):
        """Test bundle with 5+ variants has deterministic ranking with ties."""
        variants = [
            ConflictVariant(
                id="REQ-001-v1",
                content="Short",
                source_location="file:1",
                heuristic_score=0.5,
            ),
            ConflictVariant(
                id="REQ-001-v2",
                content="Medium length content",
                source_location="file:2",
                heuristic_score=0.8,
            ),
            ConflictVariant(
                id="REQ-001-v3",
                content="Tied score A",
                source_location="file:3",
                heuristic_score=0.9,  # Tie with v4
            ),
            ConflictVariant(
                id="REQ-001-v4",
                content="Tied score B",
                source_location="file:4",
                heuristic_score=0.9,  # Tie with v3
            ),
            ConflictVariant(
                id="REQ-001-v5",
                content="Low score",
                source_location="file:5",
                heuristic_score=0.3,
            ),
        ]

        bundle = ConflictBundle(conflicting_id="REQ-001", variants=variants)
        bundle.rank_variants()

        # Should be deterministic - v3 comes before v4 alphabetically
        assert bundle.recommended_variant == "REQ-001-v3"

        # Run multiple times to verify determinism
        for _ in range(10):
            bundle_copy = ConflictBundle(conflicting_id="REQ-001", variants=variants.copy())
            bundle_copy.rank_variants()
            assert bundle_copy.recommended_variant == "REQ-001-v3"

    def test_remainder_queue_duplicate_detection(self):
        """Test duplicate items in queue are handled correctly."""
        queue = RemainderQueue(stagnation_threshold=2)

        # Items with duplicates - set-based comparison should deduplicate
        queue.update(["item1", "item2", "item2", "item3"])
        first_hash = queue.last_content_hash

        # Same unique items, different duplicates
        queue.update(["item1", "item1", "item2", "item3"])
        second_hash = queue.last_content_hash

        # Hashes should match since unique content is the same
        assert first_hash == second_hash
        assert queue.stagnation_count == 1  # Content unchanged

    def test_compute_evidence_signature_with_complex_details(self):
        """Test signature stability with nested Path/datetime in evidence details."""
        evidence = [
            GapEvidence(
                invariant_family="format",
                description="Complex details",
                details={
                    "path": Path("/test/file.md"),
                    "timestamp": datetime(2024, 6, 15, 10, 30),
                    "nested": {
                        "inner_path": Path("/inner/path"),
                        "values": [1, 2, 3],
                    },
                },
            )
        ]

        # Run multiple times to verify determinism
        signatures = {compute_evidence_signature(evidence) for _ in range(10)}
        assert len(signatures) == 1  # All should be identical

    def test_all_status_constants_are_valid_strings(self):
        """Test all STATUS_* constants are non-empty strings."""
        statuses = [
            STATUS_PENDING,
            STATUS_OPEN,
            STATUS_RESOLVED,
            STATUS_BYPASSED,
            STATUS_DEFERRED,
            STATUS_PASSED,
            STATUS_FAILED,
            STATUS_AUTO_RESOLVED,
            STATUS_MANUAL_REQUIRED,
            STATUS_IN_PROGRESS,
        ]
        for status in statuses:
            assert isinstance(status, str)
            assert len(status) > 0

    @pytest.mark.parametrize(
        "threshold,format_val,annotation_val,id_val,expected",
        [
            (0.0, 0.0, 0.0, 0.0, True),  # Zero threshold, zero values
            (0.5, 0.6, 0.7, 0.8, True),  # All above 0.5
            (0.5, 0.4, 0.7, 0.8, False),  # One below threshold
            (1.0, 1.0, 1.0, 1.0, True),  # Perfect scores
            (1.0, 0.99, 1.0, 1.0, False),  # Almost perfect fails
            (0.95, 0.95, 0.95, 0.95, True),  # Exactly at threshold
        ],
    )
    def test_compliance_metrics_custom_threshold(
        self, threshold, format_val, annotation_val, id_val, expected
    ):
        """Test gate_passed logic with various threshold values."""
        metrics = ComplianceMetrics(
            format_compliance=format_val,
            annotation_coverage=annotation_val,
            id_normalization=id_val,
            gate_threshold=threshold,
        )
        assert metrics.gate_passed() is expected

    @pytest.mark.parametrize(
        "confidence,rounded",
        [
            # Values that round to 0.94
            (0.9401, 0.94),
            (0.9449, 0.94),
            # Values that round to 0.95
            (0.9451, 0.95),
            (0.9499, 0.95),
            # Values that round to 0.96
            (0.9551, 0.96),
            (0.9599, 0.96),
        ],
    )
    def test_gap_evidence_confidence_rounding_in_signature(self, confidence, rounded):
        """Test confidence values near boundaries produce expected signatures.

        Note: Python's round() uses banker's rounding and has floating-point
        precision nuances. We test values that are safely within rounding ranges
        rather than exact boundary values like 0.945 or 0.955.
        """
        # Create evidence with specific confidence
        ev = GapEvidence(invariant_family="format", description="Test", confidence=confidence)

        # Create equivalent evidence with pre-rounded confidence
        ev_rounded = GapEvidence(invariant_family="format", description="Test", confidence=rounded)

        sig1 = compute_evidence_signature([ev])
        sig2 = compute_evidence_signature([ev_rounded])

        # Signatures should match due to rounding in signature computation
        assert sig1 == sig2


@pytest.mark.slow
class TestDataStructuresPerformance:
    """Performance and stress tests for data structures."""

    def test_compute_evidence_signature_with_large_evidence_list(self):
        """Test signature computation with 100+ evidence items completes quickly."""
        evidence = [
            GapEvidence(
                invariant_family=f"family_{i % 5}",
                description=f"Description {i}",
                details={"index": i, "data": f"value_{i}"},
                confidence=0.5 + (i % 50) / 100,
            )
            for i in range(150)
        ]

        # Should complete without timeout
        sig = compute_evidence_signature(evidence)
        assert len(sig) == 8

        # Verify determinism
        sig2 = compute_evidence_signature(evidence)
        assert sig == sig2

    def test_remainder_queue_with_large_item_list(self):
        """Test stagnation detection with 1000+ items is efficient."""
        queue = RemainderQueue(stagnation_threshold=3)

        # Initial large list
        items = [f"item_{i}" for i in range(1000)]
        queue.update(items)
        assert queue.stagnation_count == 0

        # Same items, different order (should detect stagnation)
        items_shuffled = items[::-1]  # Reverse
        queue.update(items_shuffled)
        assert queue.stagnation_count == 1

        # Remove one item (should reset stagnation)
        queue.update(items[:-1])
        assert queue.stagnation_count == 0

    def test_conflict_bundle_ranking_with_many_variants(self):
        """Test ranking 100+ variants completes quickly and deterministically."""
        variants = [
            ConflictVariant(
                id=f"REQ-001-v{i:03d}",
                content=f"Content variant {i}",
                source_location=f"file:{i}",
                heuristic_score=(i % 100) / 100,  # 0.00 to 0.99
            )
            for i in range(150)
        ]

        bundle = ConflictBundle(conflicting_id="REQ-001", variants=variants)
        bundle.rank_variants()

        # Highest score is 0.99 (at i=99)
        assert bundle.recommended_variant == "REQ-001-v099"

        # Verify determinism
        for _ in range(5):
            bundle2 = ConflictBundle(conflicting_id="REQ-001", variants=variants.copy())
            bundle2.rank_variants()
            assert bundle2.recommended_variant == bundle.recommended_variant

    def test_serialization_of_large_gap_with_many_evidence_items(self):
        """Test to_dict/from_dict with 50+ evidence items."""
        evidence = [
            GapEvidence(
                invariant_family=f"family_{i % 3}",
                description=f"Evidence item {i}",
                details={
                    "index": i,
                    "nested": {"level": 2, "values": [1, 2, 3]},
                },
                confidence=0.9,
                location=f"file_{i}.md:{i * 10}",
                detector=f"detector_{i % 5}",
            )
            for i in range(75)
        ]

        gap = Gap(
            id="GAP-largegap",
            severity=Severity.ERROR,
            evidence=evidence,
            status=STATUS_OPEN,
            affected_elements=[f"ELEM-{i}" for i in range(20)],
        )

        data = gap.to_dict()
        assert len(data["evidence"]) == 75
        assert len(data["affected_elements"]) == 20

        restored = Gap.from_dict(data)
        assert len(restored.evidence) == 75
        assert restored.evidence[50].invariant_family == "family_2"

    def test_nested_details_serialization_depth(self):
        """Test deeply nested dicts (10+ levels) are handled correctly."""
        # Build deeply nested structure
        nested = {"leaf": "value"}
        for i in range(15):
            nested = {f"level_{i}": nested}

        evidence = GapEvidence(
            invariant_family="format",
            description="Deep nesting",
            details=nested,
        )

        # Should serialize without recursion errors
        data = evidence.to_dict()
        assert "level_14" in data["details"]

        # Walk down to verify structure
        current = data["details"]
        for i in range(14, -1, -1):
            assert f"level_{i}" in current
            current = current[f"level_{i}"]
        assert current == {"leaf": "value"}
