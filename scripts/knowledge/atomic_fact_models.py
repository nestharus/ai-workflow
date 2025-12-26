"""Atomic fact extraction data models for span lifecycle and dual representation.

This module provides data models for the atomic fact extraction system, supporting:
1. Span lifecycle management (ATTEMPTABLE/PROVEN/FAILED states)
2. Dual representation (canonical text + source context)
3. Work region tracking for iterative extraction
4. Validation artifacts (fabrication attempts, reconstruction failures)
5. Progress tracking (anchoring attempts, clarification questions)

The models follow TypedDict patterns from fact_store.py for consistency with
existing DuckDB/CSV operations.

Architectural References:
- requirements.md lines 17-100: Non-negotiable invariants
- requirements.md lines 365-433: Span handling and work regions
- requirements.md lines 442-476: Dual representation (canonical + source context)
- requirements.md lines 507-619: Illegal fabrication types

Non-negotiable Invariants (summary):
1. Byte-exact provenance: All references use character offsets into canonical string
2. No semantic classification requirement: Links may be untyped
3. Incomplete structures expected: Surfaced via reconstruction failures
4. Span lifecycle: ATTEMPTABLE -> PROVEN or FAILED
5. Facts do not own text: Facts explain text, multiple facts may overlap
6. Progress test: Anchoring drives improvement, clarification on stall
7. Anchoring: Uncovered text triggers expanded context extraction

Two-Phase Pipeline:
- Phase 1 (Haiku): Detail extraction - raw observations from text
- Phase 2 (Haiku): Fact construction - anchored, validated triplets
- Orchestration (Opus): Reconstruction proofs and QA validation

Span Lifecycle State Machine:
```
[*] --> ATTEMPTABLE: Span created
ATTEMPTABLE --> PROVEN: Reconstruction succeeds (uncovered = 0)
ATTEMPTABLE --> FAILED: Reconstruction fails (uncovered > 0)
FAILED --> ATTEMPTABLE: Anchoring extracts new facts
FAILED --> FAILED: Anchoring stalls (emit clarification)
PROVEN --> [*]: Span complete
```

Usage:
    from scripts.knowledge.atomic_fact_models import (
        Span,
        SpanLifecycleState,
        BaseFact,
        ImpliedFact,
        SourceContext,
        ReconstructionFailure,
        FabricationType,
    )
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from enum import Enum
from typing import Any, Literal, TypedDict

# =============================================================================
# ENUMS
# =============================================================================


class SpanLifecycleState(str, Enum):
    """Span lifecycle states for reconstruction tracking.

    Per requirements.md lines 66-76, span states track reconstruction status:
    - ATTEMPTABLE: Coverage looks sufficient to attempt reconstruction
    - PROVEN: Reconstruction succeeded, sufficient facts extracted
    - FAILED: Reconstruction failed, uncovered text remains

    PROVEN indicates the reconstruction threshold has been met (sufficient facts
    to rebuild original text), NOT that every possible fact has been extracted.
    """

    ATTEMPTABLE = "ATTEMPTABLE"
    PROVEN = "PROVEN"
    FAILED = "FAILED"


class FactType(str, Enum):
    """Classification of fact types by extraction method.

    Per requirements.md lines 365-379:
    - BASE_FACT: Directly extractable from source grammar (SpaCy-validatable)
    - IMPLIED_FACT: Derivable through logical inference from base facts
    - ENTITY_DECLARATION: Entity mention without relation triplet
    - ATTRIBUTE_ANNOTATION: Entity with modifier but no predicate
    """

    BASE_FACT = "BASE_FACT"
    IMPLIED_FACT = "IMPLIED_FACT"
    ENTITY_DECLARATION = "ENTITY_DECLARATION"
    ATTRIBUTE_ANNOTATION = "ATTRIBUTE_ANNOTATION"


class FabricationType(str, Enum):
    """Types of illegal fabrication detected during validation.

    Per requirements.md lines 507-579, fabrications fall into two categories:

    Grammar Fabrications (types 1-5, caught by SpaCy):
    - HIDDEN_COPULA: Adding verb to transform noun phrase into assertion
    - ATTRIBUTE_TO_PROCESS: Converting static adjective to temporal verb
    - PRONOUN_CONCORD: Grammatical agreement violation (number/person/gender)
    - TENSE_FABRICATION: Assigning tense when source is timeless
    - FORCED_SUBJECT: Inventing subject/object to complete triplet

    Inference Fabrications (types 6-8, caught by Opus):
    - INVALID_COREFERENCE: Pronoun resolution without valid antecedent
    - UNGROUNDED_IMPLICATION: Inference not logically following from base facts
    - CONTEXT_BOUNDARY_VIOLATION: Cross-section inference without connection
    """

    # Grammar fabrications (SpaCy-detected)
    HIDDEN_COPULA = "HIDDEN_COPULA"
    ATTRIBUTE_TO_PROCESS = "ATTRIBUTE_TO_PROCESS"
    PRONOUN_CONCORD = "PRONOUN_CONCORD"
    TENSE_FABRICATION = "TENSE_FABRICATION"
    FORCED_SUBJECT = "FORCED_SUBJECT"

    # Inference fabrications (Opus-detected)
    INVALID_COREFERENCE = "INVALID_COREFERENCE"
    UNGROUNDED_IMPLICATION = "UNGROUNDED_IMPLICATION"
    CONTEXT_BOUNDARY_VIOLATION = "CONTEXT_BOUNDARY_VIOLATION"


# =============================================================================
# CORE SPAN AND WORK REGION MODELS
# =============================================================================


class Span(TypedDict):
    """A text interval in the canonical string with lifecycle state.

    Spans track reconstruction status for text regions. Per requirements.md
    lines 402-433:
    - Spans are intervals [start_char, end_char) into canonical UTF-8 string
    - Spans may overlap and nest; not required to form disjoint list
    - Lifecycle state tracks reconstruction progress

    Attributes:
        span_id: UUID identifying this span.
        start_char: Inclusive start character offset into canonical string.
        end_char: Exclusive end character offset (end_char > start_char).
        state: Current lifecycle state (ATTEMPTABLE, PROVEN, FAILED).
        text: Verbatim text from canonical string at [start_char, end_char).
        doc_id: Document identifier this span belongs to.
        created_at: ISO 8601 timestamp when span was created.
        updated_at: ISO 8601 timestamp when span state last changed.

    Example:
        {
            "span_id": "550e8400-e29b-41d4-a716-446655440000",
            "start_char": 100,
            "end_char": 250,
            "state": "ATTEMPTABLE",
            "text": "The device supports Bluetooth and Wi-Fi connectivity.",
            "doc_id": "doc-001",
            "created_at": "2025-01-15T10:30:00Z",
            "updated_at": "2025-01-15T10:30:00Z"
        }
    """

    span_id: str
    start_char: int
    end_char: int
    state: Literal["ATTEMPTABLE", "PROVEN", "FAILED"]
    text: str
    doc_id: str
    created_at: str
    updated_at: str


class WorkRegion(TypedDict):
    """An unprocessed region awaiting fact extraction.

    Per requirements.md lines 402-433, work regions track extraction progress:
    - Initially, the entire document is one unprocessed work region
    - After extraction, regions are marked processed
    - Validation via reconstruction determines if threshold is met

    Attributes:
        region_id: UUID identifying this work region.
        doc_id: Document identifier this region belongs to.
        start_char: Inclusive start character offset into canonical string.
        end_char: Exclusive end character offset.
        is_processed: False initially, True after extraction attempt.
        created_at: ISO 8601 timestamp when region was created.

    Example:
        {
            "region_id": "550e8400-e29b-41d4-a716-446655440001",
            "doc_id": "doc-001",
            "start_char": 0,
            "end_char": 5000,
            "is_processed": False,
            "created_at": "2025-01-15T10:00:00Z"
        }
    """

    region_id: str
    doc_id: str
    start_char: int
    end_char: int
    is_processed: bool
    created_at: str


# =============================================================================
# FACT MODELS WITH DUAL REPRESENTATION
# =============================================================================


class ValidationFlags(TypedDict):
    """Validation status flags for fact verification.

    Tracks which validation checks a fact has passed:
    - grammar_valid: SpaCy grammar validation passed (structure present in source)
    - inference_valid: Opus inference validation passed (if applicable for ImpliedFact)
    - atomicity_valid: No conjunctions/compound statements detected

    Attributes:
        grammar_valid: True if SpaCy grammar validation passed.
        inference_valid: True if Opus inference validation passed (always True for BaseFact).
        atomicity_valid: True if fact contains no conjunctions/compound statements.
    """

    grammar_valid: bool
    inference_valid: bool
    atomicity_valid: bool


class SourceContext(TypedDict):
    """Provenance marker linking a fact to its source location.

    Per requirements.md lines 459-475, source context:
    - References work region(s) via character offsets into canonical string
    - Contains original phrasing as it appeared in source
    - Is NOT an ownership claim; multiple facts may share same context
    - Enables reconstruction testing by preserving verbatim original text

    Attributes:
        doc_id: Document identifier.
        start_char: Inclusive start character offset.
        end_char: Exclusive end character offset.
        verbatim_text: Original text as it appeared in source.

    Example:
        {
            "doc_id": "doc-001",
            "start_char": 100,
            "end_char": 150,
            "verbatim_text": "It supports Bluetooth connectivity."
        }
    """

    doc_id: str
    start_char: int
    end_char: int
    verbatim_text: str


class BaseFact(TypedDict):
    """A directly extractable atomic fact from source grammar.

    Per requirements.md lines 369-371, base facts:
    - Are directly extractable from source text grammar
    - Have syntactically present subject, predicate, and object
    - Can be validated by SpaCy for structural presence

    The dual representation (canonical_text + source_contexts) per lines 442-475:
    - canonical_text: Normalized, self-contained text for search/deduplication
    - source_contexts: Provenance markers for reconstruction/traceability

    Attributes:
        fact_id: UUID identifying this fact.
        fact_type: Type classification (BASE_FACT, IMPLIED_FACT, etc.).
        canonical_text: Normalized, self-contained fact text. Pronouns resolved
            or marked with UNKNOWN_REF_N placeholders.
        subject: The subject entity of the triplet.
        predicate: The relation/action connecting subject to object.
        object: The object entity of the triplet.
        source_contexts: List of provenance markers (may have multiple sources).
        confidence: Confidence score 0.0-1.0.
        extracted_at: ISO 8601 timestamp when fact was extracted.
        validation_flags: ValidationFlags tracking validation status.

    Example:
        {
            "fact_id": "550e8400-e29b-41d4-a716-446655440002",
            "fact_type": "BASE_FACT",
            "canonical_text": "The device supports Bluetooth connectivity.",
            "subject": "The device",
            "predicate": "supports",
            "object": "Bluetooth connectivity",
            "source_contexts": [{
                "doc_id": "doc-001",
                "start_char": 100,
                "end_char": 145,
                "verbatim_text": "The device supports Bluetooth connectivity."
            }],
            "confidence": 0.95,
            "extracted_at": "2025-01-15T10:35:00Z",
            "validation_flags": {
                "grammar_valid": True,
                "inference_valid": True,
                "atomicity_valid": True
            }
        }
    """

    fact_id: str
    fact_type: Literal["BASE_FACT"]
    canonical_text: str
    subject: str
    predicate: str
    object: str
    source_contexts: list[SourceContext]
    confidence: float
    extracted_at: str
    validation_flags: ValidationFlags


class ImpliedFact(TypedDict):
    """A fact derivable through logical inference from base facts.

    Per requirements.md lines 373-377, implied facts:
    - Are derivable from base facts through logical inference
    - Are not directly stated in source grammar
    - May require reasoning beyond syntax
    - Are valid when correctly derivable and contextually important

    Extends BaseFact conceptually with inference justification.

    Attributes:
        fact_id: UUID identifying this fact.
        fact_type: Always "IMPLIED_FACT" for this type.
        canonical_text: Normalized fact text after inference.
        subject: The subject entity of the triplet.
        predicate: The inferred relation.
        object: The object entity of the triplet.
        source_contexts: Source locations that support the inference.
        confidence: Confidence score 0.0-1.0.
        extracted_at: ISO 8601 timestamp.
        validation_flags: ValidationFlags tracking validation status.
        inference_justification: Explanation of how fact was derived.
        derived_from_fact_ids: List of base fact IDs used for inference.

    Example:
        {
            "fact_id": "550e8400-e29b-41d4-a716-446655440003",
            "fact_type": "IMPLIED_FACT",
            "canonical_text": "Red flowers are on the floor.",
            "subject": "Red flowers",
            "predicate": "are on",
            "object": "the floor",
            "source_contexts": [{
                "doc_id": "doc-001",
                "start_char": 200,
                "end_char": 240,
                "verbatim_text": "red flowers scattered across the floor"
            }],
            "confidence": 0.85,
            "extracted_at": "2025-01-15T10:36:00Z",
            "validation_flags": {
                "grammar_valid": True,
                "inference_valid": True,
                "atomicity_valid": True
            },
            "inference_justification": (
                "Spatial containment inference: 'scattered across' implies 'on'"
            ),
            "derived_from_fact_ids": ["550e8400-e29b-41d4-a716-446655440002"]
        }
    """

    fact_id: str
    fact_type: Literal["IMPLIED_FACT"]
    canonical_text: str
    subject: str
    predicate: str
    object: str
    source_contexts: list[SourceContext]
    confidence: float
    extracted_at: str
    validation_flags: ValidationFlags
    inference_justification: str
    derived_from_fact_ids: list[str]


class EntityDeclaration(TypedDict):
    """Recognition that an entity exists without asserting a relation.

    Per requirements.md lines 595-600, entity declarations:
    - Record that an entity was mentioned in source text
    - Do not assert any predicate or complete triplet
    - Avoid grammatical fabrication to force triplet structure

    Attributes:
        entity_id: UUID identifying this declaration.
        fact_type: Always "ENTITY_DECLARATION" for this type.
        entity_name: The entity as it appears in source.
        source_context: Location where entity was mentioned.
        status: Always "DECLARED" for this type.

    Example:
        {
            "entity_id": "550e8400-e29b-41d4-a716-446655440004",
            "fact_type": "ENTITY_DECLARATION",
            "entity_name": "buffalo sauce",
            "source_context": {
                "doc_id": "doc-001",
                "start_char": 300,
                "end_char": 315,
                "verbatim_text": "also buffalo sauce"
            },
            "status": "DECLARED"
        }
    """

    entity_id: str
    fact_type: Literal["ENTITY_DECLARATION"]
    entity_name: str
    source_context: SourceContext
    status: Literal["DECLARED"]


class AttributeAnnotation(TypedDict):
    """An entity with a modifier but no predicate.

    Per requirements.md lines 601-606, attribute annotations:
    - Record when an entity has a modifier (adjective, adverb)
    - Do not fabricate a copula to create a triplet
    - Preserve the modifier-entity relationship without assertion

    Attributes:
        annotation_id: UUID identifying this annotation.
        fact_type: Always "ATTRIBUTE_ANNOTATION" for this type.
        entity_name: The entity being modified.
        attribute: The modifier/adjective present in source.
        source_context: Location of the attributed entity.

    Example:
        {
            "annotation_id": "550e8400-e29b-41d4-a716-446655440005",
            "fact_type": "ATTRIBUTE_ANNOTATION",
            "entity_name": "buffalo sauce",
            "attribute": "also",
            "source_context": {
                "doc_id": "doc-001",
                "start_char": 300,
                "end_char": 318,
                "verbatim_text": "also buffalo sauce"
            }
        }
    """

    annotation_id: str
    fact_type: Literal["ATTRIBUTE_ANNOTATION"]
    entity_name: str
    attribute: str
    source_context: SourceContext


# =============================================================================
# VALIDATION ARTIFACT MODELS
# =============================================================================


class FabricationAttempt(TypedDict):
    """Record of a grammar fabrication detected and rejected.

    Tracks grammar fabrications (types 1-5) detected by SpaCy validation.
    Per requirements.md lines 507-549, these violations invent syntactic
    structure not present in source text.

    Note: Inference fabrications (types 6-8: INVALID_COREFERENCE,
    UNGROUNDED_IMPLICATION, CONTEXT_BOUNDARY_VIOLATION) are tracked
    separately in InvalidInferenceAttempt.

    Attributes:
        attempt_id: UUID identifying this attempt.
        fabrication_type: One of the 5 grammar fabrication types.
        attempted_fact: The illegal fact that was rejected (BaseFact structure).
        source_span: The span from which fabrication was attempted.
        detection_method: Always "spacy_grammar" for grammar fabrications.
        violation_details: Explanation of why the fact is illegal.
        detected_at: ISO 8601 timestamp when detected.

    Example:
        {
            "attempt_id": "550e8400-e29b-41d4-a716-446655440006",
            "fabrication_type": "HIDDEN_COPULA",
            "attempted_fact": {
                "fact_id": "...",
                "fact_type": "BASE_FACT",
                "canonical_text": "Red flowers are scattered across the pavement.",
                ...
            },
            "source_span": {...},
            "detection_method": "spacy_grammar",
            "violation_details": (
                "Source text uses participial phrase 'scattered', "
                "not predicate. Verb 'are' was added."
            ),
            "detected_at": "2025-01-15T10:40:00Z"
        }
    """

    attempt_id: str
    fabrication_type: Literal[
        "HIDDEN_COPULA",
        "ATTRIBUTE_TO_PROCESS",
        "PRONOUN_CONCORD",
        "TENSE_FABRICATION",
        "FORCED_SUBJECT",
    ]
    attempted_fact: BaseFact
    source_span: Span
    detection_method: Literal["spacy_grammar"]
    violation_details: str
    detected_at: str


class InvalidInferenceAttempt(TypedDict):
    """Record of an inference fabrication detected and rejected.

    Tracks inference fabrications (types 6-8) detected by Opus validation.
    Per requirements.md lines 550-579, these violations claim inferences
    that don't validly follow from base facts.

    Attributes:
        attempt_id: UUID identifying this attempt.
        fabrication_type: One of INVALID_COREFERENCE, UNGROUNDED_IMPLICATION,
            or CONTEXT_BOUNDARY_VIOLATION.
        attempted_inference: The invalid implied fact.
        base_facts_used: IDs of base facts the inference claimed to derive from.
        inference_error: Explanation of why the inference is invalid.
        detected_at: ISO 8601 timestamp when detected.

    Example:
        {
            "attempt_id": "550e8400-e29b-41d4-a716-446655440007",
            "fabrication_type": "INVALID_COREFERENCE",
            "attempted_inference": {...},
            "base_facts_used": ["fact-001", "fact-002"],
            "inference_error": (
                "Number mismatch: 'its' (singular) "
                "cannot refer to 'flowers' (plural)"
            ),
            "detected_at": "2025-01-15T10:41:00Z"
        }
    """

    attempt_id: str
    fabrication_type: Literal[
        "INVALID_COREFERENCE",
        "UNGROUNDED_IMPLICATION",
        "CONTEXT_BOUNDARY_VIOLATION",
    ]
    attempted_inference: ImpliedFact
    base_facts_used: list[str]
    inference_error: str
    detected_at: str


class ReconstructionFailure(TypedDict):
    """Record of a failed reconstruction attempt.

    Per requirements.md lines 44-53, reconstruction is an explanation test:
    - Attempts to re-explain original text using current understanding
    - Succeeds only if exact original substring can be reproduced byte-for-byte
    - Failure means current understanding is insufficient

    Attributes:
        failure_id: UUID identifying this failure.
        span_id: ID of the span that failed reconstruction.
        original_text: Verbatim T(S) - the text being reconstructed.
        reconstructed_text: R(S) - Opus's reconstruction attempt.
        uncovered_phrases: Exact substrings not covered by any fact.
        uncovered_offsets: Character ranges of uncovered text as (start, end) tuples.
        facts_used: IDs of facts used in reconstruction attempt.
        proof_trace: Opus's step-by-step reconstruction reasoning.
        substitutions_used: Token substitutions applied during reconstruction.
        failed_at: ISO 8601 timestamp when failure occurred.

    Example:
        {
            "failure_id": "550e8400-e29b-41d4-a716-446655440008",
            "span_id": "550e8400-e29b-41d4-a716-446655440000",
            "original_text": "The device supports Bluetooth and Wi-Fi connectivity.",
            "reconstructed_text": "The device supports Bluetooth connectivity.",
            "uncovered_phrases": ["and Wi-Fi"],
            "uncovered_offsets": [(32, 42)],
            "facts_used": ["fact-001"],
            "proof_trace": (
                "Applied fact-001: 'The device supports Bluetooth connectivity.' "
                "Missing: conjunction and second connectivity type."
            ),
            "substitutions_used": {},
            "failed_at": "2025-01-15T10:45:00Z"
        }
    """

    failure_id: str
    span_id: str
    original_text: str
    reconstructed_text: str
    uncovered_phrases: list[str]
    uncovered_offsets: list[tuple[int, int]]
    facts_used: list[str]
    proof_trace: str
    substitutions_used: dict[str, str]
    failed_at: str


class ClarificationQuestion(TypedDict):
    """Request for human clarification when reconstruction remains impossible.

    Per requirements.md lines 53, 94-95, clarification questions:
    - Emitted when progress test shows no improvement after bounded attempts
    - Are honest admissions of non-understanding
    - Are required outputs, not recovery mechanisms

    Attributes:
        question_id: UUID identifying this question.
        doc_id: Document where the unclear region exists.
        start_char: Inclusive start character offset of unclear region.
        end_char: Exclusive end character offset of unclear region.
        verbatim_text: The text including unanchored portions.
        failure_statement: Why the system cannot understand this region.
        failure_type: "anchoring_failure" or "derivation_impossibility".
        bounded_attempts_count: Number of anchoring iterations before giving up.
        author_response: Human response (empty initially, filled later).
        emitted_at: ISO 8601 timestamp when question was emitted.

    Example:
        {
            "question_id": "550e8400-e29b-41d4-a716-446655440009",
            "doc_id": "doc-001",
            "start_char": 500,
            "end_char": 550,
            "verbatim_text": "erupting from the palms of its hands",
            "failure_statement": (
                "Cannot determine referent for 'its' - "
                "no singular entity in context"
            ),
            "failure_type": "anchoring_failure",
            "bounded_attempts_count": 3,
            "author_response": "",
            "emitted_at": "2025-01-15T10:50:00Z"
        }
    """

    question_id: str
    doc_id: str
    start_char: int
    end_char: int
    verbatim_text: str
    failure_statement: str
    failure_type: Literal["anchoring_failure", "derivation_impossibility"]
    bounded_attempts_count: int
    author_response: str
    emitted_at: str


# =============================================================================
# ANCHORING AND PROGRESS TRACKING MODELS
# =============================================================================


class AnchoringAttempt(TypedDict):
    """Record of an attempt to anchor uncovered text via expanded context.

    Per requirements.md lines 86-95, anchoring is the progress test mechanism:
    - Re-attempts extraction over failing region with expanded context
    - If reconstruction improves, continue extraction
    - If no improvement after bounded attempts, emit clarification

    Attributes:
        attempt_id: UUID identifying this attempt.
        span_id: ID of the span being anchored.
        uncovered_phrase: The specific uncovered text being targeted.
        context_expansion_start: Start offset of expanded context window.
        context_expansion_end: End offset of expanded context window.
        existing_facts_searched: IDs of facts checked for anchor points.
        new_facts_extracted: IDs of facts extracted during this attempt.
        uncovered_reduction: Character count reduction in uncovered text.
        succeeded: True if uncovered text shrank.
        attempted_at: ISO 8601 timestamp when attempt occurred.

    Example:
        {
            "attempt_id": "550e8400-e29b-41d4-a716-446655440010",
            "span_id": "550e8400-e29b-41d4-a716-446655440000",
            "uncovered_phrase": "and Wi-Fi",
            "context_expansion_start": 80,
            "context_expansion_end": 280,
            "existing_facts_searched": ["fact-001"],
            "new_facts_extracted": ["fact-003"],
            "uncovered_reduction": 10,
            "succeeded": True,
            "attempted_at": "2025-01-15T10:46:00Z"
        }
    """

    attempt_id: str
    span_id: str
    uncovered_phrase: str
    context_expansion_start: int
    context_expansion_end: int
    existing_facts_searched: list[str]
    new_facts_extracted: list[str]
    uncovered_reduction: int
    succeeded: bool
    attempted_at: str


class ProgressTest(TypedDict):
    """Tracks progress across anchoring attempts for a span.

    Per requirements.md lines 84-95, the progress test determines:
    - Whether anchoring is making progress (uncovered text shrinking)
    - When to emit clarification questions (stalled progress)

    Attributes:
        test_id: UUID identifying this test.
        span_id: ID of the span being tested.
        initial_uncovered_count: Character count of uncovered text at start.
        anchoring_attempts: List of anchoring attempts made.
        final_uncovered_count: Character count after all attempts.
        stalled: True if no reduction after bounded attempts.
        clarification_emitted: True if clarification question was emitted.
        completed_at: ISO 8601 timestamp when test completed.

    Example:
        {
            "test_id": "550e8400-e29b-41d4-a716-446655440011",
            "span_id": "550e8400-e29b-41d4-a716-446655440000",
            "initial_uncovered_count": 25,
            "anchoring_attempts": [...],
            "final_uncovered_count": 0,
            "stalled": False,
            "clarification_emitted": False,
            "completed_at": "2025-01-15T10:48:00Z"
        }
    """

    test_id: str
    span_id: str
    initial_uncovered_count: int
    anchoring_attempts: list[AnchoringAttempt]
    final_uncovered_count: int
    stalled: bool
    clarification_emitted: bool
    completed_at: str


# =============================================================================
# SERIALIZATION AND NORMALIZATION UTILITIES
# =============================================================================


def normalize_canonical_text(text: str) -> str:
    """Normalize fact text for canonical comparison and deduplication.

    Applies the same normalization as fact_store.py lines 148-182:
    1. Unicode normalization (NFC)
    2. Trim leading/trailing whitespace
    3. Collapse internal whitespace to single spaces
    4. Stable punctuation (normalize quotes, dashes)

    Args:
        text: Raw fact text to normalize.

    Returns:
        Normalized text suitable for hashing and comparison.

    Example:
        >>> normalize_canonical_text("  The   device   supports  Wi-Fi.  ")
        'The device supports Wi-Fi.'
    """
    # Unicode normalization (NFC)
    text = unicodedata.normalize("NFC", text)

    # Trim whitespace
    text = text.strip()

    # Collapse internal whitespace
    text = re.sub(r"\s+", " ", text)

    # Stable punctuation: normalize various quote types
    text = text.replace("\u2018", "'")  # Left single quote
    text = text.replace("\u2019", "'")  # Right single quote
    text = text.replace("\u201c", '"')  # Left double quote
    text = text.replace("\u201d", '"')  # Right double quote

    # Normalize dashes
    text = text.replace("\u2013", "-")  # En dash
    text = text.replace("\u2014", "-")  # Em dash

    return text


def compute_fact_hash(
    canonical_text: str,
    subject: str,
    predicate: str,
    obj: str,
) -> str:
    """Compute SHA-256 hash for fact deduplication.

    Creates a deterministic hash from normalized fact components for
    identifying duplicate facts across extraction passes.

    Args:
        canonical_text: Normalized canonical fact text.
        subject: Subject entity of the triplet.
        predicate: Predicate/relation of the triplet.
        obj: Object entity of the triplet.

    Returns:
        Hex digest of SHA-256 hash.

    Example:
        >>> compute_fact_hash(
        ...     "The device supports Bluetooth.", "The device", "supports", "Bluetooth"
        ... )
        'a1b2c3d4...'
    """
    normalized_text = normalize_canonical_text(canonical_text)
    normalized_subject = normalize_canonical_text(subject)
    normalized_predicate = normalize_canonical_text(predicate)
    normalized_object = normalize_canonical_text(obj)

    # Use null byte as delimiter to avoid collisions when components contain pipes
    composite = "\x00".join(
        [normalized_text, normalized_subject, normalized_predicate, normalized_object]
    )
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def create_source_context(
    doc_id: str,
    start_char: int,
    end_char: int,
    canonical_string: str,
) -> SourceContext:
    """Create a source context by extracting verbatim text from canonical string.

    Args:
        doc_id: Document identifier.
        start_char: Inclusive start offset into canonical_string.
        end_char: Exclusive end offset into canonical_string.
        canonical_string: The full canonical UTF-8 string.

    Returns:
        SourceContext with verbatim text extracted.

    Raises:
        ValueError: If offsets are out of bounds.

    Example:
        >>> create_source_context("doc-001", 0, 10, "Hello world!")
        {'doc_id': 'doc-001', 'start_char': 0, 'end_char': 10, 'verbatim_text': 'Hello worl'}
    """
    if start_char < 0 or end_char > len(canonical_string) or start_char >= end_char:
        msg = f"Invalid offsets: start={start_char}, end={end_char}, len={len(canonical_string)}"
        raise ValueError(msg)

    return SourceContext(
        doc_id=doc_id,
        start_char=start_char,
        end_char=end_char,
        verbatim_text=canonical_string[start_char:end_char],
    )


def work_region_to_span(
    region: WorkRegion,
    canonical_string: str,
    span_id: str,
    timestamp: str,
) -> Span:
    """Convert a work region to a span for reconstruction.

    Args:
        region: The work region to convert.
        canonical_string: The full canonical UTF-8 string.
        span_id: UUID for the new span.
        timestamp: ISO 8601 timestamp for created_at/updated_at.

    Returns:
        Span with text extracted from canonical string.

    Raises:
        ValueError: If region offsets are out of bounds.
    """
    start = region["start_char"]
    end = region["end_char"]

    if start < 0 or end > len(canonical_string) or start >= end:
        msg = f"Invalid region offsets: start={start}, end={end}, len={len(canonical_string)}"
        raise ValueError(msg)

    return Span(
        span_id=span_id,
        start_char=start,
        end_char=end,
        state="ATTEMPTABLE",
        text=canonical_string[start:end],
        doc_id=region["doc_id"],
        created_at=timestamp,
        updated_at=timestamp,
    )


# =============================================================================
# CSV SERIALIZATION UTILITIES
# =============================================================================


# CSV column definitions for each model type
SPAN_CSV_COLUMNS = [
    "span_id",
    "start_char",
    "end_char",
    "state",
    "text",
    "doc_id",
    "created_at",
    "updated_at",
]

FACT_CSV_COLUMNS = [
    "fact_id",
    "fact_type",
    "canonical_text",
    "subject",
    "predicate",
    "object",
    "source_contexts_json",  # JSON-encoded list
    "confidence",
    "extracted_at",
    "validation_flags_json",  # JSON-encoded dict
    # ImpliedFact additional fields (may be empty for BaseFact)
    "inference_justification",
    "derived_from_fact_ids_json",  # JSON-encoded list
]

RECONSTRUCTION_FAILURE_CSV_COLUMNS = [
    "failure_id",
    "span_id",
    "original_text",
    "reconstructed_text",
    "uncovered_phrases_json",  # JSON-encoded list
    "uncovered_offsets_json",  # JSON-encoded list of tuples
    "facts_used_json",  # JSON-encoded list
    "proof_trace",
    "substitutions_used_json",  # JSON-encoded dict
    "failed_at",
]

FABRICATION_ATTEMPT_CSV_COLUMNS = [
    "attempt_id",
    "fabrication_type",
    "attempted_fact_json",  # JSON-encoded BaseFact
    "source_span_json",  # JSON-encoded Span
    "detection_method",
    "violation_details",
    "detected_at",
]

CLARIFICATION_QUESTION_CSV_COLUMNS = [
    "question_id",
    "doc_id",
    "start_char",
    "end_char",
    "verbatim_text",
    "failure_statement",
    "failure_type",
    "bounded_attempts_count",
    "author_response",
    "emitted_at",
]

ANCHORING_ATTEMPT_CSV_COLUMNS = [
    "attempt_id",
    "span_id",
    "uncovered_phrase",
    "context_expansion_start",
    "context_expansion_end",
    "existing_facts_searched_json",  # JSON-encoded list
    "new_facts_extracted_json",  # JSON-encoded list
    "uncovered_reduction",
    "succeeded",
    "attempted_at",
]

PROGRESS_TEST_CSV_COLUMNS = [
    "test_id",
    "span_id",
    "initial_uncovered_count",
    "anchoring_attempts_json",  # JSON-encoded list of AnchoringAttempt
    "final_uncovered_count",
    "stalled",
    "clarification_emitted",
    "completed_at",
]

WORK_REGION_CSV_COLUMNS = [
    "region_id",
    "doc_id",
    "start_char",
    "end_char",
    "is_processed",
    "created_at",
]

INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS = [
    "attempt_id",
    "fabrication_type",
    "attempted_inference_json",  # JSON-encoded ImpliedFact
    "base_facts_used_json",  # JSON-encoded list
    "inference_error",
    "detected_at",
]

ENTITY_DECLARATION_CSV_COLUMNS = [
    "entity_id",
    "fact_type",
    "entity_name",
    "source_context_json",  # JSON-encoded SourceContext
    "status",
]

ATTRIBUTE_ANNOTATION_CSV_COLUMNS = [
    "annotation_id",
    "fact_type",
    "entity_name",
    "attribute",
    "source_context_json",  # JSON-encoded SourceContext
]


def _to_json_str(value: Any) -> str:
    """Convert a value to JSON string for CSV storage.

    Args:
        value: Any JSON-serializable value.

    Returns:
        JSON string representation.
    """
    return json.dumps(value, ensure_ascii=False)


def span_to_csv_row(span: Span) -> dict[str, str]:
    """Flatten Span to CSV-compatible dict.

    Args:
        span: Span TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "span_id": span["span_id"],
        "start_char": str(span["start_char"]),
        "end_char": str(span["end_char"]),
        "state": span["state"],
        "text": span["text"],
        "doc_id": span["doc_id"],
        "created_at": span["created_at"],
        "updated_at": span["updated_at"],
    }


