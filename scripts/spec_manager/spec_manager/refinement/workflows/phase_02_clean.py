"""Phase 2 clean/compose/compliance workflow for spec refinement."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from spec_manager.compliance.scorer import ComplianceResult, ComplianceScorer
from spec_manager.core.context_index import ContextIndex, ContextIndexBuilder
from spec_manager.core.gap import GapEvidence, GapSynthesizer
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase, PhaseStatus
from spec_manager.schemas.atoms import LineAtom

logger = logging.getLogger(__name__)


class EvidenceRecord(BaseModel):
    """Validation model for phase evidence JSONL records."""

    invariant_family: str
    description: str
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    location: str | None = None
    detector: str | None = None


def _ensure_run_local_strategies(manager: WorkspaceManager) -> int:
    strategies_dir = manager.structure.workspace_dir / "strategies"
    strategies_dir.mkdir(parents=True, exist_ok=True)
    definitions_dir = Path(__file__).resolve().parents[2] / "strategies" / "definitions"

    copied = 0
    for strategy_file in sorted(definitions_dir.glob("*.yaml")):
        dest = strategies_dir / strategy_file.name
        if not dest.exists() or dest.stat().st_mtime < strategy_file.stat().st_mtime:
            shutil.copy2(strategy_file, dest)
            copied += 1

    if copied:
        logger.info("Copied %s strategy definition(s) to %s", copied, strategies_dir)
    return copied


def _copy_pass_01_evidence(
    manager: WorkspaceManager,
    pass_dir: Path,
) -> tuple[Path, list[GapEvidence]]:
    source_path = manager.structure.pass_01_dir / "evidence.jsonl"
    if not source_path.exists():
        raise FileNotFoundError(f"Missing evidence file: {source_path}")

    destination_path = pass_dir / "evidence.jsonl"
    evidence_records: list[GapEvidence] = []

    with (
        source_path.open("r", encoding="utf-8") as source,
        destination_path.open("w", encoding="utf-8") as target,
    ):
        for line in source:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            record = EvidenceRecord.model_validate(payload)
            evidence_records.append(GapEvidence.from_dict(record.model_dump()))
            target.write(stripped + "\n")

    return destination_path, evidence_records


def _write_gaps(pass_dir: Path, evidence_records: list[GapEvidence]) -> Path:
    gaps_path = pass_dir / "gaps.json"
    synthesizer = GapSynthesizer()
    gaps = synthesizer.cluster_evidence(evidence_records) if evidence_records else []
    gaps_path.write_text(
        json.dumps([gap.to_dict() for gap in gaps], indent=2),
        encoding="utf-8",
    )
    return gaps_path


def _write_identity_membership(manager: WorkspaceManager, pass_dir: Path) -> Path:
    atoms_dir = manager.structure.manifest_atoms_dir
    if not atoms_dir.exists():
        raise FileNotFoundError(f"Missing atoms directory: {atoms_dir}")

    output_path = pass_dir / "membership.jsonl"
    timestamp = datetime.now().isoformat()

    with output_path.open("w", encoding="utf-8") as handle:
        for atoms_file in sorted(atoms_dir.glob("*.atoms.jsonl")):
            with atoms_file.open("r", encoding="utf-8") as atoms_handle:
                for line in atoms_handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    atom = LineAtom.model_validate_json(stripped)
                    # v2 atoms have atom_id directly; use it as-is for identity mapping
                    record = {
                        "source_unit_id": atom.atom_id,
                        "target_element_id": atom.atom_id,
                        "rationale": "identity_mapping_phase_02",
                        "confidence": 1.0,
                        "method": "identity",
                        "timestamp": timestamp,
                    }
                    handle.write(json.dumps(record) + "\n")

    return output_path


def _write_identity_lineage(manager: WorkspaceManager, pass_dir: Path) -> Path:
    atoms_dir = manager.structure.manifest_atoms_dir
    if not atoms_dir.exists():
        raise FileNotFoundError(f"Missing atoms directory: {atoms_dir}")

    output_path = pass_dir / "lineage.jsonl"
    timestamp = datetime.now().isoformat()

    with output_path.open("w", encoding="utf-8") as handle:
        for atoms_file in sorted(atoms_dir.glob("*.atoms.jsonl")):
            with atoms_file.open("r", encoding="utf-8") as atoms_handle:
                for line in atoms_handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    atom = LineAtom.model_validate_json(stripped)
                    # v2 atoms have atom_id directly; use it as-is for identity mapping
                    record = {
                        "source_id": atom.atom_id,
                        "target_id": atom.atom_id,
                        "edge_type": "identity",
                        "timestamp": timestamp,
                    }
                    handle.write(json.dumps(record) + "\n")

    return output_path


def run_phase_02_clean(run_id: str) -> dict[str, Any]:
    """Run Phase 2 clean/compose/compliance workflow."""
    manager = WorkspaceManager(run_id=run_id, input_folder=Path("."))
    if not manager.is_initialized:
        raise RuntimeError("Workspace not initialized. Run init before Phase 2.")

    phase_status = manager.state.phases[Phase.SECTIONIZATION.value].status
    if phase_status != PhaseStatus.COMPLETED:
        raise RuntimeError("Phase 1 (sectionization) must be completed before Phase 2 can run.")

    manager.start_phase(Phase.SUMMARIZATION)

    try:
        strategy_count = _ensure_run_local_strategies(manager)

        builder = ContextIndexBuilder(
            workspace=manager.workspace_path,
            spec_folder=manager.run_root,
        )
        context_index: ContextIndex = builder.build_from_run_manifests(manager.run_root)
        context_index_path = manager.structure.workspace_dir / "indexes" / "context_index.json"
        context_index.save(context_index_path)

        pass_dir = manager.structure.intermediates_dir / "pass_02"
        pass_dir.mkdir(parents=True, exist_ok=True)

        scorer = ComplianceScorer(blocker_threshold=0.0, warning_threshold=0.05)
        compliance_result: ComplianceResult = scorer.score_run_compliance(
            run_root=manager.run_root,
            pass_num=2,
        )
        compliance_path = pass_dir / "compliance.json"
        compliance_result.save(compliance_path)

        evidence_path, evidence_records = _copy_pass_01_evidence(manager, pass_dir)
        gaps_path = _write_gaps(pass_dir, evidence_records)
        membership_path = _write_identity_membership(manager, pass_dir)
        lineage_path = _write_identity_lineage(manager, pass_dir)

        outputs = {
            "context_index_path": str(context_index_path),
            "compliance_path": str(compliance_path),
            "evidence_path": str(evidence_path),
            "gaps_path": str(gaps_path),
            "membership_path": str(membership_path),
            "lineage_path": str(lineage_path),
            "strategies_copied": strategy_count,
        }

        manager.complete_phase(Phase.SUMMARIZATION, outputs=outputs)
        return {"success": True, "outputs": outputs}
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        manager.fail_phase(Phase.SUMMARIZATION, error=str(exc))
        return {"success": False, "error": str(exc)}
