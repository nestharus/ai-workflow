"""Atom-aware drift comparator implementing ALG-PROJ-0002 and ALG-PROJ-0003.

Provides drift detection between projections and spec index using atom
fingerprints for cross-revision matching.

Phase 7 Work Item 2: Atom-Aware Drift Comparator
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from spec_manager.core.gap import Gap, GapEvidence, GapType
from spec_manager.core.gaps import Severity

if TYPE_CHECKING:
    from spec_manager.schemas.atoms import LineAtom
    from spec_manager.schemas.projection import ProjectionArtifact
    from spec_manager.schemas.spec_index_v2 import SpecIndexV2

logger = logging.getLogger(__name__)


@dataclass
class DriftItem:
    """DS-PROJ-0003 compliant drift item.

    Represents a single drift detected between projection and source.

    Attributes:
        drift_type: Type of drift detected
        evidence_atom_ids: Atom IDs related to this drift
        projection_excerpt: Excerpt from projection at drift location
        best_match_score: Similarity score of best match (0.0-1.0)
        pin_id: Optional pin ID if drift is related to a specific pin
        target_id: Target ID referenced by the pin
        urgency: Optional urgency classification for propagation-driven drift
        trace_details: Structured trace metadata preserved through transformations
    """

    drift_type: Literal["PLAN_ONLY", "MISMATCH", "MISSING_PIN", "PIN_TARGET_MISSING"]
    evidence_atom_ids: list[str] = field(default_factory=list)
    projection_excerpt: str = ""
    best_match_score: float = 0.0
    pin_id: str | None = None
    target_id: str | None = None
    urgency: str | None = None
    trace_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AtomAlignment:
    """Result of atom alignment between two revisions.

    Uses fingerprint-based matching for cross-revision atom correlation.

    Attributes:
        opcodes: List of (op, old_start, old_end, new_start, new_end) tuples
        matched_pairs: List of (old_atom_id, new_atom_id) pairs
        old_only: Atom IDs that only exist in old version
        new_only: Atom IDs that only exist in new version
    """

    opcodes: list[tuple[str, int, int, int, int]] = field(default_factory=list)
    matched_pairs: list[tuple[str, str]] = field(default_factory=list)
    old_only: list[str] = field(default_factory=list)
    new_only: list[str] = field(default_factory=list)


class DriftPolicy(BaseModel):
    """Configuration for drift detection and gap conversion.

    Attributes:
        drift_similarity_floor: Minimum similarity below which drift becomes a gap
        drift_severity: Severity to assign to drift-based gaps
        include_excerpts: Whether to include projection excerpts in drift items
        max_excerpt_length: Maximum length of excerpts
    """

    drift_similarity_floor: float = Field(default=0.8, ge=0.0, le=1.0)
    drift_severity: Severity = Field(default=Severity.WARNING)
    include_excerpts: bool = True
    max_excerpt_length: int = 200


@dataclass
class DriftReport:
    """Result of drift detection between projection and sources.

    Attributes:
        projection_id: ID of the projection analyzed
        drift_items: List of detected drift items
        similarity: Overall similarity score (0.0-1.0)
        total_pins: Number of pins in the projection
        valid_pins: Number of pins with valid targets
        missing_targets: Number of pins with missing targets
        created_at: Timestamp when report was created
    """

    projection_id: str
    drift_items: list[DriftItem] = field(default_factory=list)
    similarity: float = 1.0
    total_pins: int = 0
    valid_pins: int = 0
    missing_targets: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def has_significant_drift(self, threshold: float = 0.8) -> bool:
        """Check if drift exceeds significance threshold.

        Args:
            threshold: Similarity threshold below which drift is significant

        Returns:
            True if similarity is below threshold
        """
        return self.similarity < threshold


class AtomAwareDriftComparator:
    """ALG-PROJ-0002 implementation.

    Compares projections against spec index using atom fingerprints
    for cross-revision matching.
    """

    def __init__(self, policy: DriftPolicy | None = None) -> None:
        """Initialize the drift comparator.

        Args:
            policy: Configuration for drift detection
        """
        self.policy = policy or DriftPolicy()

    def compare(
        self,
        projection: ProjectionArtifact,
        spec_index: SpecIndexV2,
        atoms: list[LineAtom] | None = None,
    ) -> DriftReport:
        """Compare projection against spec index.

        Args:
            projection: ProjectionArtifact to analyze
            spec_index: SpecIndexV2 with authoritative elements
            atoms: Optional list of atoms for atom-level comparison

        Returns:
            DriftReport with drift analysis results
        """
        drift_items: list[DriftItem] = []
        valid_pins = 0
        missing_targets = 0

        # Check each pin for target existence
        for pin in projection.pins:
            target_exists = self._check_target_exists(pin.target_id, pin.target_kind, spec_index)

            if target_exists:
                valid_pins += 1
            else:
                missing_targets += 1
                excerpt = self._extract_excerpt(projection.content, pin.from_projection_offset)
                drift_items.append(
                    DriftItem(
                        drift_type="PIN_TARGET_MISSING",
                        evidence_atom_ids=[],
                        projection_excerpt=excerpt,
                        best_match_score=0.0,
                        pin_id=pin.pin_id,
                        target_id=pin.target_id,
                    )
                )

        # Compute atom-level alignment if atoms provided
        atom_similarity = 1.0
        if atoms:
            atom_drift_items, atom_similarity = self._compare_atoms(projection, spec_index, atoms)
            drift_items.extend(atom_drift_items)

        # Compute overall similarity
        total_pins = len(projection.pins)
        pin_validity_ratio = valid_pins / total_pins if total_pins > 0 else 1.0

        # Weight: 60% pin validity, 40% atom alignment
        similarity = (0.6 * pin_validity_ratio) + (0.4 * atom_similarity)

        return DriftReport(
            projection_id=projection.projection_id,
            drift_items=drift_items,
            similarity=similarity,
            total_pins=total_pins,
            valid_pins=valid_pins,
            missing_targets=missing_targets,
        )

    def _check_target_exists(
        self,
        target_id: str,
        target_kind: str,
        spec_index: SpecIndexV2,
    ) -> bool:
        """Check if a pin target exists in the spec index.

        Args:
            target_id: ID of the target
            target_kind: Kind of target (LIBRARY, ELEMENT, ATOM_RANGE)
            spec_index: SpecIndexV2 to check

        Returns:
            True if target exists
        """
        if target_kind == "LIBRARY":
            return spec_index.get_library(target_id) is not None
        if target_kind == "ELEMENT":
            return spec_index.get_element(target_id) is not None
        if target_kind == "ATOM_RANGE":
            return len(spec_index.get_elements_for_atom(target_id)) > 0
        if target_kind == "ATOM_FUNCTION":
            logger.warning(
                "ATOM_FUNCTION pin target cannot be validated against SpecIndexV2 "
                "without a pin-function authority source: %s",
                target_id,
            )
            return False
        raise ValueError(f"Unsupported pin target kind: {target_kind}")

    def _extract_excerpt(self, content: str, offset: int) -> str:
        """Extract an excerpt around an offset.

        Args:
            content: Full content string
            offset: Character offset to center excerpt on

        Returns:
            Excerpt string
        """
        if not self.policy.include_excerpts:
            return ""

        half_len = self.policy.max_excerpt_length // 2
        start = max(0, offset - half_len)
        end = min(len(content), offset + half_len)

        excerpt = content[start:end]
        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt = excerpt + "..."

        return excerpt

    def _compare_atoms(
        self,
        projection: ProjectionArtifact,
        spec_index: SpecIndexV2,
        atoms: list[LineAtom],
    ) -> tuple[list[DriftItem], float]:
        """Compare atoms between projection and spec index.

        Uses fingerprint-based matching for cross-revision correlation.

        Args:
            projection: ProjectionArtifact being analyzed
            spec_index: SpecIndexV2 with authoritative atoms
            atoms: List of current atoms

        Returns:
            Tuple of (drift items, similarity score)
        """
        drift_items: list[DriftItem] = []
        available_atom_ids = {atom.atom_id for atom in atoms}
        expected_atoms_by_target = self._collect_expected_atoms_by_target(projection, spec_index)

        total_expected_atoms = sum(len(atom_ids) for atom_ids in expected_atoms_by_target.values())
        if total_expected_atoms == 0:
            return drift_items, 1.0

        matched_atoms = 0
        for target_id, expected_atom_ids in expected_atoms_by_target.items():
            missing_atom_ids = [
                atom_id for atom_id in expected_atom_ids if atom_id not in available_atom_ids
            ]
            matched_atoms += len(expected_atom_ids) - len(missing_atom_ids)

            if not missing_atom_ids:
                continue

            pins_for_target = projection.get_pins_by_target(target_id)
            pin_id = pins_for_target[0].pin_id if pins_for_target else None
            excerpt = ""
            if pins_for_target:
                excerpt = self._extract_excerpt(
                    projection.content,
                    pins_for_target[0].from_projection_offset,
                )
            if not excerpt:
                excerpt = f"Projection target {target_id} references missing atoms"

            drift_items.append(
                DriftItem(
                    drift_type="MISMATCH",
                    evidence_atom_ids=missing_atom_ids,
                    projection_excerpt=excerpt,
                    best_match_score=(
                        (len(expected_atom_ids) - len(missing_atom_ids)) / len(expected_atom_ids)
                        if expected_atom_ids
                        else 1.0
                    ),
                    pin_id=pin_id,
                    target_id=target_id,
                    trace_details={
                        "expected_atom_ids": expected_atom_ids,
                        "missing_atom_ids": missing_atom_ids,
                    },
                )
            )

        similarity = matched_atoms / total_expected_atoms
        return drift_items, similarity

    def _collect_expected_atoms_by_target(
        self,
        projection: ProjectionArtifact,
        spec_index: SpecIndexV2,
    ) -> dict[str, list[str]]:
        """Collect expected atom IDs grouped by projection target."""
        expected_atoms_by_target: dict[str, list[str]] = {}

        for pin in projection.pins:
            if pin.target_kind == "ELEMENT":
                if spec_index.get_element(pin.target_id) is None:
                    continue
                atom_ids = self._dedupe_ids(spec_index.get_atoms_for_element(pin.target_id))
                if atom_ids:
                    expected_atoms_by_target[pin.target_id] = atom_ids
                continue

            if pin.target_kind == "LIBRARY":
                for elem_data in spec_index.get_elements_by_library(pin.target_id):
                    elem_id_raw = elem_data.get("elem_id")
                    elem_id = str(elem_id_raw) if elem_id_raw is not None else ""
                    if not elem_id:
                        continue
                    atom_ids = self._dedupe_ids(spec_index.get_atoms_for_element(elem_id))
                    if atom_ids:
                        expected_atoms_by_target[elem_id] = atom_ids
                continue

            if pin.target_kind == "ATOM_RANGE":
                expected_atoms_by_target[pin.target_id] = [pin.target_id]

        return expected_atoms_by_target

    @staticmethod
    def _dedupe_ids(values: list[str]) -> list[str]:
        """Return IDs with order preserved and duplicates removed."""
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def align_atoms(
        self,
        old_atoms: list[LineAtom],
        new_atoms: list[LineAtom],
    ) -> AtomAlignment:
        """Align atoms between two revisions using fingerprints.

        Implements ALG-XFORM-0001: AtomAwareAlignment.

        Args:
            old_atoms: Atoms from old revision
            new_atoms: Atoms from new revision

        Returns:
            AtomAlignment with matched pairs and opcodes
        """
        # Build fingerprint maps that preserve duplicate fingerprints.
        old_fp_to_atoms: dict[str, list[LineAtom]] = defaultdict(list)
        new_fp_to_atoms: dict[str, list[LineAtom]] = defaultdict(list)
        for atom in old_atoms:
            old_fp_to_atoms[atom.atom_fingerprint].append(atom)
        for atom in new_atoms:
            new_fp_to_atoms[atom.atom_fingerprint].append(atom)

        # Find matching pairs by fingerprint
        matched_pairs: list[tuple[str, str]] = []
        old_matched: set[str] = set()
        new_matched: set[str] = set()

        for fp in sorted(set(old_fp_to_atoms) & set(new_fp_to_atoms)):
            old_group = old_fp_to_atoms[fp]
            new_group = new_fp_to_atoms[fp]
            pair_count = min(len(old_group), len(new_group))
            for idx in range(pair_count):
                old_atom = old_group[idx]
                new_atom = new_group[idx]
                matched_pairs.append((old_atom.atom_id, new_atom.atom_id))
                old_matched.add(old_atom.atom_id)
                new_matched.add(new_atom.atom_id)

        # Find unmatched atoms
        old_only = [a.atom_id for a in old_atoms if a.atom_id not in old_matched]
        new_only = [a.atom_id for a in new_atoms if a.atom_id not in new_matched]

        # Generate opcodes using text content
        old_texts = [a.text for a in old_atoms]
        new_texts = [a.text for a in new_atoms]
        matcher = SequenceMatcher(None, old_texts, new_texts)
        opcodes = matcher.get_opcodes()

        return AtomAlignment(
            opcodes=list(opcodes),
            matched_pairs=matched_pairs,
            old_only=old_only,
            new_only=new_only,
        )


def convert_drift_to_gaps(
    drift_report: DriftReport,
    policy: DriftPolicy | None = None,
) -> list[Gap]:
    """Convert drift items exceeding floor into Gaps (ALG-PROJ-0003, CON-0013).

    Args:
        drift_report: DriftReport from comparator
        policy: DriftPolicy with thresholds

    Returns:
        List of Gap objects for significant drift
    """
    if policy is None:
        policy = DriftPolicy()

    gaps: list[Gap] = []

    # Overall drift threshold controls only the aggregate-level gap.
    if drift_report.similarity < policy.drift_similarity_floor:
        overall_gap = Gap(
            id=f"GAP-DRIFT-{drift_report.projection_id[:8]}",
            gap_type=GapType.content_mismatch,
            severity=policy.drift_severity,
            source=[drift_report.projection_id],
            derived_artifact_target=f"projection:{drift_report.projection_id}",
            description=(
                f"Projection drift exceeds floor: similarity={drift_report.similarity:.2%}, "
                f"threshold={policy.drift_similarity_floor:.2%}"
            ),
            evidence=[
                GapEvidence(
                    invariant_family="content",
                    description="Projection-to-source drift detected",
                    details={
                        "similarity": drift_report.similarity,
                        "threshold": policy.drift_similarity_floor,
                        "total_pins": drift_report.total_pins,
                        "valid_pins": drift_report.valid_pins,
                        "missing_targets": drift_report.missing_targets,
                    },
                    confidence=1.0,
                    detector="drift_comparator",
                )
            ],
        )
        gaps.append(overall_gap)

    # Evaluate item-level drift independently so local evidence is never dropped.
    for idx, item in enumerate(drift_report.drift_items):
        if item.drift_type == "PIN_TARGET_MISSING" and item.target_id:
            target_gap = Gap(
                id=f"GAP-DRIFT-{item.pin_id or 'UNKNOWN'}-{idx}",
                gap_type=GapType.content_mismatch,
                severity=policy.drift_severity,
                source=[item.pin_id or drift_report.projection_id],
                derived_artifact_target=item.target_id,
                description=f"Pin target missing: {item.target_id}",
                evidence=[
                    GapEvidence(
                        invariant_family="content",
                        description=f"Pin {item.pin_id} references missing target",
                        details={
                            "drift_type": item.drift_type,
                            "target_id": item.target_id,
                            "excerpt": item.projection_excerpt,
                            "urgency": item.urgency,
                            "trace_details": item.trace_details,
                        },
                        confidence=1.0,
                        detector="drift_comparator",
                    )
                ],
            )
            gaps.append(target_gap)
            continue

        if item.drift_type in {"MISMATCH", "MISSING_PIN"}:
            if item.best_match_score >= policy.drift_similarity_floor:
                continue

            mismatch_gap = Gap(
                id=f"GAP-DRIFT-{item.pin_id or 'ITEM'}-{idx}",
                gap_type=GapType.content_mismatch,
                severity=policy.drift_severity,
                source=[item.pin_id or drift_report.projection_id],
                derived_artifact_target=(
                    item.target_id or f"projection:{drift_report.projection_id}"
                ),
                description=(
                    f"Drift item {item.drift_type} below floor: "
                    "match="
                    f"{item.best_match_score:.2%}, "
                    f"threshold={policy.drift_similarity_floor:.2%}"
                ),
                evidence=[
                    GapEvidence(
                        invariant_family="content",
                        description="Item-level projection drift detected",
                        details={
                            "drift_type": item.drift_type,
                            "best_match_score": item.best_match_score,
                            "threshold": policy.drift_similarity_floor,
                            "evidence_atom_ids": item.evidence_atom_ids,
                            "target_id": item.target_id,
                            "excerpt": item.projection_excerpt,
                            "urgency": item.urgency,
                            "trace_details": item.trace_details,
                        },
                        confidence=1.0,
                        detector="drift_comparator",
                    )
                ],
            )
            gaps.append(mismatch_gap)

    return gaps


__all__ = [
    "AtomAlignment",
    "AtomAwareDriftComparator",
    "DriftItem",
    "DriftPolicy",
    "DriftReport",
    "convert_drift_to_gaps",
]