def fact_to_csv_row(fact: BaseFact | ImpliedFact) -> dict[str, str]:
    """Flatten fact to CSV-compatible dict with JSON-encoded nested fields.

    Args:
        fact: BaseFact or ImpliedFact TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    row = {
        "fact_id": fact["fact_id"],
        "fact_type": fact["fact_type"],
        "canonical_text": fact["canonical_text"],
        "subject": fact["subject"],
        "predicate": fact["predicate"],
        "object": fact["object"],
        "source_contexts_json": _to_json_str(fact["source_contexts"]),
        "confidence": str(fact["confidence"]),
        "extracted_at": fact["extracted_at"],
        "validation_flags_json": _to_json_str(fact["validation_flags"]),
        "inference_justification": "",
        "derived_from_fact_ids_json": "[]",
    }

    # Add ImpliedFact-specific fields if present
    if fact["fact_type"] == "IMPLIED_FACT":
        row["inference_justification"] = fact["inference_justification"]
        row["derived_from_fact_ids_json"] = _to_json_str(fact["derived_from_fact_ids"])

    return row


def reconstruction_failure_to_csv_row(failure: ReconstructionFailure) -> dict[str, str]:
    """Flatten ReconstructionFailure to CSV-compatible dict.

    Args:
        failure: ReconstructionFailure TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "failure_id": failure["failure_id"],
        "span_id": failure["span_id"],
        "original_text": failure["original_text"],
        "reconstructed_text": failure["reconstructed_text"],
        "uncovered_phrases_json": _to_json_str(failure["uncovered_phrases"]),
        "uncovered_offsets_json": _to_json_str(failure["uncovered_offsets"]),
        "facts_used_json": _to_json_str(failure["facts_used"]),
        "proof_trace": failure["proof_trace"],
        "substitutions_used_json": _to_json_str(failure["substitutions_used"]),
        "failed_at": failure["failed_at"],
    }


