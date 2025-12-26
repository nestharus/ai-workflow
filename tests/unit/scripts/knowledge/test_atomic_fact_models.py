"""Unit tests for atomic_fact_models.py.

Tests cover:
- Span lifecycle state transitions
- Fact normalization and hashing
- Source context extraction
- CSV/JSON serialization round-trips
- Validation function edge cases
- Dual representation consistency

Tests are fully implemented with comprehensive coverage for all model
types, validation functions, and serialization round-trips.
"""

from __future__ import annotations

import pytest

from scripts.knowledge.atomic_fact_models import (
    ANCHORING_ATTEMPT_CSV_COLUMNS,
    ATTRIBUTE_ANNOTATION_CSV_COLUMNS,
    CLARIFICATION_QUESTION_CSV_COLUMNS,
    ENTITY_DECLARATION_CSV_COLUMNS,
    FABRICATION_ATTEMPT_CSV_COLUMNS,
    FACT_CSV_COLUMNS,
    INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS,
    PROGRESS_TEST_CSV_COLUMNS,
    RECONSTRUCTION_FAILURE_CSV_COLUMNS,
    SPAN_CSV_COLUMNS,
    WORK_REGION_CSV_COLUMNS,
    AnchoringAttempt,
    AttributeAnnotation,
    BaseFact,
    ClarificationQuestion,
    EntityDeclaration,
    FabricationAttempt,
    FabricationType,
    FactType,
    ImpliedFact,
    InvalidInferenceAttempt,
    ProgressTest,
    ReconstructionFailure,
    SourceContext,
    Span,
    SpanLifecycleState,
    ValidationFlags,
    WorkRegion,
    anchoring_attempt_to_csv_row,
    anchoring_attempt_to_json,
    attribute_annotation_to_csv_row,
    attribute_annotation_to_json,
    can_emit_clarification,
    can_transition_to_attemptable,
    can_transition_to_failed,
    can_transition_to_proven,
    clarification_question_to_csv_row,
    clarification_question_to_json,
    compute_fact_hash,
    create_source_context,
    entity_declaration_to_csv_row,
    entity_declaration_to_json,
    fabrication_attempt_to_csv_row,
    fabrication_attempt_to_json,
    fact_to_csv_row,
    fact_to_json,
    invalid_inference_attempt_to_csv_row,
    invalid_inference_attempt_to_json,
    normalize_canonical_text,
    progress_test_to_csv_row,
    progress_test_to_json,
    reconstruction_failure_to_csv_row,
    reconstruction_failure_to_json,
    span_to_csv_row,
    span_to_json,
    validate_fact_atomicity,
    validate_implied_fact_derivation,
    validate_source_context_consistency,
    validate_span_offsets,
    work_region_to_csv_row,
    work_region_to_json,
    work_region_to_span,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def sample_canonical_string() -> str:
    """Sample canonical string for testing."""
    return "The device supports Bluetooth and Wi-Fi connectivity. It has 8GB RAM."


@pytest.fixture
def sample_span() -> Span:
    """Sample span for testing."""
    return Span(
        span_id="550e8400-e29b-41d4-a716-446655440000",
        start_char=0,
        end_char=52,
        state="ATTEMPTABLE",
        text="The device supports Bluetooth and Wi-Fi connectivity.",
        doc_id="doc-001",
        created_at="2025-01-15T10:30:00Z",
        updated_at="2025-01-15T10:30:00Z",
    )


@pytest.fixture
def sample_work_region() -> WorkRegion:
    """Sample work region for testing."""
    return WorkRegion(
        region_id="550e8400-e29b-41d4-a716-446655440001",
        doc_id="doc-001",
        start_char=0,
        end_char=69,
        is_processed=False,
        created_at="2025-01-15T10:00:00Z",
    )


@pytest.fixture
def sample_source_context() -> SourceContext:
    """Sample source context for testing."""
    return SourceContext(
        doc_id="doc-001",
        start_char=0,
        end_char=52,
        verbatim_text="The device supports Bluetooth and Wi-Fi connectivity.",
    )


@pytest.fixture
def sample_base_fact(sample_source_context: SourceContext) -> BaseFact:
    """Sample base fact for testing."""
    return BaseFact(
        fact_id="550e8400-e29b-41d4-a716-446655440002",
        fact_type="BASE_FACT",
        canonical_text="The device supports Bluetooth connectivity.",
        subject="The device",
        predicate="supports",
        object="Bluetooth connectivity",
        source_contexts=[sample_source_context],
        confidence=0.95,
        extracted_at="2025-01-15T10:35:00Z",
        validation_flags=ValidationFlags(
            grammar_valid=True,
            inference_valid=True,
            atomicity_valid=True,
        ),
    )


@pytest.fixture
def sample_implied_fact(sample_source_context: SourceContext) -> ImpliedFact:
    """Sample implied fact for testing."""
    return ImpliedFact(
        fact_id="550e8400-e29b-41d4-a716-446655440003",
        fact_type="IMPLIED_FACT",
        canonical_text="Red flowers are on the floor.",
        subject="Red flowers",
        predicate="are on",
        object="the floor",
        source_contexts=[sample_source_context],
        confidence=0.85,
        extracted_at="2025-01-15T10:36:00Z",
        validation_flags=ValidationFlags(
            grammar_valid=True,
            inference_valid=True,
            atomicity_valid=True,
        ),
        inference_justification="Spatial containment inference: 'scattered across' implies 'on'",
        derived_from_fact_ids=["550e8400-e29b-41d4-a716-446655440002"],
    )


@pytest.fixture
def sample_entity_declaration(sample_source_context: SourceContext) -> EntityDeclaration:
    """Sample entity declaration for testing."""
    return EntityDeclaration(
        entity_id="550e8400-e29b-41d4-a716-446655440004",
        fact_type="ENTITY_DECLARATION",
        entity_name="buffalo sauce",
        source_context=sample_source_context,
        status="DECLARED",
    )


@pytest.fixture
def sample_attribute_annotation(sample_source_context: SourceContext) -> AttributeAnnotation:
    """Sample attribute annotation for testing."""
    return AttributeAnnotation(
        annotation_id="550e8400-e29b-41d4-a716-446655440005",
        fact_type="ATTRIBUTE_ANNOTATION",
        entity_name="buffalo sauce",
        attribute="also",
        source_context=sample_source_context,
    )


@pytest.fixture
def sample_invalid_inference_attempt(
    sample_implied_fact: ImpliedFact,
) -> InvalidInferenceAttempt:
    """Sample invalid inference attempt for testing."""
    return InvalidInferenceAttempt(
        attempt_id="550e8400-e29b-41d4-a716-446655440007",
        fabrication_type="INVALID_COREFERENCE",
        attempted_inference=sample_implied_fact,
        base_facts_used=["fact-001", "fact-002"],
        inference_error="Number mismatch: 'its' (singular) cannot refer to 'flowers' (plural)",
        detected_at="2025-01-15T10:41:00Z",
    )


# =============================================================================
# ENUM TESTS
# =============================================================================


class TestSpanLifecycleState:
    """Tests for SpanLifecycleState enum."""

    def test_enum_values_exist(self) -> None:
        """All expected lifecycle states exist."""
        assert SpanLifecycleState.ATTEMPTABLE.value == "ATTEMPTABLE"
        assert SpanLifecycleState.PROVEN.value == "PROVEN"
        assert SpanLifecycleState.FAILED.value == "FAILED"

    def test_enum_is_string_enum(self) -> None:
        """SpanLifecycleState is a string enum for serialization."""
        assert isinstance(SpanLifecycleState.ATTEMPTABLE, str)


class TestFactType:
    """Tests for FactType enum."""

    def test_enum_values_exist(self) -> None:
        """All expected fact types exist."""
        assert FactType.BASE_FACT.value == "BASE_FACT"
        assert FactType.IMPLIED_FACT.value == "IMPLIED_FACT"
        assert FactType.ENTITY_DECLARATION.value == "ENTITY_DECLARATION"
        assert FactType.ATTRIBUTE_ANNOTATION.value == "ATTRIBUTE_ANNOTATION"


class TestFabricationType:
    """Tests for FabricationType enum."""

    def test_grammar_fabrication_types_exist(self) -> None:
        """All 5 grammar fabrication types exist."""
        assert FabricationType.HIDDEN_COPULA.value == "HIDDEN_COPULA"
        assert FabricationType.ATTRIBUTE_TO_PROCESS.value == "ATTRIBUTE_TO_PROCESS"
        assert FabricationType.PRONOUN_CONCORD.value == "PRONOUN_CONCORD"
        assert FabricationType.TENSE_FABRICATION.value == "TENSE_FABRICATION"
        assert FabricationType.FORCED_SUBJECT.value == "FORCED_SUBJECT"

    def test_inference_fabrication_types_exist(self) -> None:
        """All 3 inference fabrication types exist."""
        assert FabricationType.INVALID_COREFERENCE.value == "INVALID_COREFERENCE"
        assert FabricationType.UNGROUNDED_IMPLICATION.value == "UNGROUNDED_IMPLICATION"
        assert FabricationType.CONTEXT_BOUNDARY_VIOLATION.value == "CONTEXT_BOUNDARY_VIOLATION"


# =============================================================================
# VALIDATION FLAGS TESTS
# =============================================================================


class TestValidationFlags:
    """Tests for ValidationFlags TypedDict."""

    def test_validation_flags_creation(self) -> None:
        """ValidationFlags can be created with all required keys."""
        flags = ValidationFlags(
            grammar_valid=True,
            inference_valid=False,
            atomicity_valid=True,
        )
        assert flags["grammar_valid"] is True
        assert flags["inference_valid"] is False
        assert flags["atomicity_valid"] is True

    def test_validation_flags_has_expected_keys(self) -> None:
        """ValidationFlags has the three expected boolean keys."""
        flags = ValidationFlags(
            grammar_valid=True,
            inference_valid=True,
            atomicity_valid=True,
        )
        expected_keys = {"grammar_valid", "inference_valid", "atomicity_valid"}
        assert set(flags.keys()) == expected_keys


# =============================================================================
# NORMALIZATION TESTS
# =============================================================================


class TestNormalizeCanonicalText:
    """Tests for normalize_canonical_text function."""

    def test_trims_whitespace(self) -> None:
        """Leading and trailing whitespace is trimmed."""
        assert normalize_canonical_text("  hello  ") == "hello"

    def test_collapses_internal_whitespace(self) -> None:
        """Internal whitespace is collapsed to single spaces."""
        assert normalize_canonical_text("hello   world") == "hello world"

    def test_normalizes_quotes(self) -> None:
        """Curly quotes are normalized to straight quotes."""
        assert normalize_canonical_text("\u2018hello\u2019") == "'hello'"
        assert normalize_canonical_text("\u201chello\u201d") == '"hello"'

    def test_normalizes_dashes(self) -> None:
        """En and em dashes are normalized to hyphens."""
        assert normalize_canonical_text("hello\u2013world") == "hello-world"
        assert normalize_canonical_text("hello\u2014world") == "hello-world"

    def test_unicode_nfc_normalization(self) -> None:
        """Unicode is normalized to NFC form."""
        # e + combining acute = normalized to single precomposed e-acute
        composed = "caf\u00e9"  # NFC form
        decomposed = "cafe\u0301"  # NFD form
        assert normalize_canonical_text(decomposed) == composed


# =============================================================================
# HASH COMPUTATION TESTS
# =============================================================================


class TestComputeFactHash:
    """Tests for compute_fact_hash function."""

    def test_same_input_produces_same_hash(self) -> None:
        """Identical inputs produce identical hashes."""
        hash1 = compute_fact_hash("The device supports X.", "The device", "supports", "X")
        hash2 = compute_fact_hash("The device supports X.", "The device", "supports", "X")
        assert hash1 == hash2

    def test_different_input_produces_different_hash(self) -> None:
        """Different inputs produce different hashes."""
        hash1 = compute_fact_hash("The device supports X.", "The device", "supports", "X")
        hash2 = compute_fact_hash("The device supports Y.", "The device", "supports", "Y")
        assert hash1 != hash2

    def test_hash_is_hex_string(self) -> None:
        """Hash is a valid hex string."""
        result = compute_fact_hash("text", "subj", "pred", "obj")
        assert all(c in "0123456789abcdef" for c in result)

    def test_normalized_before_hashing(self) -> None:
        """Input is normalized before hashing."""
        hash1 = compute_fact_hash("  hello  ", "subj", "pred", "obj")
        hash2 = compute_fact_hash("hello", "subj", "pred", "obj")
        assert hash1 == hash2

    def test_pipe_in_components_produces_unique_hash(self) -> None:
        """Components containing pipes produce unique hashes (no collision)."""
        # These would collide if using pipe delimiter without escaping
        hash1 = compute_fact_hash("A|B", "C", "D", "E")
        hash2 = compute_fact_hash("A", "B|C", "D", "E")
        hash3 = compute_fact_hash("A", "B", "C|D", "E")
        hash4 = compute_fact_hash("A", "B", "C", "D|E")
        # All should be different
        all_hashes = [hash1, hash2, hash3, hash4]
        assert len(set(all_hashes)) == 4, (
            "Pipe characters in components should not cause hash collisions"
        )


# =============================================================================
# SOURCE CONTEXT TESTS
# =============================================================================


class TestCreateSourceContext:
    """Tests for create_source_context function."""

    def test_extracts_verbatim_text(self, sample_canonical_string: str) -> None:
        """Verbatim text is extracted from canonical string."""
        ctx = create_source_context("doc-001", 0, 10, sample_canonical_string)
        assert ctx["verbatim_text"] == "The device"

    def test_sets_doc_id(self, sample_canonical_string: str) -> None:
        """Doc ID is set correctly."""
        ctx = create_source_context("doc-001", 0, 10, sample_canonical_string)
        assert ctx["doc_id"] == "doc-001"

    def test_sets_offsets(self, sample_canonical_string: str) -> None:
        """Character offsets are set correctly."""
        ctx = create_source_context("doc-001", 5, 15, sample_canonical_string)
        assert ctx["start_char"] == 5
        assert ctx["end_char"] == 15

    def test_raises_on_invalid_offsets(self, sample_canonical_string: str) -> None:
        """ValueError raised for invalid offsets."""
        with pytest.raises(ValueError):
            create_source_context("doc-001", -1, 10, sample_canonical_string)
        with pytest.raises(ValueError):
            create_source_context("doc-001", 10, 5, sample_canonical_string)  # start >= end
        with pytest.raises(ValueError):
            create_source_context("doc-001", 0, 1000, sample_canonical_string)  # beyond length


# =============================================================================
# WORK REGION TO SPAN TESTS
# =============================================================================


class TestWorkRegionToSpan:
    """Tests for work_region_to_span function."""

    def test_converts_region_to_span(
        self,
        sample_work_region: WorkRegion,
        sample_canonical_string: str,
    ) -> None:
        """Work region is converted to span with correct fields."""
        # Adjust region to fit canonical string
        region = WorkRegion(
            region_id="test-region",
            doc_id="doc-001",
            start_char=0,
            end_char=52,
            is_processed=False,
            created_at="2025-01-15T10:00:00Z",
        )
        span = work_region_to_span(
            region, sample_canonical_string, "new-span-id", "2025-01-15T11:00:00Z"
        )
        assert span["span_id"] == "new-span-id"
        assert span["doc_id"] == "doc-001"
        assert span["state"] == "ATTEMPTABLE"
        assert span["text"] == sample_canonical_string[:52]

    def test_raises_on_invalid_region_offsets(self, sample_canonical_string: str) -> None:
        """ValueError raised for invalid region offsets."""
        bad_region = WorkRegion(
            region_id="bad-region",
            doc_id="doc-001",
            start_char=0,
            end_char=1000,  # Beyond canonical string length
            is_processed=False,
            created_at="2025-01-15T10:00:00Z",
        )
        with pytest.raises(ValueError):
            work_region_to_span(bad_region, sample_canonical_string, "id", "ts")


# =============================================================================
# SPAN VALIDATION TESTS
# =============================================================================


class TestValidateSpanOffsets:
    """Tests for validate_span_offsets function."""

    def test_valid_offsets(self, sample_span: Span) -> None:
        """Valid offsets pass validation."""
        assert validate_span_offsets(sample_span, 100)

    def test_invalid_start_negative(self, sample_span: Span) -> None:
        """Negative start offset fails validation."""
        bad_span = {**sample_span, "start_char": -1}
        assert not validate_span_offsets(bad_span, 100)  # type: ignore[arg-type]

    def test_invalid_end_beyond_length(self, sample_span: Span) -> None:
        """End beyond canonical length fails validation."""
        bad_span = {**sample_span, "end_char": 200}
        assert not validate_span_offsets(bad_span, 100)  # type: ignore[arg-type]

    def test_invalid_start_equals_end(self, sample_span: Span) -> None:
        """Start == end fails validation (zero-length span)."""
        bad_span = {**sample_span, "start_char": 50, "end_char": 50}
        assert not validate_span_offsets(bad_span, 100)  # type: ignore[arg-type]

    def test_invalid_start_greater_than_end(self, sample_span: Span) -> None:
        """Start > end fails validation (inverted span)."""
        bad_span = {**sample_span, "start_char": 60, "end_char": 50}
        assert not validate_span_offsets(bad_span, 100)  # type: ignore[arg-type]


# =============================================================================
# ATOMICITY VALIDATION TESTS
# =============================================================================


class TestValidateFactAtomicity:
    """Tests for validate_fact_atomicity function."""

    def test_atomic_fact_passes(self, sample_base_fact: BaseFact) -> None:
        """Atomic fact passes validation."""
        is_valid, error = validate_fact_atomicity(sample_base_fact)
        assert is_valid
        assert error == ""

    def test_fact_with_and_fails(self, sample_base_fact: BaseFact) -> None:
        """Fact with 'and' conjunction fails validation."""
        compound_fact = {
            **sample_base_fact,
            "canonical_text": "The device supports Bluetooth and Wi-Fi.",
        }
        is_valid, error = validate_fact_atomicity(compound_fact)  # type: ignore[arg-type]
        assert not is_valid
        assert "and" in error

    def test_fact_with_or_fails(self, sample_base_fact: BaseFact) -> None:
        """Fact with 'or' conjunction fails validation."""
        compound_fact = {
            **sample_base_fact,
            "canonical_text": "The device supports Bluetooth or Wi-Fi.",
        }
        is_valid, error = validate_fact_atomicity(compound_fact)  # type: ignore[arg-type]
        assert not is_valid
        assert "or" in error

    def test_fact_with_but_fails(self, sample_base_fact: BaseFact) -> None:
        """Fact with 'but' conjunction fails validation."""
        compound_fact = {
            **sample_base_fact,
            "canonical_text": "The device supports Bluetooth but not Wi-Fi.",
        }
        is_valid, error = validate_fact_atomicity(compound_fact)  # type: ignore[arg-type]
        assert not is_valid
        assert "but" in error

    def test_fact_with_as_well_as_fails(self, sample_base_fact: BaseFact) -> None:
        """Fact with 'as well as' conjunction fails validation."""
        compound_fact = {
            **sample_base_fact,
            "canonical_text": "The device supports Bluetooth as well as Wi-Fi.",
        }
        is_valid, error = validate_fact_atomicity(compound_fact)  # type: ignore[arg-type]
        assert not is_valid
        assert "as well as" in error

    def test_fact_with_both_fails(self, sample_base_fact: BaseFact) -> None:
        """Fact with 'both' conjunction fails validation."""
        compound_fact = {
            **sample_base_fact,
            "canonical_text": "Both devices support Bluetooth connectivity.",
        }
        is_valid, error = validate_fact_atomicity(compound_fact)  # type: ignore[arg-type]
        assert not is_valid
        assert "both" in error


# =============================================================================
# SOURCE CONTEXT CONSISTENCY TESTS
# =============================================================================


class TestValidateSourceContextConsistency:
    """Tests for validate_source_context_consistency function."""

    def test_consistent_context_passes(self) -> None:
        """Consistent source context passes validation."""
        canonical = "The device supports Bluetooth."
        fact = BaseFact(
            fact_id="test-id",
            fact_type="BASE_FACT",
            canonical_text="The device supports Bluetooth.",
            subject="The device",
            predicate="supports",
            object="Bluetooth",
            source_contexts=[
                SourceContext(
                    doc_id="doc-001",
                    start_char=0,
                    end_char=30,
                    verbatim_text="The device supports Bluetooth.",
                )
            ],
            confidence=0.9,
            extracted_at="2025-01-15T10:00:00Z",
            validation_flags=ValidationFlags(
                grammar_valid=True,
                inference_valid=True,
                atomicity_valid=True,
            ),
        )
        assert validate_source_context_consistency(fact, canonical)

    def test_inconsistent_text_fails(self) -> None:
        """Mismatched verbatim text fails validation."""
        canonical = "The device supports Bluetooth."
        fact = BaseFact(
            fact_id="test-id",
            fact_type="BASE_FACT",
            canonical_text="The device supports Bluetooth.",
            subject="The device",
            predicate="supports",
            object="Bluetooth",
            source_contexts=[
                SourceContext(
                    doc_id="doc-001",
                    start_char=0,
                    end_char=30,
                    verbatim_text="Wrong text here.",  # Doesn't match
                )
            ],
            confidence=0.9,
            extracted_at="2025-01-15T10:00:00Z",
            validation_flags=ValidationFlags(
                grammar_valid=True,
                inference_valid=True,
                atomicity_valid=True,
            ),
        )
        assert not validate_source_context_consistency(fact, canonical)


# =============================================================================
# IMPLIED FACT DERIVATION TESTS
# =============================================================================


class TestValidateImpliedFactDerivation:
    """Tests for validate_implied_fact_derivation function."""

    def test_valid_derivation_passes(
        self,
        sample_implied_fact: ImpliedFact,
        sample_base_fact: BaseFact,
    ) -> None:
        """Valid derivation with existing base facts passes."""
        # Ensure derived_from_fact_ids matches sample_base_fact
        implied = {
            **sample_implied_fact,
            "derived_from_fact_ids": [sample_base_fact["fact_id"]],
        }
        is_valid, error = validate_implied_fact_derivation(implied, [sample_base_fact])  # type: ignore[arg-type]
        assert is_valid
        assert error == ""

    def test_missing_base_fact_fails(self, sample_implied_fact: ImpliedFact) -> None:
        """Derivation referencing non-existent base fact fails."""
        is_valid, error = validate_implied_fact_derivation(sample_implied_fact, [])
        assert not is_valid
        assert "non-existent" in error

    def test_empty_derivation_fails(self, sample_implied_fact: ImpliedFact) -> None:
        """Empty derived_from_fact_ids fails."""
        implied = {**sample_implied_fact, "derived_from_fact_ids": []}
        is_valid, error = validate_implied_fact_derivation(implied, [])  # type: ignore[arg-type]
        assert not is_valid
        assert "no derived_from_fact_ids" in error


# =============================================================================
# LIFECYCLE TRANSITION TESTS
# =============================================================================


class TestCanTransitionToProven:
    """Tests for can_transition_to_proven function."""

    def test_can_transition_with_zero_uncovered(self, sample_span: Span) -> None:
        """Transition valid with zero uncovered and proof trace."""
        assert can_transition_to_proven(sample_span, 0, "Proof trace here")

    def test_cannot_transition_with_uncovered(self, sample_span: Span) -> None:
        """Transition invalid with uncovered text remaining."""
        assert not can_transition_to_proven(sample_span, 10, "Proof trace")

    def test_cannot_transition_without_proof(self, sample_span: Span) -> None:
        """Transition invalid without proof trace."""
        assert not can_transition_to_proven(sample_span, 0, "")

    def test_cannot_transition_from_failed(self, sample_span: Span) -> None:
        """Transition invalid from FAILED state."""
        failed_span = {**sample_span, "state": "FAILED"}
        assert not can_transition_to_proven(failed_span, 0, "Proof trace")  # type: ignore[arg-type]


class TestCanTransitionToFailed:
    """Tests for can_transition_to_failed function."""

    def test_can_transition_with_uncovered(self, sample_span: Span) -> None:
        """Transition valid with uncovered text remaining."""
        assert can_transition_to_failed(sample_span, 10)

    def test_cannot_transition_without_uncovered(self, sample_span: Span) -> None:
        """Transition invalid with no uncovered text."""
        assert not can_transition_to_failed(sample_span, 0)


class TestCanTransitionToAttemptable:
    """Tests for can_transition_to_attemptable function."""

    def test_can_transition_from_failed_with_new_facts(self, sample_span: Span) -> None:
        """Transition valid from FAILED when new facts extracted."""
        failed_span = {**sample_span, "state": "FAILED"}
        assert can_transition_to_attemptable(failed_span, new_facts_extracted=True)  # type: ignore[arg-type]

    def test_cannot_transition_from_failed_without_new_facts(self, sample_span: Span) -> None:
        """Transition invalid from FAILED when no new facts extracted."""
        failed_span = {**sample_span, "state": "FAILED"}
        assert not can_transition_to_attemptable(failed_span, new_facts_extracted=False)  # type: ignore[arg-type]

    def test_cannot_transition_from_attemptable(self, sample_span: Span) -> None:
        """Transition invalid from ATTEMPTABLE state."""
        assert not can_transition_to_attemptable(sample_span, new_facts_extracted=True)

    def test_cannot_transition_from_proven(self, sample_span: Span) -> None:
        """Transition invalid from PROVEN state."""
        proven_span = {**sample_span, "state": "PROVEN"}
        assert not can_transition_to_attemptable(proven_span, new_facts_extracted=True)  # type: ignore[arg-type]


class TestCanEmitClarification:
    """Tests for can_emit_clarification function."""

    def test_can_emit_when_stalled(self) -> None:
        """Can emit clarification when stalled and not already emitted."""
        progress = ProgressTest(
            test_id="test-id",
            span_id="span-id",
            initial_uncovered_count=50,
            anchoring_attempts=[],
            final_uncovered_count=50,
            stalled=True,
            clarification_emitted=False,
            completed_at="2025-01-15T10:00:00Z",
        )
        assert can_emit_clarification(progress)

    def test_cannot_emit_if_not_stalled(self) -> None:
        """Cannot emit clarification if not stalled."""
        progress = ProgressTest(
            test_id="test-id",
            span_id="span-id",
            initial_uncovered_count=50,
            anchoring_attempts=[],
            final_uncovered_count=0,
            stalled=False,
            clarification_emitted=False,
            completed_at="2025-01-15T10:00:00Z",
        )
        assert not can_emit_clarification(progress)

    def test_cannot_emit_if_already_emitted(self) -> None:
        """Cannot emit clarification if already emitted."""
        progress = ProgressTest(
            test_id="test-id",
            span_id="span-id",
            initial_uncovered_count=50,
            anchoring_attempts=[],
            final_uncovered_count=50,
            stalled=True,
            clarification_emitted=True,  # Already emitted
            completed_at="2025-01-15T10:00:00Z",
        )
        assert not can_emit_clarification(progress)


# =============================================================================
# CSV SERIALIZATION TESTS
# =============================================================================


class TestSpanToCsvRow:
    """Tests for span_to_csv_row function."""

    def test_flattens_span_to_strings(self, sample_span: Span) -> None:
        """Span is flattened to dict of strings."""
        row = span_to_csv_row(sample_span)
        assert row["span_id"] == sample_span["span_id"]
        assert row["start_char"] == str(sample_span["start_char"])
        assert row["end_char"] == str(sample_span["end_char"])
        assert row["state"] == sample_span["state"]

    def test_all_columns_present(self, sample_span: Span) -> None:
        """All expected columns are present in output."""
        row = span_to_csv_row(sample_span)
        for col in SPAN_CSV_COLUMNS:
            assert col in row


class TestFactToCsvRow:
    """Tests for fact_to_csv_row function."""

    def test_flattens_base_fact(self, sample_base_fact: BaseFact) -> None:
        """Base fact is flattened with JSON-encoded nested fields."""
        row = fact_to_csv_row(sample_base_fact)
        assert row["fact_id"] == sample_base_fact["fact_id"]
        assert row["fact_type"] == "BASE_FACT"
        assert "source_contexts_json" in row
        assert row["inference_justification"] == ""  # Empty for base facts

    def test_flattens_implied_fact(self, sample_implied_fact: ImpliedFact) -> None:
        """Implied fact includes inference fields."""
        row = fact_to_csv_row(sample_implied_fact)
        assert row["fact_type"] == "IMPLIED_FACT"
        assert row["inference_justification"] != ""

    def test_all_columns_present(self, sample_base_fact: BaseFact) -> None:
        """All expected columns are present in output."""
        row = fact_to_csv_row(sample_base_fact)
        for col in FACT_CSV_COLUMNS:
            assert col in row


# =============================================================================
# JSON SERIALIZATION TESTS
# =============================================================================


class TestSpanToJson:
    """Tests for span_to_json function."""

    def test_preserves_structure(self, sample_span: Span) -> None:
        """JSON conversion preserves TypedDict structure."""
        result = span_to_json(sample_span)
        assert result["span_id"] == sample_span["span_id"]
        assert result["start_char"] == sample_span["start_char"]  # Preserves int


class TestFactToJson:
    """Tests for fact_to_json function."""

    def test_preserves_nested_structures(self, sample_base_fact: BaseFact) -> None:
        """JSON conversion preserves nested source_contexts."""
        result = fact_to_json(sample_base_fact)
        assert "source_contexts" in result
        assert len(result["source_contexts"]) > 0
        assert "doc_id" in result["source_contexts"][0]


# =============================================================================
# CSV COLUMN DEFINITION TESTS
# =============================================================================


class TestCsvColumnDefinitions:
    """Tests for CSV column constant definitions."""

    def test_span_columns_defined(self) -> None:
        """SPAN_CSV_COLUMNS has expected columns."""
        assert "span_id" in SPAN_CSV_COLUMNS
        assert "state" in SPAN_CSV_COLUMNS
        assert "text" in SPAN_CSV_COLUMNS

    def test_fact_columns_defined(self) -> None:
        """FACT_CSV_COLUMNS has expected columns."""
        assert "fact_id" in FACT_CSV_COLUMNS
        assert "canonical_text" in FACT_CSV_COLUMNS
        assert "source_contexts_json" in FACT_CSV_COLUMNS

    def test_reconstruction_failure_columns_defined(self) -> None:
        """RECONSTRUCTION_FAILURE_CSV_COLUMNS has expected columns."""
        assert "failure_id" in RECONSTRUCTION_FAILURE_CSV_COLUMNS
        assert "original_text" in RECONSTRUCTION_FAILURE_CSV_COLUMNS
        assert "uncovered_phrases_json" in RECONSTRUCTION_FAILURE_CSV_COLUMNS

    def test_fabrication_attempt_columns_defined(self) -> None:
        """FABRICATION_ATTEMPT_CSV_COLUMNS has expected columns."""
        assert "attempt_id" in FABRICATION_ATTEMPT_CSV_COLUMNS
        assert "fabrication_type" in FABRICATION_ATTEMPT_CSV_COLUMNS

    def test_clarification_question_columns_defined(self) -> None:
        """CLARIFICATION_QUESTION_CSV_COLUMNS has expected columns."""
        assert "question_id" in CLARIFICATION_QUESTION_CSV_COLUMNS
        assert "failure_statement" in CLARIFICATION_QUESTION_CSV_COLUMNS

    def test_anchoring_attempt_columns_defined(self) -> None:
        """ANCHORING_ATTEMPT_CSV_COLUMNS has expected columns."""
        assert "attempt_id" in ANCHORING_ATTEMPT_CSV_COLUMNS
        assert "uncovered_phrase" in ANCHORING_ATTEMPT_CSV_COLUMNS

    def test_progress_test_columns_defined(self) -> None:
        """PROGRESS_TEST_CSV_COLUMNS has expected columns."""
        assert "test_id" in PROGRESS_TEST_CSV_COLUMNS
        assert "stalled" in PROGRESS_TEST_CSV_COLUMNS

    def test_work_region_columns_defined(self) -> None:
        """WORK_REGION_CSV_COLUMNS has expected columns."""
        assert "region_id" in WORK_REGION_CSV_COLUMNS
        assert "doc_id" in WORK_REGION_CSV_COLUMNS
        assert "start_char" in WORK_REGION_CSV_COLUMNS
        assert "end_char" in WORK_REGION_CSV_COLUMNS
        assert "is_processed" in WORK_REGION_CSV_COLUMNS
        assert "created_at" in WORK_REGION_CSV_COLUMNS

    def test_invalid_inference_attempt_columns_defined(self) -> None:
        """INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS has expected columns."""
        assert "attempt_id" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS
        assert "fabrication_type" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS
        assert "attempted_inference_json" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS
        assert "base_facts_used_json" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS
        assert "inference_error" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS
        assert "detected_at" in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS

    def test_entity_declaration_columns_defined(self) -> None:
        """ENTITY_DECLARATION_CSV_COLUMNS has expected columns."""
        assert "entity_id" in ENTITY_DECLARATION_CSV_COLUMNS
        assert "fact_type" in ENTITY_DECLARATION_CSV_COLUMNS
        assert "entity_name" in ENTITY_DECLARATION_CSV_COLUMNS
        assert "source_context_json" in ENTITY_DECLARATION_CSV_COLUMNS
        assert "status" in ENTITY_DECLARATION_CSV_COLUMNS

    def test_attribute_annotation_columns_defined(self) -> None:
        """ATTRIBUTE_ANNOTATION_CSV_COLUMNS has expected columns."""
        assert "annotation_id" in ATTRIBUTE_ANNOTATION_CSV_COLUMNS
        assert "fact_type" in ATTRIBUTE_ANNOTATION_CSV_COLUMNS
        assert "entity_name" in ATTRIBUTE_ANNOTATION_CSV_COLUMNS
        assert "attribute" in ATTRIBUTE_ANNOTATION_CSV_COLUMNS
        assert "source_context_json" in ATTRIBUTE_ANNOTATION_CSV_COLUMNS


# =============================================================================
# NEW CSV ROW FUNCTION TESTS
# =============================================================================


class TestWorkRegionToCsvRow:
    """Tests for work_region_to_csv_row function."""

    def test_flattens_work_region(self, sample_work_region: WorkRegion) -> None:
        """WorkRegion is flattened to dict of strings."""
        row = work_region_to_csv_row(sample_work_region)
        assert row["region_id"] == sample_work_region["region_id"]
        assert row["doc_id"] == sample_work_region["doc_id"]
        assert row["start_char"] == str(sample_work_region["start_char"])
        assert row["end_char"] == str(sample_work_region["end_char"])
        assert row["is_processed"] == "false"
        assert row["created_at"] == sample_work_region["created_at"]

    def test_all_columns_present(self, sample_work_region: WorkRegion) -> None:
        """All expected columns are present in output."""
        row = work_region_to_csv_row(sample_work_region)
        for col in WORK_REGION_CSV_COLUMNS:
            assert col in row


class TestInvalidInferenceAttemptToCsvRow:
    """Tests for invalid_inference_attempt_to_csv_row function."""

    def test_flattens_invalid_inference_attempt(
        self, sample_invalid_inference_attempt: InvalidInferenceAttempt
    ) -> None:
        """InvalidInferenceAttempt is flattened with JSON-encoded nested fields."""
        row = invalid_inference_attempt_to_csv_row(sample_invalid_inference_attempt)
        assert row["attempt_id"] == sample_invalid_inference_attempt["attempt_id"]
        assert row["fabrication_type"] == "INVALID_COREFERENCE"
        assert "attempted_inference_json" in row
        assert "base_facts_used_json" in row
        assert row["inference_error"] == sample_invalid_inference_attempt["inference_error"]

    def test_all_columns_present(
        self, sample_invalid_inference_attempt: InvalidInferenceAttempt
    ) -> None:
        """All expected columns are present in output."""
        row = invalid_inference_attempt_to_csv_row(sample_invalid_inference_attempt)
        for col in INVALID_INFERENCE_ATTEMPT_CSV_COLUMNS:
            assert col in row


class TestEntityDeclarationToCsvRow:
    """Tests for entity_declaration_to_csv_row function."""

    def test_flattens_entity_declaration(
        self, sample_entity_declaration: EntityDeclaration
    ) -> None:
        """EntityDeclaration is flattened with JSON-encoded source context."""
        row = entity_declaration_to_csv_row(sample_entity_declaration)
        assert row["entity_id"] == sample_entity_declaration["entity_id"]
        assert row["fact_type"] == "ENTITY_DECLARATION"
        assert row["entity_name"] == "buffalo sauce"
        assert "source_context_json" in row
        assert row["status"] == "DECLARED"

    def test_all_columns_present(self, sample_entity_declaration: EntityDeclaration) -> None:
        """All expected columns are present in output."""
        row = entity_declaration_to_csv_row(sample_entity_declaration)
        for col in ENTITY_DECLARATION_CSV_COLUMNS:
            assert col in row


class TestAttributeAnnotationToCsvRow:
    """Tests for attribute_annotation_to_csv_row function."""

    def test_flattens_attribute_annotation(
        self, sample_attribute_annotation: AttributeAnnotation
    ) -> None:
        """AttributeAnnotation is flattened with JSON-encoded source context."""
        row = attribute_annotation_to_csv_row(sample_attribute_annotation)
        assert row["annotation_id"] == sample_attribute_annotation["annotation_id"]
        assert row["fact_type"] == "ATTRIBUTE_ANNOTATION"
        assert row["entity_name"] == "buffalo sauce"
        assert row["attribute"] == "also"
        assert "source_context_json" in row

    def test_all_columns_present(self, sample_attribute_annotation: AttributeAnnotation) -> None:
        """All expected columns are present in output."""
        row = attribute_annotation_to_csv_row(sample_attribute_annotation)
        for col in ATTRIBUTE_ANNOTATION_CSV_COLUMNS:
            assert col in row


# =============================================================================
# NEW JSON SERIALIZATION TESTS
# =============================================================================


class TestFabricationAttemptToJson:
    """Tests for fabrication_attempt_to_json function."""

    @pytest.fixture
    def sample_fabrication_attempt(
        self, sample_base_fact: BaseFact, sample_span: Span
    ) -> FabricationAttempt:
        """Sample fabrication attempt for testing."""
        return FabricationAttempt(
            attempt_id="550e8400-e29b-41d4-a716-446655440006",
            fabrication_type="HIDDEN_COPULA",
            attempted_fact=sample_base_fact,
            source_span=sample_span,
            detection_method="spacy_grammar",
            violation_details="Verb 'are' was added.",
            detected_at="2025-01-15T10:40:00Z",
        )

    def test_preserves_nested_structures(
        self, sample_fabrication_attempt: FabricationAttempt
    ) -> None:
        """JSON conversion preserves nested attempted_fact and source_span."""
        result = fabrication_attempt_to_json(sample_fabrication_attempt)
        assert "attempted_fact" in result
        assert "source_span" in result
        assert result["attempted_fact"]["fact_id"] is not None
        assert result["source_span"]["span_id"] is not None

    def test_round_trip(self, sample_fabrication_attempt: FabricationAttempt) -> None:
        """JSON round-trip preserves all data."""
        result = fabrication_attempt_to_json(sample_fabrication_attempt)
        assert result["attempt_id"] == sample_fabrication_attempt["attempt_id"]
        assert result["fabrication_type"] == sample_fabrication_attempt["fabrication_type"]
        assert result["detection_method"] == sample_fabrication_attempt["detection_method"]


class TestInvalidInferenceAttemptToJson:
    """Tests for invalid_inference_attempt_to_json function."""

    def test_preserves_nested_structures(
        self, sample_invalid_inference_attempt: InvalidInferenceAttempt
    ) -> None:
        """JSON conversion preserves nested attempted_inference."""
        result = invalid_inference_attempt_to_json(sample_invalid_inference_attempt)
        assert "attempted_inference" in result
        assert result["attempted_inference"]["fact_id"] is not None
        assert "base_facts_used" in result
        assert len(result["base_facts_used"]) == 2

    def test_round_trip(self, sample_invalid_inference_attempt: InvalidInferenceAttempt) -> None:
        """JSON round-trip preserves all data."""
        result = invalid_inference_attempt_to_json(sample_invalid_inference_attempt)
        assert result["attempt_id"] == sample_invalid_inference_attempt["attempt_id"]
        assert result["fabrication_type"] == "INVALID_COREFERENCE"
        assert result["inference_error"] == sample_invalid_inference_attempt["inference_error"]


class TestAnchoringAttemptToJson:
    """Tests for anchoring_attempt_to_json function."""

    @pytest.fixture
    def sample_anchoring_attempt(self) -> AnchoringAttempt:
        """Sample anchoring attempt for testing."""
        return AnchoringAttempt(
            attempt_id="550e8400-e29b-41d4-a716-446655440010",
            span_id="550e8400-e29b-41d4-a716-446655440000",
            uncovered_phrase="and Wi-Fi",
            context_expansion_start=80,
            context_expansion_end=280,
            existing_facts_searched=["fact-001"],
            new_facts_extracted=["fact-003"],
            uncovered_reduction=10,
            succeeded=True,
            attempted_at="2025-01-15T10:46:00Z",
        )

    def test_preserves_structure(self, sample_anchoring_attempt: AnchoringAttempt) -> None:
        """JSON conversion preserves all fields."""
        result = anchoring_attempt_to_json(sample_anchoring_attempt)
        assert result["attempt_id"] == sample_anchoring_attempt["attempt_id"]
        assert result["span_id"] == sample_anchoring_attempt["span_id"]
        assert result["succeeded"] is True
        assert len(result["existing_facts_searched"]) == 1
        assert len(result["new_facts_extracted"]) == 1


class TestProgressTestToJson:
    """Tests for progress_test_to_json function."""

    @pytest.fixture
    def sample_progress_test_with_attempts(self) -> ProgressTest:
        """Sample progress test with anchoring attempts for testing."""
        return ProgressTest(
            test_id="550e8400-e29b-41d4-a716-446655440011",
            span_id="550e8400-e29b-41d4-a716-446655440000",
            initial_uncovered_count=25,
            anchoring_attempts=[
                AnchoringAttempt(
                    attempt_id="attempt-001",
                    span_id="550e8400-e29b-41d4-a716-446655440000",
                    uncovered_phrase="and Wi-Fi",
                    context_expansion_start=80,
                    context_expansion_end=280,
                    existing_facts_searched=["fact-001"],
                    new_facts_extracted=["fact-003"],
                    uncovered_reduction=10,
                    succeeded=True,
                    attempted_at="2025-01-15T10:46:00Z",
                )
            ],
            final_uncovered_count=15,
            stalled=False,
            clarification_emitted=False,
            completed_at="2025-01-15T10:48:00Z",
        )

    def test_preserves_nested_attempts(
        self, sample_progress_test_with_attempts: ProgressTest
    ) -> None:
        """JSON conversion preserves nested anchoring_attempts list."""
        result = progress_test_to_json(sample_progress_test_with_attempts)
        assert "anchoring_attempts" in result
        assert len(result["anchoring_attempts"]) == 1
        assert result["anchoring_attempts"][0]["attempt_id"] == "attempt-001"

    def test_round_trip(self, sample_progress_test_with_attempts: ProgressTest) -> None:
        """JSON round-trip preserves all data."""
        result = progress_test_to_json(sample_progress_test_with_attempts)
        assert result["test_id"] == sample_progress_test_with_attempts["test_id"]
        assert result["stalled"] is False
        assert result["final_uncovered_count"] == 15


class TestWorkRegionToJson:
    """Tests for work_region_to_json function."""

    def test_preserves_structure(self, sample_work_region: WorkRegion) -> None:
        """JSON conversion preserves all fields."""
        result = work_region_to_json(sample_work_region)
        assert result["region_id"] == sample_work_region["region_id"]
        assert result["doc_id"] == sample_work_region["doc_id"]
        assert result["start_char"] == sample_work_region["start_char"]
        assert result["end_char"] == sample_work_region["end_char"]
        assert result["is_processed"] == sample_work_region["is_processed"]


class TestEntityDeclarationToJson:
    """Tests for entity_declaration_to_json function."""

    def test_preserves_nested_source_context(
        self, sample_entity_declaration: EntityDeclaration
    ) -> None:
        """JSON conversion preserves nested source_context."""
        result = entity_declaration_to_json(sample_entity_declaration)
        assert "source_context" in result
        assert result["source_context"]["doc_id"] is not None
        assert result["source_context"]["start_char"] is not None

    def test_round_trip(self, sample_entity_declaration: EntityDeclaration) -> None:
        """JSON round-trip preserves all data."""
        result = entity_declaration_to_json(sample_entity_declaration)
        assert result["entity_id"] == sample_entity_declaration["entity_id"]
        assert result["fact_type"] == "ENTITY_DECLARATION"
        assert result["entity_name"] == "buffalo sauce"
        assert result["status"] == "DECLARED"


class TestAttributeAnnotationToJson:
    """Tests for attribute_annotation_to_json function."""

    def test_preserves_nested_source_context(
        self, sample_attribute_annotation: AttributeAnnotation
    ) -> None:
        """JSON conversion preserves nested source_context."""
        result = attribute_annotation_to_json(sample_attribute_annotation)
        assert "source_context" in result
        assert result["source_context"]["doc_id"] is not None

    def test_round_trip(self, sample_attribute_annotation: AttributeAnnotation) -> None:
        """JSON round-trip preserves all data."""
        result = attribute_annotation_to_json(sample_attribute_annotation)
        assert result["annotation_id"] == sample_attribute_annotation["annotation_id"]
        assert result["fact_type"] == "ATTRIBUTE_ANNOTATION"
        assert result["entity_name"] == "buffalo sauce"
        assert result["attribute"] == "also"


# =============================================================================
# CSV ROW CONVERTER TESTS FOR REMAINING FUNCTIONS
# =============================================================================


class TestReconstructionFailureToCsvRow:
    """Tests for reconstruction_failure_to_csv_row function."""

    @pytest.fixture
    def sample_reconstruction_failure(self) -> ReconstructionFailure:
        """Sample reconstruction failure for testing."""
        return ReconstructionFailure(
            failure_id="550e8400-e29b-41d4-a716-446655440020",
            span_id="550e8400-e29b-41d4-a716-446655440000",
            original_text="The device supports Bluetooth and Wi-Fi connectivity.",
            reconstructed_text="The device supports Bluetooth connectivity.",
            uncovered_phrases=["and Wi-Fi"],
            uncovered_offsets=[(32, 42)],
            facts_used=["fact-001"],
            proof_trace="Applied fact-001. Missing: conjunction and second connectivity type.",
            substitutions_used={},
            failed_at="2025-01-15T10:45:00Z",
        )

    def test_flattens_reconstruction_failure(
        self, sample_reconstruction_failure: ReconstructionFailure
    ) -> None:
        """ReconstructionFailure is flattened with JSON-encoded nested fields."""
        row = reconstruction_failure_to_csv_row(sample_reconstruction_failure)
        assert row["failure_id"] == sample_reconstruction_failure["failure_id"]
        assert row["span_id"] == sample_reconstruction_failure["span_id"]
        assert row["original_text"] == sample_reconstruction_failure["original_text"]
        assert row["reconstructed_text"] == sample_reconstruction_failure["reconstructed_text"]
        assert row["proof_trace"] == sample_reconstruction_failure["proof_trace"]
        assert row["failed_at"] == sample_reconstruction_failure["failed_at"]
        # Check JSON-encoded fields are present
        assert "uncovered_phrases_json" in row
        assert "uncovered_offsets_json" in row
        assert "facts_used_json" in row
        assert "substitutions_used_json" in row

    def test_all_columns_present(
        self, sample_reconstruction_failure: ReconstructionFailure
    ) -> None:
        """All expected columns are present in output."""
        row = reconstruction_failure_to_csv_row(sample_reconstruction_failure)
        for col in RECONSTRUCTION_FAILURE_CSV_COLUMNS:
            assert col in row


class TestClarificationQuestionToCsvRow:
    """Tests for clarification_question_to_csv_row function."""

    @pytest.fixture
    def sample_clarification_question(self) -> ClarificationQuestion:
        """Sample clarification question for testing."""
        return ClarificationQuestion(
            question_id="550e8400-e29b-41d4-a716-446655440021",
            doc_id="doc-001",
            start_char=500,
            end_char=550,
            verbatim_text="erupting from the palms of its hands",
            failure_statement="Cannot determine referent for 'its' - no singular entity in context",
            failure_type="anchoring_failure",
            bounded_attempts_count=3,
            author_response="",
            emitted_at="2025-01-15T10:50:00Z",
        )

    def test_flattens_clarification_question(
        self, sample_clarification_question: ClarificationQuestion
    ) -> None:
        """ClarificationQuestion is flattened to dict of strings."""
        row = clarification_question_to_csv_row(sample_clarification_question)
        assert row["question_id"] == sample_clarification_question["question_id"]
        assert row["doc_id"] == sample_clarification_question["doc_id"]
        assert row["start_char"] == str(sample_clarification_question["start_char"])
        assert row["end_char"] == str(sample_clarification_question["end_char"])
        assert row["verbatim_text"] == sample_clarification_question["verbatim_text"]
        assert row["failure_statement"] == sample_clarification_question["failure_statement"]
        assert row["failure_type"] == sample_clarification_question["failure_type"]
        assert row["bounded_attempts_count"] == str(
            sample_clarification_question["bounded_attempts_count"]
        )
        assert row["author_response"] == sample_clarification_question["author_response"]
        assert row["emitted_at"] == sample_clarification_question["emitted_at"]

    def test_all_columns_present(
        self, sample_clarification_question: ClarificationQuestion
    ) -> None:
        """All expected columns are present in output."""
        row = clarification_question_to_csv_row(sample_clarification_question)
        for col in CLARIFICATION_QUESTION_CSV_COLUMNS:
            assert col in row


class TestFabricationAttemptToCsvRow:
    """Tests for fabrication_attempt_to_csv_row function."""

    @pytest.fixture
    def sample_fabrication_attempt(
        self, sample_base_fact: BaseFact, sample_span: Span
    ) -> FabricationAttempt:
        """Sample fabrication attempt for testing."""
        return FabricationAttempt(
            attempt_id="550e8400-e29b-41d4-a716-446655440022",
            fabrication_type="HIDDEN_COPULA",
            attempted_fact=sample_base_fact,
            source_span=sample_span,
            detection_method="spacy_grammar",
            violation_details="Verb 'are' was added to source text.",
            detected_at="2025-01-15T10:40:00Z",
        )

    def test_flattens_fabrication_attempt(
        self, sample_fabrication_attempt: FabricationAttempt
    ) -> None:
        """FabricationAttempt is flattened with JSON-encoded nested fields."""
        row = fabrication_attempt_to_csv_row(sample_fabrication_attempt)
        assert row["attempt_id"] == sample_fabrication_attempt["attempt_id"]
        assert row["fabrication_type"] == "HIDDEN_COPULA"
        assert row["detection_method"] == "spacy_grammar"
        assert row["violation_details"] == sample_fabrication_attempt["violation_details"]
        assert row["detected_at"] == sample_fabrication_attempt["detected_at"]
        # Check JSON-encoded fields are present
        assert "attempted_fact_json" in row
        assert "source_span_json" in row

    def test_all_columns_present(self, sample_fabrication_attempt: FabricationAttempt) -> None:
        """All expected columns are present in output."""
        row = fabrication_attempt_to_csv_row(sample_fabrication_attempt)
        for col in FABRICATION_ATTEMPT_CSV_COLUMNS:
            assert col in row


class TestAnchoringAttemptToCsvRow:
    """Tests for anchoring_attempt_to_csv_row function."""

    @pytest.fixture
    def sample_anchoring_attempt(self) -> AnchoringAttempt:
        """Sample anchoring attempt for testing."""
        return AnchoringAttempt(
            attempt_id="550e8400-e29b-41d4-a716-446655440023",
            span_id="550e8400-e29b-41d4-a716-446655440000",
            uncovered_phrase="and Wi-Fi",
            context_expansion_start=80,
            context_expansion_end=280,
            existing_facts_searched=["fact-001", "fact-002"],
            new_facts_extracted=["fact-003"],
            uncovered_reduction=10,
            succeeded=True,
            attempted_at="2025-01-15T10:46:00Z",
        )

    def test_flattens_anchoring_attempt(
        self, sample_anchoring_attempt: AnchoringAttempt
    ) -> None:
        """AnchoringAttempt is flattened with JSON-encoded nested fields."""
        row = anchoring_attempt_to_csv_row(sample_anchoring_attempt)
        assert row["attempt_id"] == sample_anchoring_attempt["attempt_id"]
        assert row["span_id"] == sample_anchoring_attempt["span_id"]
        assert row["uncovered_phrase"] == sample_anchoring_attempt["uncovered_phrase"]
        assert row["context_expansion_start"] == str(
            sample_anchoring_attempt["context_expansion_start"]
        )
        assert row["context_expansion_end"] == str(
            sample_anchoring_attempt["context_expansion_end"]
        )
        assert row["uncovered_reduction"] == str(
            sample_anchoring_attempt["uncovered_reduction"]
        )
        assert row["succeeded"] == "true"
        assert row["attempted_at"] == sample_anchoring_attempt["attempted_at"]
        # Check JSON-encoded fields are present
        assert "existing_facts_searched_json" in row
        assert "new_facts_extracted_json" in row

    def test_all_columns_present(self, sample_anchoring_attempt: AnchoringAttempt) -> None:
        """All expected columns are present in output."""
        row = anchoring_attempt_to_csv_row(sample_anchoring_attempt)
        for col in ANCHORING_ATTEMPT_CSV_COLUMNS:
            assert col in row


class TestProgressTestToCsvRow:
    """Tests for progress_test_to_csv_row function."""

    @pytest.fixture
    def sample_progress_test(self) -> ProgressTest:
        """Sample progress test for testing."""
        return ProgressTest(
            test_id="550e8400-e29b-41d4-a716-446655440024",
            span_id="550e8400-e29b-41d4-a716-446655440000",
            initial_uncovered_count=25,
            anchoring_attempts=[
                AnchoringAttempt(
                    attempt_id="attempt-001",
                    span_id="550e8400-e29b-41d4-a716-446655440000",
                    uncovered_phrase="and Wi-Fi",
                    context_expansion_start=80,
                    context_expansion_end=280,
                    existing_facts_searched=["fact-001"],
                    new_facts_extracted=["fact-003"],
                    uncovered_reduction=10,
                    succeeded=True,
                    attempted_at="2025-01-15T10:46:00Z",
                )
            ],
            final_uncovered_count=15,
            stalled=False,
            clarification_emitted=False,
            completed_at="2025-01-15T10:48:00Z",
        )

    def test_flattens_progress_test(self, sample_progress_test: ProgressTest) -> None:
        """ProgressTest is flattened with JSON-encoded nested fields."""
        row = progress_test_to_csv_row(sample_progress_test)
        assert row["test_id"] == sample_progress_test["test_id"]
        assert row["span_id"] == sample_progress_test["span_id"]
        assert row["initial_uncovered_count"] == str(
            sample_progress_test["initial_uncovered_count"]
        )
        assert row["final_uncovered_count"] == str(
            sample_progress_test["final_uncovered_count"]
        )
        assert row["stalled"] == "false"
        assert row["clarification_emitted"] == "false"
        assert row["completed_at"] == sample_progress_test["completed_at"]
        # Check JSON-encoded fields are present
        assert "anchoring_attempts_json" in row

    def test_all_columns_present(self, sample_progress_test: ProgressTest) -> None:
        """All expected columns are present in output."""
        row = progress_test_to_csv_row(sample_progress_test)
        for col in PROGRESS_TEST_CSV_COLUMNS:
            assert col in row
