"""Strategy implementations for the spec_manager strategy framework."""

from spec_manager.strategies.implementations.coverage_verification import (
    CoverageVerificationStrategy,
)
from spec_manager.strategies.implementations.llm_inference import (
    InferenceResult,
    ProseFragmentEvidence,
    ProseFragmentInferenceDetector,
    ProseFragmentReductionStrategy,
    VagueReferenceResolver,
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
    # Unitizers
    "Unitizer",
    "LineUnitizer",
    "SentenceUnitizer",
    "ClauseUnitizer",
    "LLMUnitizer",
    "SectionUnitizer",
    "UnitizationSelector",
    # LLM Inference
    "InferenceResult",
    "ProseFragmentEvidence",
    "ProseFragmentInferenceDetector",
    "ProseFragmentReductionStrategy",
    "VagueReferenceResolver",
    # Strategies
    "SentenceDecompositionStrategy",
    "CoverageVerificationStrategy",
]