def fabrication_attempt_to_csv_row(attempt: FabricationAttempt) -> dict[str, str]:
    """Flatten FabricationAttempt to CSV-compatible dict.

    Args:
        attempt: FabricationAttempt TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "attempt_id": attempt["attempt_id"],
        "fabrication_type": attempt["fabrication_type"],
        "attempted_fact_json": _to_json_str(attempt["attempted_fact"]),
        "source_span_json": _to_json_str(attempt["source_span"]),
        "detection_method": attempt["detection_method"],
        "violation_details": attempt["violation_details"],
        "detected_at": attempt["detected_at"],
    }


def clarification_question_to_csv_row(question: ClarificationQuestion) -> dict[str, str]:
    """Flatten ClarificationQuestion to CSV-compatible dict.

    Args:
        question: ClarificationQuestion TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "question_id": question["question_id"],
        "doc_id": question["doc_id"],
        "start_char": str(question["start_char"]),
        "end_char": str(question["end_char"]),
        "verbatim_text": question["verbatim_text"],
        "failure_statement": question["failure_statement"],
        "failure_type": question["failure_type"],
        "bounded_attempts_count": str(question["bounded_attempts_count"]),
        "author_response": question["author_response"],
        "emitted_at": question["emitted_at"],
    }


def anchoring_attempt_to_csv_row(attempt: AnchoringAttempt) -> dict[str, str]:
    """Flatten AnchoringAttempt to CSV-compatible dict.

    Args:
        attempt: AnchoringAttempt TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "attempt_id": attempt["attempt_id"],
        "span_id": attempt["span_id"],
        "uncovered_phrase": attempt["uncovered_phrase"],
        "context_expansion_start": str(attempt["context_expansion_start"]),
        "context_expansion_end": str(attempt["context_expansion_end"]),
        "existing_facts_searched_json": _to_json_str(attempt["existing_facts_searched"]),
        "new_facts_extracted_json": _to_json_str(attempt["new_facts_extracted"]),
        "uncovered_reduction": str(attempt["uncovered_reduction"]),
        "succeeded": str(attempt["succeeded"]).lower(),
        "attempted_at": attempt["attempted_at"],
    }


def progress_test_to_csv_row(test: ProgressTest) -> dict[str, str]:
    """Flatten ProgressTest to CSV-compatible dict.

    Args:
        test: ProgressTest TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "test_id": test["test_id"],
        "span_id": test["span_id"],
        "initial_uncovered_count": str(test["initial_uncovered_count"]),
        "anchoring_attempts_json": _to_json_str(test["anchoring_attempts"]),
        "final_uncovered_count": str(test["final_uncovered_count"]),
        "stalled": str(test["stalled"]).lower(),
        "clarification_emitted": str(test["clarification_emitted"]).lower(),
        "completed_at": test["completed_at"],
    }


