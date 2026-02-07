"""Tests for entity-to-atom matching strategies."""

from __future__ import annotations

from spec_manager.branches.types import AtomDescriptor, AtomKind
from spec_manager.compliance.coverage.matching import (
    _tokenize_name,
    match_by_keywords,
    match_by_naming,
    match_explicit,
    resolve_matches,
)
from spec_manager.compliance.coverage.report import CoverageMatch
from spec_manager.schemas.entities import (
    EntitiesArtifact,
    Entity,
    EntityKind,
    EntityMention,
    EntityTag,
)
from spec_manager.schemas.hollowed_spec import HollowedParagraph, ParagraphKind


def _make_entity(entity_id: str, name: str, kind: EntityKind = EntityKind.CONCEPT) -> Entity:
    return Entity(entity_id=entity_id, name=name, kind=kind)


def _make_atom(
    atom_id: str,
    function_name: str,
    kind: AtomKind = AtomKind.ALGORITHM,
    vertical_slice: str | None = None,
) -> AtomDescriptor:
    return AtomDescriptor(
        atom_id=atom_id,
        kind=kind,
        file_path=f"{function_name}.py",
        function_name=function_name,
        signature="() -> None",
        content_hash="abc123",
        introduced_by="test",
        vertical_slice=vertical_slice,
    )


def _make_paragraph(
    para_id: str,
    keywords: list[str] | None = None,
) -> HollowedParagraph:
    return HollowedParagraph(
        paragraph_id=para_id,
        section_path="Test.Section",
        kind=ParagraphKind.PROSE,
        text="Test paragraph text",
        keywords=keywords or [],
        entity_refs=[],
        line_start=1,
        line_end=2,
    )


class TestTokenizeName:
    def test_underscore_case(self) -> None:
        tokens = _tokenize_name("calculate_payment_total")
        assert "calculate" in tokens
        assert "payment" in tokens
        assert "total" in tokens

    def test_camel_case(self) -> None:
        tokens = _tokenize_name("calculatePaymentTotal")
        assert "calculate" in tokens
        assert "payment" in tokens
        assert "total" in tokens

    def test_dash_case(self) -> None:
        tokens = _tokenize_name("calculate-payment-total")
        assert "calculate" in tokens
        assert "payment" in tokens
        assert "total" in tokens

    def test_mixed_case(self) -> None:
        tokens = _tokenize_name("my_httpClient-factory")
        assert "http" in tokens
        assert "client" in tokens
        assert "factory" in tokens

    def test_filters_short_tokens(self) -> None:
        tokens = _tokenize_name("a_bb_ccc")
        assert "ccc" in tokens
        assert "bb" not in tokens
        assert "a" not in tokens

    def test_empty_string(self) -> None:
        tokens = _tokenize_name("")
        assert tokens == set()

    def test_single_word(self) -> None:
        tokens = _tokenize_name("payment")
        assert tokens == {"payment"}


class TestMatchExplicit:
    def test_matches_linked_atoms(self) -> None:
        artifact = EntitiesArtifact(
            entities=[_make_entity("ENT-0001", "Payment Processor")],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_process_payment", "atom_validate_card"],
                    confidence=1.0,
                )
            ],
        )
        atom_ids = {"atom_process_payment", "atom_validate_card", "atom_other"}
        matches = match_explicit(artifact, atom_ids)

        assert len(matches) == 2
        assert all(m.match_method == "explicit" for m in matches)
        assert all(m.confidence == 1.0 for m in matches)
        matched_atom_ids = {m.atom_id for m in matches}
        assert "atom_process_payment" in matched_atom_ids
        assert "atom_validate_card" in matched_atom_ids

    def test_filters_missing_atoms(self) -> None:
        artifact = EntitiesArtifact(
            entities=[_make_entity("ENT-0001", "Widget")],
            mentions=[
                EntityMention(
                    entity_id="ENT-0001",
                    section_id="SEC-01",
                    atom_ids=["atom_missing"],
                )
            ],
        )
        atom_ids = {"atom_other"}
        matches = match_explicit(artifact, atom_ids)
        assert len(matches) == 0

    def test_includes_tag_linkages(self) -> None:
        artifact = EntitiesArtifact(
            entities=[_make_entity("ENT-0001", "Config")],
            mentions=[],
            tags=[
                EntityTag(
                    entity_id="ENT-0001",
                    atom_ids=["atom_load_config"],
                    tag_type="definition",
                )
            ],
        )
        atom_ids = {"atom_load_config"}
        matches = match_explicit(artifact, atom_ids)
        assert len(matches) == 1
        assert matches[0].atom_id == "atom_load_config"

    def test_empty_artifact(self) -> None:
        artifact = EntitiesArtifact()
        matches = match_explicit(artifact, {"atom_1"})
        assert matches == []


