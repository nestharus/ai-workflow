"""Core utilities for spec management."""

from spec_manager.core.annotations import AnnotationParser
from spec_manager.core.sections import SectionExtractor
from spec_manager.core.ids import IdValidator
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.provenance import (
    UnitType,
    UnitStatus,
    GranularityLevel,
    SourceLocation,
    TargetLocation,
    MembershipEvidence,
    TrackedUnit,
    ProvenanceTracker,
    LineageTable,
    LineageEdge,
    parse_stamp,
    generate_stamp,
)
from spec_manager.core.intermediate import (
    IntermediateManager,
    IntermediateState,
    FileSnapshot,
)
from spec_manager.core.gaps import (
    # New evidence-based gap detection (Phase D)
    Severity,
    GapEvidence,
    Gap,
    GapElement,
    normalize_to_evidence,
    # Detectors
    FormatComplianceDetector,
    DuplicateDetector,
    UndefinedFunctionDetector,
    SequenceAnalyzer,
    ContentVerifier,
    ProofChainDetector,
    ProseFragmentInferenceDetector,
    InferredClaimPromotionStrategy,
    UncertaintyDetector,
    StructuralHealthDetector,
    # Consolidated interfaces
    EvidenceExtractor,
    GapSynthesizer,
    UnifiedGapDetector,
    # Legacy API
    detect_gaps,
    format_gaps_md,
)

__all__ = [
    # Existing exports
    "AnnotationParser",
    "SectionExtractor",
    "IdValidator",
    "LibsRegistry",
    # Provenance tracking (Phase A)
    "UnitType",
    "UnitStatus",
    "GranularityLevel",
    "SourceLocation",
    "TargetLocation",
    "MembershipEvidence",
    "TrackedUnit",
    "ProvenanceTracker",
    "LineageTable",
    "LineageEdge",
    "parse_stamp",
    "generate_stamp",
    # Intermediate state management (Phase A)
    "IntermediateManager",
    "IntermediateState",
    "FileSnapshot",
    # Evidence-based gap detection (Phase D)
    "Severity",
    "GapEvidence",
    "Gap",
    "GapElement",
    "normalize_to_evidence",
    "FormatComplianceDetector",
    "DuplicateDetector",
    "UndefinedFunctionDetector",
    "SequenceAnalyzer",
    "ContentVerifier",
    "ProofChainDetector",
    "ProseFragmentInferenceDetector",
    "InferredClaimPromotionStrategy",
    "UncertaintyDetector",
    "StructuralHealthDetector",
    "EvidenceExtractor",
    "GapSynthesizer",
    "UnifiedGapDetector",
    "detect_gaps",
    "format_gaps_md",
]