def work_region_to_csv_row(region: WorkRegion) -> dict[str, str]:
    """Flatten WorkRegion to CSV-compatible dict.

    Args:
        region: WorkRegion TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "region_id": region["region_id"],
        "doc_id": region["doc_id"],
        "start_char": str(region["start_char"]),
        "end_char": str(region["end_char"]),
        "is_processed": str(region["is_processed"]).lower(),
        "created_at": region["created_at"],
    }


def invalid_inference_attempt_to_csv_row(attempt: InvalidInferenceAttempt) -> dict[str, str]:
    """Flatten InvalidInferenceAttempt to CSV-compatible dict.

    Args:
        attempt: InvalidInferenceAttempt TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "attempt_id": attempt["attempt_id"],
        "fabrication_type": attempt["fabrication_type"],
        "attempted_inference_json": _to_json_str(attempt["attempted_inference"]),
        "base_facts_used_json": _to_json_str(attempt["base_facts_used"]),
        "inference_error": attempt["inference_error"],
        "detected_at": attempt["detected_at"],
    }


def entity_declaration_to_csv_row(declaration: EntityDeclaration) -> dict[str, str]:
    """Flatten EntityDeclaration to CSV-compatible dict.

    Args:
        declaration: EntityDeclaration TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "entity_id": declaration["entity_id"],
        "fact_type": declaration["fact_type"],
        "entity_name": declaration["entity_name"],
        "source_context_json": _to_json_str(declaration["source_context"]),
        "status": declaration["status"],
    }


def attribute_annotation_to_csv_row(annotation: AttributeAnnotation) -> dict[str, str]:
    """Flatten AttributeAnnotation to CSV-compatible dict.

    Args:
        annotation: AttributeAnnotation TypedDict to flatten.

    Returns:
        Dict with string values suitable for CSV writing.
    """
    return {
        "annotation_id": annotation["annotation_id"],
        "fact_type": annotation["fact_type"],
        "entity_name": annotation["entity_name"],
        "attribute": annotation["attribute"],
        "source_context_json": _to_json_str(annotation["source_context"]),
    }


# =============================================================================
# JSON SERIALIZATION UTILITIES
# =============================================================================


def span_to_json(span: Span) -> dict[str, Any]:
    """Convert Span to JSON-serializable dict.

    Args:
        span: Span TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(span)


