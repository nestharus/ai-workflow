"""Schema definitions for structured agent outputs."""

from scripts.spec_refinement.schemas.architecture import (
    ArchitectureCandidate,
    ArchitectureComponent,
    ArchitectureProposal,
    ArchitectureSelection,
    ArchitectureTradeoffs,
)
from scripts.spec_refinement.schemas.architecture_brief import ArchitectureBrief
from scripts.spec_refinement.schemas.atoms import LineAtom
from scripts.spec_refinement.schemas.evidence_mapper import EvidenceMapperOutput
from scripts.spec_refinement.schemas.files import FileManifestEntry, FilesManifest
from scripts.spec_refinement.schemas.gap_judge import GapFinding, GapJudgeOutput
from scripts.spec_refinement.schemas.library_labels import LibraryLabel, LibraryLabelerOutput
from scripts.spec_refinement.schemas.qa_judge import QaCriterionResult, QaJudgeOutput
from scripts.spec_refinement.schemas.sections import FileSections, SectionSpan
from scripts.spec_refinement.schemas.spec_patches import SpecPatchOp, SpecPatchOutput
from scripts.spec_refinement.schemas.terms import FileTerms, SectionTerms

__all__ = [
    "ArchitectureBrief",
    "ArchitectureCandidate",
    "ArchitectureComponent",
    "ArchitectureProposal",
    "ArchitectureSelection",
    "ArchitectureTradeoffs",
    "EvidenceMapperOutput",
    "FileManifestEntry",
    "FileSections",
    "FileTerms",
    "FilesManifest",
    "GapFinding",
    "GapJudgeOutput",
    "LibraryLabel",
    "LibraryLabelerOutput",
    "LineAtom",
    "QaCriterionResult",
    "QaJudgeOutput",
    "SectionSpan",
    "SectionTerms",
    "SpecPatchOp",
    "SpecPatchOutput",
]