class TestMatchByNaming:
    def test_high_similarity_matches(self) -> None:
        entities = [_make_entity("ENT-0001", "calculate_payment")]
        atoms = [_make_atom("a1", "calculate_payment_total")]
        matches = match_by_naming(entities, atoms)

        assert len(matches) == 1
        assert matches[0].match_method == "naming"
        assert matches[0].confidence == 0.7

    def test_low_similarity_no_match(self) -> None:
        entities = [_make_entity("ENT-0001", "payment_processor")]
        atoms = [_make_atom("a1", "widget_factory_builder")]
        matches = match_by_naming(entities, atoms)
        assert len(matches) == 0

    def test_exact_name_match(self) -> None:
        entities = [_make_entity("ENT-0001", "calculate_total")]
        atoms = [_make_atom("a1", "calculate_total")]
        matches = match_by_naming(entities, atoms)

        assert len(matches) == 1
        assert matches[0].confidence == 0.7

    def test_camel_case_vs_underscore(self) -> None:
        entities = [_make_entity("ENT-0001", "PaymentProcessor")]
        atoms = [_make_atom("a1", "payment_processor")]
        matches = match_by_naming(entities, atoms)

        assert len(matches) == 1

    def test_empty_inputs(self) -> None:
        assert match_by_naming([], []) == []
        assert match_by_naming([], [_make_atom("a1", "foo")]) == []
        assert match_by_naming([_make_entity("ENT-0001", "foo")], []) == []


class TestMatchByKeywords:
    def test_sufficient_keyword_overlap(self) -> None:
        paragraphs = {
            "Payment System": [
                _make_paragraph("p1", keywords=["payment", "processing", "gateway", "secure"]),
            ],
        }
        atom_keywords = {
            "atom_payment": {"payment", "processing", "gateway"},
        }
        matches = match_by_keywords(paragraphs, atom_keywords)

        assert len(matches) == 1
        assert matches[0].match_method == "keyword"
        assert matches[0].confidence == 0.4

    def test_insufficient_keyword_overlap(self) -> None:
        paragraphs = {
            "Payment System": [
                _make_paragraph("p1", keywords=["payment", "processing"]),
            ],
        }
        atom_keywords = {
            "atom_widget": {"widget", "factory", "payment"},
        }
        matches = match_by_keywords(paragraphs, atom_keywords)
        assert len(matches) == 0  # Only 1 shared keyword, need >= 3

    def test_entity_name_to_id_mapping(self) -> None:
        paragraphs = {
            "Auth Service": [
                _make_paragraph("p1", keywords=["auth", "token", "validate", "session"]),
            ],
        }
        atom_keywords = {
            "atom_auth": {"auth", "token", "validate"},
        }
        entity_names = {"Auth Service": "ENT-0001"}
        matches = match_by_keywords(paragraphs, atom_keywords, entity_names)

        assert len(matches) == 1
        assert matches[0].entity_id == "ENT-0001"

    def test_empty_keywords(self) -> None:
        paragraphs = {
            "Empty": [_make_paragraph("p1", keywords=[])],
        }
        atom_keywords = {"atom_1": {"a", "b", "c"}}
        matches = match_by_keywords(paragraphs, atom_keywords)
        assert matches == []

    def test_case_insensitive(self) -> None:
        paragraphs = {
            "Auth": [
                _make_paragraph("p1", keywords=["Auth", "Token", "Validate", "Session"]),
            ],
        }
        atom_keywords = {
            "atom_auth": {"auth", "token", "validate"},
        }
        matches = match_by_keywords(paragraphs, atom_keywords)
        assert len(matches) == 1


class TestResolveMatches:
    def test_explicit_overrides_naming(self) -> None:
        explicit = [
            CoverageMatch("ENT-0001", "a1", "explicit", 1.0, "Payment", "process_payment"),
        ]
        naming = [
            CoverageMatch("ENT-0001", "a1", "naming", 0.7, "Payment", "process_payment"),
        ]
        result = resolve_matches(explicit, naming, [])
        assert len(result) == 1
        assert result[0].match_method == "explicit"
        assert result[0].confidence == 1.0

    def test_naming_overrides_keyword(self) -> None:
        naming = [
            CoverageMatch("ENT-0001", "a1", "naming", 0.7, "Payment", "process_payment"),
        ]
        keyword = [
            CoverageMatch("ENT-0001", "a1", "keyword", 0.4, "Payment", "process_payment"),
        ]
        result = resolve_matches([], naming, keyword)
        assert len(result) == 1
        assert result[0].match_method == "naming"
        assert result[0].confidence == 0.7

    def test_multiple_distinct_pairs(self) -> None:
        explicit = [
            CoverageMatch("ENT-0001", "a1", "explicit", 1.0, "E1", "f1"),
        ]
        naming = [
            CoverageMatch("ENT-0002", "a2", "naming", 0.7, "E2", "f2"),
        ]
        keyword = [
            CoverageMatch("ENT-0003", "a3", "keyword", 0.4, "E3", "f3"),
        ]
        result = resolve_matches(explicit, naming, keyword)
        assert len(result) == 3

    def test_empty_inputs(self) -> None:
        result = resolve_matches([], [], [])
        assert result == []

    def test_sorted_by_confidence_then_ids(self) -> None:
        matches = [
            CoverageMatch("ENT-0002", "a2", "naming", 0.7, "E2", "f2"),
            CoverageMatch("ENT-0001", "a1", "explicit", 1.0, "E1", "f1"),
            CoverageMatch("ENT-0003", "a3", "keyword", 0.4, "E3", "f3"),
        ]
        result = resolve_matches([matches[1]], [matches[0]], [matches[2]])
        assert result[0].confidence == 1.0
        assert result[1].confidence == 0.7
        assert result[2].confidence == 0.4