def fact_to_json(fact: BaseFact | ImpliedFact) -> dict[str, Any]:
    """Convert fact to JSON-serializable dict.

    Args:
        fact: BaseFact or ImpliedFact TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(fact)


def reconstruction_failure_to_json(failure: ReconstructionFailure) -> dict[str, Any]:
    """Convert ReconstructionFailure to JSON-serializable dict.

    Args:
        failure: ReconstructionFailure TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(failure)


def clarification_question_to_json(question: ClarificationQuestion) -> dict[str, Any]:
    """Convert ClarificationQuestion to JSON-serializable dict.

    Args:
        question: ClarificationQuestion TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(question)


def fabrication_attempt_to_json(attempt: FabricationAttempt) -> dict[str, Any]:
    """Convert FabricationAttempt to JSON-serializable dict.

    Args:
        attempt: FabricationAttempt TypedDict.

    Returns:
        Dict ready for JSON serialization with nested data preserved.
    """
    return dict(attempt)


def invalid_inference_attempt_to_json(attempt: InvalidInferenceAttempt) -> dict[str, Any]:
    """Convert InvalidInferenceAttempt to JSON-serializable dict.

    Args:
        attempt: InvalidInferenceAttempt TypedDict.

    Returns:
        Dict ready for JSON serialization with nested data preserved.
    """
    return dict(attempt)


def anchoring_attempt_to_json(attempt: AnchoringAttempt) -> dict[str, Any]:
    """Convert AnchoringAttempt to JSON-serializable dict.

    Args:
        attempt: AnchoringAttempt TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(attempt)


