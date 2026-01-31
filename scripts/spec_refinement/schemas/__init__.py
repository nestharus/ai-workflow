"""Schema definitions for structured agent outputs."""

from scripts.spec_refinement.schemas.architecture import (
    ArchitectureCandidate,
    ArchitectureComponent,
    ArchitectureProposal,
    ArchitectureSelection,
    ArchitectureTradeoffs,
)
from scripts.spec_refinement.schemas.architecture_brief import ArchitectureBrief
from scripts.spec_refinement.schemas.evidence_mapper import EvidenceMapperOutput
from scripts.spec_refinement.schemas.gap_judge import GapFinding, GapJudgeOutput
from scripts.spec_refinement.schemas.library_labels import LibraryLabel, LibraryLabelerOutput
from scripts.spec_refinement.schemas.spec_patches import SpecPatchOp, SpecPatchOutput

__all__ = [
    "ArchitectureBrief",
    "ArchitectureCandidate",
    "ArchitectureComponent",
    "ArchitectureProposal",
    "ArchitectureSelection",
    "ArchitectureTradeoffs",
    "EvidenceMapperOutput",
    "GapFinding",
    "GapJudgeOutput",
    "LibraryLabel",
    "LibraryLabelerOutput",
    "SpecPatchOp",
    "SpecPatchOutput",
]
