"""Schema definitions for structured agent outputs."""

from .architecture import (
    ArchitectureCandidate,
    ArchitectureComponent,
    ArchitectureProposal,
    ArchitectureSelection,
    ArchitectureTradeoffs,
)
from .architecture_brief import ArchitectureBrief
from .atoms import LineAtom
from .evidence_mapper import EvidenceMapperOutput
from .files import FileManifestEntry, FilesManifest
from .gap_judge import GapFinding, GapJudgeOutput
from .library_labels import LibraryLabel, LibraryLabelerOutput
from .qa_judge import QaCriterionResult, QaJudgeOutput
from .sections import FileSections, SectionSpan
from .spec_patches import SpecPatchOp, SpecPatchOutput
from .terms import FileTerms, SectionTerms

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