def progress_test_to_json(test: ProgressTest) -> dict[str, Any]:
    """Convert ProgressTest to JSON-serializable dict.

    Args:
        test: ProgressTest TypedDict.

    Returns:
        Dict ready for JSON serialization with nested data preserved.
    """
    return dict(test)


def work_region_to_json(region: WorkRegion) -> dict[str, Any]:
    """Convert WorkRegion to JSON-serializable dict.

    Args:
        region: WorkRegion TypedDict.

    Returns:
        Dict ready for JSON serialization.
    """
    return dict(region)


def entity_declaration_to_json(declaration: EntityDeclaration) -> dict[str, Any]:
    """Convert EntityDeclaration to JSON-serializable dict.

    Args:
        declaration: EntityDeclaration TypedDict.

    Returns:
        Dict ready for JSON serialization with nested data preserved.
    """
    return dict(declaration)


def attribute_annotation_to_json(annotation: AttributeAnnotation) -> dict[str, Any]:
    """Convert AttributeAnnotation to JSON-serializable dict.

    Args:
        annotation: AttributeAnnotation TypedDict.

    Returns:
        Dict ready for JSON serialization with nested data preserved.
    """
    return dict(annotation)


# =============================================================================
# MODEL VALIDATION FUNCTIONS
# =============================================================================


