"""Strategy implementations for the spec_manager strategy framework."""

from spec_manager.strategies.implementations.coverage_verification import (
    CoverageVerificationStrategy,
)
from spec_manager.strategies.implementations.entity_resolution import (
    EntityResolutionStrategy,
)
from spec_manager.strategies.implementations.format_repair import (
    FormatRepairStrategy,
)
from spec_manager.strategies.implementations.line_membership import (
    LineMembershipStrategy,
)
from spec_manager.strategies.implementations.llm_inference import (
    InferenceResult,
    ProseFragmentEvidence,
    ProseFragmentInferenceDetector,
    ProseFragmentReductionStrategy,
    VagueReferenceResolver,
)
from spec_manager.strategies.implementations.low_confidence_remainder import (
    LowConfidenceRemainderStrategy,
)
from spec_manager.strategies.implementations.sentence_decomposition import (
    SentenceDecompositionStrategy,
)
from spec_manager.strategies.implementations.truncation_guard import (
    TruncationGuardStrategy,
)
from spec_manager.strategies.implementations.unitizers import (
    ClauseUnitizer,
    LineUnitizer,
    LLMUnitizer,
    SectionUnitizer,
    SentenceUnitizer,
    UnitizationSelector,
    Unitizer,
)

__all__ = [
    "ClauseUnitizer",
    "CoverageVerificationStrategy",
    "EntityResolutionStrategy",
    "FormatRepairStrategy",
    "InferenceResult",
    "LLMUnitizer",
    "LineMembershipStrategy",
    "LineUnitizer",
    "LowConfidenceRemainderStrategy",
    "ProseFragmentEvidence",
    "ProseFragmentInferenceDetector",
    "ProseFragmentReductionStrategy",
    "SectionUnitizer",
    "SentenceDecompositionStrategy",
    "SentenceUnitizer",
    "TruncationGuardStrategy",
    "UnitizationSelector",
    "Unitizer",
    "VagueReferenceResolver",
]
