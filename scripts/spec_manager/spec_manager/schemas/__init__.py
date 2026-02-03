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
from .edge_list import (
    EdgeListSchema,
    EdgeSchema,
    InterfaceIndexSchema,
    allocate_edge_id,
    build_interface_index,
    read_edge_list_json,
    read_interface_index_json,
    validate_edge_references,
    write_edge_list_json,
    write_interface_index_json,
)
from .evidence_mapper import EvidenceMapperOutput
from .files import FileManifestEntry, FilesManifest
from .gap_judge import GapFinding, GapJudgeOutput
from .interface_contract import (
    ConsumedInterface,
    DataContract,
    InterfaceContractSchema,
    OperationalContract,
    ProvidedInterface,
    read_interface_contract_json,
    validate_contract_references,
    write_interface_contract_json,
    write_interface_contract_markdown,
)
from .library_labels import LibraryLabel, LibraryLabelerOutput
from .qa_judge import QaCriterionResult, QaJudgeOutput
from .review_actions import (
    ReviewAction,
    ReviewActionsReport,
    allocate_action_id,
    generate_stable_action_ids,
    read_review_actions_json,
    validate_pointer_format,
    validate_pointer_references,
    write_review_actions_json,
    write_review_actions_markdown,
)
from .sections import FileSections, SectionSpan
from .spec_indexes import Decision, DecisionsIndex, SpecElement, SpecIndex
from .spec_patches import SpecPatchOp, SpecPatchOutput
from .terms import FileTerms, SectionTerms

__all__ = [
    "ArchitectureBrief",
    "ArchitectureCandidate",
    "ArchitectureComponent",
    "ArchitectureProposal",
    "ArchitectureSelection",
    "ArchitectureTradeoffs",
    "ConsumedInterface",
    "DataContract",
    "Decision",
    "DecisionsIndex",
    "EdgeListSchema",
    "EdgeSchema",
    "EvidenceMapperOutput",
    "FileManifestEntry",
    "FileSections",
    "FileTerms",
    "FilesManifest",
    "GapFinding",
    "GapJudgeOutput",
    "InterfaceContractSchema",
    "InterfaceIndexSchema",
    "LibraryLabel",
    "LibraryLabelerOutput",
    "LineAtom",
    "OperationalContract",
    "ProvidedInterface",
    "QaCriterionResult",
    "QaJudgeOutput",
    "ReviewAction",
    "ReviewActionsReport",
    "SectionSpan",
    "SectionTerms",
    "SpecElement",
    "SpecIndex",
    "SpecPatchOp",
    "SpecPatchOutput",
    "allocate_action_id",
    "allocate_edge_id",
    "build_interface_index",
    "generate_stable_action_ids",
    "read_edge_list_json",
    "read_interface_contract_json",
    "read_interface_index_json",
    "read_review_actions_json",
    "validate_contract_references",
    "validate_edge_references",
    "validate_pointer_format",
    "validate_pointer_references",
    "write_edge_list_json",
    "write_interface_contract_json",
    "write_interface_contract_markdown",
    "write_interface_index_json",
    "write_review_actions_json",
    "write_review_actions_markdown",
]