def validate_span_offsets(span: Span, canonical_length: int) -> bool:
    """Validate span offsets are within canonical string bounds.

    Args:
        span: Span to validate.
        canonical_length: Length of the canonical UTF-8 string.

    Returns:
        True if offsets are valid (0 <= start < end <= canonical_length).
    """
    start = span["start_char"]
    end = span["end_char"]
    return 0 <= start < end <= canonical_length


def validate_fact_atomicity(fact: BaseFact) -> tuple[bool, str]:
    """Check that a fact is atomic (no conjunctions or compound statements).

    Per requirements.md lines 382-386, extracted candidates containing
    conjunctions should be flagged for splitting or rejected.

    Args:
        fact: BaseFact to validate.

    Returns:
        Tuple of (is_atomic, error_message). error_message is empty if valid.

    Example:
        >>> validate_fact_atomicity({"canonical_text": "X and Y are enabled", ...})
        (False, "Contains conjunction 'and' - should be split into separate facts")
    """
    text = fact["canonical_text"].lower()

    # Check for common conjunctions that indicate compound facts
    conjunction_patterns = [
        (r"\band\b", "and"),
        (r"\bor\b", "or"),
        (r"\bbut\b", "but"),
        (r"\bas well as\b", "as well as"),
        (r"\bboth\b", "both"),
    ]

    for pattern, name in conjunction_patterns:
        if re.search(pattern, text):
            return (False, f"Contains conjunction '{name}' - should be split into separate facts")

    return (True, "")


