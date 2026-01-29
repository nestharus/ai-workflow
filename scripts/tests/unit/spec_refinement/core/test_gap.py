"""Tests for spec_refinement.core.gap module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from scripts.spec_manager.spec_manager.core.gaps import Severity
from scripts.spec_refinement.core.gap import (
    Gap,
    GapEvidence,
    GapSynthesizer,
    GapType,
    compute_evidence_signature,
    format_gap_markdown,
    format_gap_table,
    parse_gaps_markdown,
)


def _make_evidence(
    *,
    invariant_family: str = "coverage",
    description: str = "Missing requirement",
    details: dict[str, object] | None = None,
    confidence: float = 0.9,
) -> GapEvidence:
    evidence_details = details or {
        "derived_artifact_target": "libs/lib-a/spec.md",
        "source": ["file_001::INTRO"],
        "gap_type": "coverage_failure",
        "severity": "warning",
    }
    return GapEvidence(
        invariant_family=invariant_family,
        description=description,
        details=evidence_details,
        confidence=confidence,
        location="file_001.md:12",
        detector="coverage_detector",
    )


def test_gap_evidence_serialization():
    """Verify GapEvidence to_dict/from_dict round-trip."""
    timestamp = datetime(2024, 1, 1, 12, 0, 0)
    evidence = GapEvidence(
        invariant_family="format",
        description="Invalid ID",
        details={"path": Path("/tmp/spec.md"), "when": timestamp, "count": 2},
        confidence=0.82,
        location="spec.md:1",
        detector="format_check",
    )

    data = evidence.to_dict()
    assert data["details"]["path"] == "/tmp/spec.md"
    assert data["details"]["when"] == timestamp.isoformat()

    restored = GapEvidence.from_dict(data)
    assert restored.invariant_family == evidence.invariant_family
    assert restored.description == evidence.description
    assert restored.details["path"] == "/tmp/spec.md"
    assert restored.details["when"] == timestamp.isoformat()
    assert restored.confidence == evidence.confidence
    assert restored.location == evidence.location
    assert restored.detector == evidence.detector


def test_gap_serialization():
    """Verify Gap serialization round-trip."""
    evidence = _make_evidence()
    gap = Gap(
        id="GAP-abc12345",
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["file_001::INTRO"],
        derived_artifact_target="libs/lib-a/spec.md",
        description="Missing coverage for requirement",
        evidence=[evidence],
        status="open",
        resolution_pointer=None,
        created_at="2024-01-01T12:00:00",
        resolved_at=None,
        resolution_notes=None,
    )

    data = gap.to_dict()
    restored = Gap.from_dict(data)

    assert restored.id == gap.id
    assert restored.gap_type == gap.gap_type
    assert restored.severity == gap.severity
    assert restored.source == gap.source
    assert restored.derived_artifact_target == gap.derived_artifact_target
    assert restored.description == gap.description
    assert restored.status == gap.status
    assert restored.created_at == gap.created_at
    assert restored.evidence[0].description == evidence.description


def test_compute_evidence_signature_deterministic():
    """Verify evidence signatures are stable across ordering."""
    evidence_a = _make_evidence(description="Missing A")
    evidence_b = _make_evidence(description="Missing B")
    signature_one = compute_evidence_signature([evidence_a, evidence_b])
    signature_two = compute_evidence_signature([evidence_b, evidence_a])
    assert signature_one == signature_two


def test_gap_synthesizer_clustering():
    """Verify evidence clustering by target/invariant/source."""
    evidence_a = _make_evidence(description="Missing A")
    evidence_b = _make_evidence(description="Missing B")
    synthesizer = GapSynthesizer()
    gaps = synthesizer.cluster_evidence([evidence_a, evidence_b])
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.derived_artifact_target == "libs/lib-a/spec.md"
    assert gap.gap_type == GapType.coverage_failure
    assert gap.source == ["file_001::INTRO"]


def test_gap_synthesizer_merge():
    """Verify gap merging preserves status and resolution."""
    evidence = _make_evidence()
    existing = Gap(
        id="GAP-merge",
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["file_001::INTRO"],
        derived_artifact_target="libs/lib-a/spec.md",
        description="Missing coverage",
        evidence=[evidence],
        status="deferred",
        resolution_pointer="decision.md:10",
        created_at="2024-01-01T00:00:00",
        resolved_at="2024-01-02T00:00:00",
        resolution_notes="Deferred pending decision",
    )
    new_gap = Gap(
        id="GAP-new",
        gap_type=GapType.coverage_failure,
        severity=Severity.ERROR,
        source=["file_001::INTRO"],
        derived_artifact_target="libs/lib-a/spec.md",
        description="Missing coverage",
        evidence=[evidence],
        status="open",
        resolution_pointer=None,
        created_at="2024-01-03T00:00:00",
        resolved_at=None,
        resolution_notes=None,
    )

    synthesizer = GapSynthesizer()
    merged = synthesizer.merge_gaps([existing], [new_gap])
    assert len(merged) == 1
    merged_gap = merged[0]
    assert merged_gap.status == "deferred"
    assert merged_gap.resolution_pointer == "decision.md:10"
    assert merged_gap.severity == Severity.ERROR


def test_format_gap_table():
    """Verify gap table formatting and truncation."""
    evidence = _make_evidence()
    gap = Gap(
        id="GAP-table",
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["file_001::INTRO"],
        derived_artifact_target="lib-a",
        description="This description is too long",
        evidence=[evidence],
        status="open",
        resolution_pointer=None,
        created_at="2024-01-01T00:00:00",
        resolved_at=None,
        resolution_notes=None,
    )

    table = format_gap_table([gap], max_desc_len=10)
    assert "Description" in table
    assert "..." in table


def test_parse_gaps_markdown():
    """Verify markdown parsing round-trip."""
    evidence = _make_evidence()
    open_gap = Gap(
        id="GAP-open",
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["file_001::INTRO"],
        derived_artifact_target="libs/lib-a/spec.md",
        description="Missing coverage",
        evidence=[evidence],
        status="open",
        resolution_pointer=None,
        created_at="2024-01-01T00:00:00",
        resolved_at=None,
        resolution_notes=None,
    )
    integrated_gap = Gap(
        id="GAP-int",
        gap_type=GapType.content_mismatch,
        severity=Severity.ERROR,
        source=["file_002::DETAILS"],
        derived_artifact_target="libs/lib-b/spec.md",
        description="Content mismatch",
        evidence=[evidence],
        status="integrated",
        resolution_pointer="spec.md:42",
        created_at="2024-01-01T00:00:00",
        resolved_at="2024-01-02T00:00:00",
        resolution_notes="Integrated into spec",
    )

    content = "\n".join(
        [
            "## Open Gaps",
            format_gap_markdown(open_gap),
            "",
            "## Integrated Gaps",
            format_gap_markdown(integrated_gap),
            "",
        ]
    )
    parsed = parse_gaps_markdown(content)
    assert len(parsed) == 2
    parsed_map = {gap.id: gap for gap in parsed}
    assert parsed_map["GAP-open"].status == "open"
    assert parsed_map["GAP-int"].status == "integrated"
    assert parsed_map["GAP-int"].resolution_pointer == "spec.md:42"
