"""Entity coverage compliance gate for promotion checks.

Provides the ``check_entity_coverage`` function that integrates with the
existing ``LayerPromotionGate`` orchestrator as the ENTITY_COVERAGE gate.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from spec_manager.compliance.coverage.analyzer import EntityCoverageAnalyzer
from spec_manager.compliance.coverage.report import EntityCoverageReport
from spec_manager.compliance.promotion.result import GateCheckResult

if TYPE_CHECKING:
    from spec_manager.branches.atoms import AtomRegistry
    from spec_manager.compliance.promotion.config import GateSpec
    from spec_manager.core.evidence_index import EvidenceIndex
    from spec_manager.schemas.entities import EntitiesArtifact


def check_entity_coverage(
    evidence_index: EvidenceIndex,
    atom_registry: AtomRegistry,
    gate_spec: GateSpec,
    entities_artifact: EntitiesArtifact | None = None,
) -> GateCheckResult:
    """Run the entity coverage gate check.

    Instantiates ``EntityCoverageAnalyzer``, runs analysis, and builds
    a ``GateCheckResult`` comparing ``entity_coverage`` against the
    configured threshold.

    Args:
        evidence_index: The evidence index with entity/paragraph data.
        atom_registry: The atom registry with atom descriptors.
        gate_spec: Gate configuration with threshold and mode.
        entities_artifact: Optional entities artifact for explicit linkage.

    Returns:
        GateCheckResult for the ENTITY_COVERAGE gate.
    """
    start = time.monotonic()

    analyzer = EntityCoverageAnalyzer(evidence_index, atom_registry, entities_artifact)
    report = analyzer.analyze()

    # Build findings from unmatched entities
    findings = []
    for ue in report.unmatched_entities:
        findings.append(
            {
                "entity_id": ue.entity_id,
                "name": ue.name,
                "kind": ue.kind,
                "paragraph_ids": ue.paragraph_ids,
                "lib_ids": ue.lib_ids,
                "type": "unmatched_entity",
            }
        )
    for ua in report.unmatched_atoms:
        findings.append(
            {
                "atom_id": ua.atom_id,
                "function_name": ua.function_name,
                "kind": ua.kind,
                "vertical_slice": ua.vertical_slice,
                "type": "unmatched_atom",
            }
        )
    for diagnostic in report.diagnostics:
        finding = {"type": "diagnostic"}
        finding.update(diagnostic)
        findings.append(finding)

    passed = report.entity_coverage >= gate_spec.threshold
    duration_ms = (time.monotonic() - start) * 1000

    summary_parts = [
        f"Entity coverage: {report.entity_coverage:.1%}",
        f"({len(report.matched)} matched",
        f"{len(report.unmatched_entities)} unmatched entities",
        f"{len(report.unmatched_atoms)} unmatched atoms)",
    ]

    from spec_manager.compliance.promotion.config import GateId

    return GateCheckResult(
        gate_id=GateId.ENTITY_COVERAGE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=report.entity_coverage,
        findings=findings,
        summary=", ".join(summary_parts),
        duration_ms=duration_ms,
    )


def build_entity_coverage_report(
    evidence_index: EvidenceIndex,
    atom_registry: AtomRegistry,
    entities_artifact: EntitiesArtifact | None = None,
) -> EntityCoverageReport:
    """Convenience wrapper to build an entity coverage report.

    Args:
        evidence_index: The evidence index with entity/paragraph data.
        atom_registry: The atom registry with atom descriptors.
        entities_artifact: Optional entities artifact for explicit linkage.

    Returns:
        EntityCoverageReport with coverage analysis results.
    """
    analyzer = EntityCoverageAnalyzer(evidence_index, atom_registry, entities_artifact)
    return analyzer.analyze()