def validate_source_context_consistency(
    fact: BaseFact,
    canonical_string: str,
) -> bool:
    """Verify source contexts match canonical string at their offsets.

    Args:
        fact: BaseFact with source_contexts to validate.
        canonical_string: The full canonical UTF-8 string.

    Returns:
        True if all source contexts' verbatim_text matches the canonical string
        at their specified offsets.
    """
    for ctx in fact["source_contexts"]:
        start = ctx["start_char"]
        end = ctx["end_char"]
        verbatim = ctx["verbatim_text"]

        # Check bounds
        if start < 0 or end > len(canonical_string) or start >= end:
            return False

        # Check text matches
        if canonical_string[start:end] != verbatim:
            return False

    return True


def validate_implied_fact_derivation(
    implied: ImpliedFact,
    base_facts: list[BaseFact],
) -> tuple[bool, str]:
    """Validate that an implied fact's derivation is plausible.

    Checks that:
    1. derived_from_fact_ids reference existing base facts
    2. inference_justification is present and not empty/whitespace

    Note: This is a structural check, not a semantic validation of
    whether the inference is logically valid (that requires Opus).

    Args:
        implied: ImpliedFact to validate.
        base_facts: List of available base facts.

    Returns:
        Tuple of (is_valid, error_message). error_message is empty if valid.
    """
    base_fact_ids = {f["fact_id"] for f in base_facts}
    derived_from = implied["derived_from_fact_ids"]

    if not derived_from:
        return (
            False,
            "ImpliedFact has no derived_from_fact_ids - inference must reference base facts",
        )

    missing_ids = [fid for fid in derived_from if fid not in base_fact_ids]
    if missing_ids:
        return (False, f"ImpliedFact references non-existent base facts: {missing_ids}")

    inference_justification = implied["inference_justification"]
    if not inference_justification or not inference_justification.strip():
        return (
            False,
            "ImpliedFact has empty inference_justification - inference must be justified",
        )

    return (True, "")


# =============================================================================
# LIFECYCLE TRANSITION VALIDATORS
# =============================================================================


def can_transition_to_proven(
    span: Span,
    uncovered_count: int,
    proof_trace: str,
) -> bool:
    """Check if a span can transition to PROVEN state.

    Per requirements.md lines 70-73, PROVEN means reconstruction succeeded
    with no uncovered words/phrases remaining.

    Args:
        span: Current span state.
        uncovered_count: Number of uncovered characters after reconstruction.
        proof_trace: The reconstruction proof trace (must be non-empty).

    Returns:
        True if transition to PROVEN is valid.
    """
    if span["state"] != "ATTEMPTABLE":
        return False
    return uncovered_count == 0 and bool(proof_trace.strip())


def can_transition_to_failed(
    span: Span,
    uncovered_count: int,
) -> bool:
    """Check if a span can transition to FAILED state.

    Per requirements.md lines 73-74, FAILED means reconstruction failed
    with uncovered words/phrases remaining.

    Args:
        span: Current span state.
        uncovered_count: Number of uncovered characters after reconstruction.

    Returns:
        True if transition to FAILED is valid.
    """
    if span["state"] != "ATTEMPTABLE":
        return False
    return uncovered_count > 0


def can_transition_to_attemptable(
    span: Span,
    new_facts_extracted: bool,
) -> bool:
    """Check if a span can transition back to ATTEMPTABLE state.

    Per the state machine diagram (lines 38-39), FAILED spans can return
    to ATTEMPTABLE when anchoring extracts new facts. This allows the
    span to be re-evaluated for reconstruction.

    Args:
        span: Current span state.
        new_facts_extracted: Whether anchoring extracted new facts during
            the current attempt.

    Returns:
        True if transition to ATTEMPTABLE is valid.
    """
    if span["state"] != "FAILED":
        return False
    return new_facts_extracted


def can_emit_clarification(progress: ProgressTest) -> bool:
    """Check if a clarification question should be emitted.

    Per requirements.md lines 86-95, clarification is emitted when
    anchoring shows no improvement after bounded attempts.

    Args:
        progress: ProgressTest tracking anchoring attempts.

    Returns:
        True if clarification should be emitted (stalled with no reduction).
    """
    return progress["stalled"] and not progress["clarification_emitted"]
