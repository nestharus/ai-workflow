"""Strategy implementations for the spec_manager strategy framework."""

from spec_manager.strategies.implementations.coverage_verification import (
    CoverageVerificationStrategy,
)
from spec_manager.strategies.implementations.entity_resolution import (
    EntityResolutionStrategy,
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
    # Strategies
    "CoverageVerificationStrategy",
    "EntityResolutionStrategy",
    "LineMembershipStrategy",
    "LowConfidenceRemainderStrategy",
    "SentenceDecompositionStrategy",
    # LLM Inference
    "InferenceResult",
    "ProseFragmentEvidence",
    "ProseFragmentInferenceDetector",
    "ProseFragmentReductionStrategy",
    "VagueReferenceResolver",
    # Unitizers
    "ClauseUnitizer",
    "LLMUnitizer",
    "LineUnitizer",
    "SectionUnitizer",
    "SentenceUnitizer",
    "UnitizationSelector",
    "Unitizer",
]
