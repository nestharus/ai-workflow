"""Core utilities for spec management."""

from spec_manager.core.annotations import AnnotationParser
from spec_manager.core.gaps import (
    ContentVerifier,
    # Primary types (new names to avoid collision with data_structures.py)
    DetectorFinding,
    DuplicateDetector,
    # Consolidated interfaces
    EvidenceExtractor,
    # Detectors
    FormatComplianceDetector,
    Gap,  # Alias for LegacyGap
    GapElement,
    # Backward compatibility aliases (deprecated, prefer new names)
    GapEvidence,  # Alias for DetectorFinding
    GapSynthesizer,
    InferredClaimPromotionStrategy,
    LegacyGap,
    ProofChainDetector,
    ProseFragmentInferenceDetector,
    SequenceAnalyzer,
    # New evidence-based gap detection (Phase D)
    Severity,
    StructuralHealthDetector,
    UncertaintyDetector,
    UndefinedFunctionDetector,
    UnifiedGapDetector,
    # Legacy API
    detect_gaps,
    format_gaps_md,
    normalize_to_evidence,  # Alias for normalize_to_findings
    normalize_to_findings,
)
from spec_manager.core.ids import IdValidator
from spec_manager.core.intermediate import (
    FileSnapshot,
    IntermediateManager,
    IntermediateState,
)
from spec_manager.core.libs_registry import LibsRegistry
from spec_manager.core.provenance import (
    GranularityLevel,
    LineageEdge,
    LineageTable,
    MembershipEvidence,
    ProvenanceTracker,
    SourceLocation,
    TargetLocation,
    TrackedUnit,
    UnitStatus,
    UnitType,
    generate_stamp,
    parse_stamp,
)
from spec_manager.core.sections import SectionExtractor

__all__ = [
    # Existing exports
    "AnnotationParser",
    "ContentVerifier",
    # Primary types (new names)
    "DetectorFinding",
    "DuplicateDetector",
    "EvidenceExtractor",
    "FileSnapshot",
    "FormatComplianceDetector",
    "Gap",
    "GapElement",
    # Backward compatibility aliases (deprecated)
    "GapEvidence",
    "GapSynthesizer",
    "GranularityLevel",
    "IdValidator",
    "InferredClaimPromotionStrategy",
    # Intermediate state management (Phase A)
    "IntermediateManager",
    "IntermediateState",
    "LegacyGap",
    "LibsRegistry",
    "LineageEdge",
    "LineageTable",
    "MembershipEvidence",
    "ProofChainDetector",
    "ProseFragmentInferenceDetector",
    "ProvenanceTracker",
    "SectionExtractor",
    "SequenceAnalyzer",
    # Evidence-based gap detection (Phase D)
    "Severity",
    "SourceLocation",
    "StructuralHealthDetector",
    "TargetLocation",
    "TrackedUnit",
    "UncertaintyDetector",
    "UndefinedFunctionDetector",
    "UnifiedGapDetector",
    "UnitStatus",
    # Provenance tracking (Phase A)
    "UnitType",
    "detect_gaps",
    "format_gaps_md",
    "generate_stamp",
    "normalize_to_evidence",
    "normalize_to_findings",
    "parse_stamp",
]
