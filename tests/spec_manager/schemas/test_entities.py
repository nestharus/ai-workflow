"""Tests for entity schemas (DS-STRUCT-0003..0005).

Tests:
- test_entity_id_format: Entity ID validation (ENT-####)
- test_entity_mention_atom_ids: EntityMention atom_ids population
- test_entity_tag_evidence_linkage: EntityTag evidence validation
- test_entities_artifact_lookup: Artifact lookup methods
"""

import pytest

from spec_manager.schemas.entities import (
    Entity,
    EntityKind,
    EntityMention,
    EntityTag,
    EntitiesArtifact,
    allocate_entity_id,
)


class TestEntity:
    """Test Entity model."""

    def test_valid_entity_id(self) -> None:
        """Test valid entity ID format."""
        entity = Entity(
            entity_id="ENT-0001",
            name="UserSession",
            kind=EntityKind.CONCEPT,
        )
        assert entity.entity_id == "ENT-0001"
        assert entity.name == "UserSession"
        assert entity.kind == EntityKind.CONCEPT

    def test_entity_with_optional_fields(self) -> None:
        """Test entity with all optional fields."""
        entity = Entity(
            entity_id="ENT-0042",
            name="FieldHierarchy",
            kind=EntityKind.DATA,
            canonical_symbol="FieldHier",
            description="A hierarchical structure of fields",
        )
        assert entity.canonical_symbol == "FieldHier"
        assert entity.description == "A hierarchical structure of fields"

    def test_invalid_entity_id_format(self) -> None:
        """Test invalid entity ID format raises error."""
        with pytest.raises(ValueError, match="ENT-####"):
            Entity(
                entity_id="ENTITY-0001",  # Wrong format
                name="Test",
                kind=EntityKind.CONCEPT,
            )

    def test_invalid_entity_id_wrong_digits(self) -> None:
        """Test entity ID with wrong number of digits raises error."""
        with pytest.raises(ValueError, match="ENT-####"):
            Entity(
                entity_id="ENT-001",  # Only 3 digits
                name="Test",
                kind=EntityKind.CONCEPT,
            )

    def test_all_entity_kinds_valid(self) -> None:
        """Test all EntityKind values can be used."""
        for kind in EntityKind:
            entity = Entity(
                entity_id="ENT-0001",
                name=f"Test{kind.value}",
                kind=kind,
            )
            assert entity.kind == kind


class TestEntityMention:
    """Test EntityMention model."""

    def test_entity_mention_basic(self) -> None:
        """Test basic entity mention creation."""
        mention = EntityMention(
            entity_id="ENT-0001",
            section_id="SEC-001",
            atom_ids=["ATOM-F0001-R0001-L0010", "ATOM-F0001-R0001-L0011"],
            confidence=0.95,
        )
        assert mention.entity_id == "ENT-0001"
        assert mention.section_id == "SEC-001"
        assert len(mention.atom_ids) == 2
        assert mention.confidence == 0.95

    def test_entity_mention_with_mention_text(self) -> None:
        """Test entity mention with mention text."""
        mention = EntityMention(
            entity_id="ENT-0042",
            section_id="SEC-003",
            atom_ids=["ATOM-F0001-R0001-L0050"],
            mention_text="field hierarchy",
        )
        assert mention.mention_text == "field hierarchy"

    def test_entity_mention_default_confidence(self) -> None:
        """Test default confidence is 1.0."""
        mention = EntityMention(
            entity_id="ENT-0001",
            section_id="SEC-001",
        )
        assert mention.confidence == 1.0

    def test_entity_mention_invalid_entity_id(self) -> None:
        """Test invalid entity ID raises error."""
        with pytest.raises(ValueError, match="ENT-####"):
            EntityMention(
                entity_id="INVALID",
                section_id="SEC-001",
            )

    def test_entity_mention_confidence_bounds(self) -> None:
        """Test confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            EntityMention(
                entity_id="ENT-0001",
                section_id="SEC-001",
                confidence=1.5,  # Out of bounds
            )


class TestEntityTag:
    """Test EntityTag model."""

    def test_entity_tag_with_evidence_id(self) -> None:
        """Test entity tag with evidence_id."""
        tag = EntityTag(
            entity_id="ENT-0001",
            evidence_id="EVID-F0001-R0001-L10-L25",
            confidence=0.9,
            tag_type="definition",
        )
        assert tag.entity_id == "ENT-0001"
        assert tag.evidence_id == "EVID-F0001-R0001-L10-L25"
        assert tag.tag_type == "definition"

    def test_entity_tag_with_atom_ids(self) -> None:
        """Test entity tag with atom_ids."""
        tag = EntityTag(
            entity_id="ENT-0002",
            atom_ids=["ATOM-F0001-R0001-L0001", "ATOM-F0001-R0001-L0002"],
            tag_type="usage",
        )
        assert len(tag.atom_ids) == 2
        assert tag.evidence_id is None

    def test_entity_tag_with_both(self) -> None:
        """Test entity tag with both evidence_id and atom_ids."""
        tag = EntityTag(
            entity_id="ENT-0003",
            evidence_id="EVID-F0001-R0001-L1-L10",
            atom_ids=["ATOM-F0001-R0001-L0005"],
            tag_type="reference",
        )
        assert tag.evidence_id is not None
        assert len(tag.atom_ids) == 1

    def test_entity_tag_requires_evidence_linkage(self) -> None:
        """Test entity tag requires evidence_id or atom_ids."""
        with pytest.raises(ValueError, match="evidence_id or atom_ids"):
            EntityTag(
                entity_id="ENT-0001",
                # Neither evidence_id nor atom_ids
            )

    def test_entity_tag_invalid_entity_id(self) -> None:
        """Test invalid entity ID raises error."""
        with pytest.raises(ValueError, match="ENT-####"):
            EntityTag(
                entity_id="BAD-ID",
                atom_ids=["ATOM-F0001-R0001-L0001"],
            )

    def test_entity_tag_default_tag_type(self) -> None:
        """Test default tag_type is 'usage'."""
        tag = EntityTag(
            entity_id="ENT-0001",
            atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        assert tag.tag_type == "usage"


class TestEntitiesArtifact:
    """Test EntitiesArtifact model."""

    def test_empty_artifact(self) -> None:
        """Test creating empty artifact."""
        artifact = EntitiesArtifact()
        assert artifact.schema_version == "1.0"
        assert artifact.entities == []
        assert artifact.mentions == []
        assert artifact.tags == []
        assert artifact.extraction_method == "llm_extraction"

    def test_artifact_with_data(self) -> None:
        """Test artifact with entities, mentions, and tags."""
        entity = Entity(
            entity_id="ENT-0001",
            name="TestConcept",
            kind=EntityKind.CONCEPT,
        )
        mention = EntityMention(
            entity_id="ENT-0001",
            section_id="SEC-001",
            atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        tag = EntityTag(
            entity_id="ENT-0001",
            atom_ids=["ATOM-F0001-R0001-L0001"],
        )

        artifact = EntitiesArtifact(
            entities=[entity],
            mentions=[mention],
            tags=[tag],
            extraction_method="manual",
            source_file="requirements.md",
        )

        assert len(artifact.entities) == 1
        assert len(artifact.mentions) == 1
        assert len(artifact.tags) == 1

    def test_get_entity_by_id(self) -> None:
        """Test get_entity_by_id method."""
        entity1 = Entity(entity_id="ENT-0001", name="First", kind=EntityKind.CONCEPT)
        entity2 = Entity(entity_id="ENT-0002", name="Second", kind=EntityKind.TERM)

        artifact = EntitiesArtifact(entities=[entity1, entity2])

        result = artifact.get_entity_by_id("ENT-0002")
        assert result is not None
        assert result.name == "Second"

        result = artifact.get_entity_by_id("ENT-9999")
        assert result is None

    def test_get_mentions_for_entity(self) -> None:
        """Test get_mentions_for_entity method."""
        mention1 = EntityMention(entity_id="ENT-0001", section_id="SEC-001")
        mention2 = EntityMention(entity_id="ENT-0001", section_id="SEC-002")
        mention3 = EntityMention(entity_id="ENT-0002", section_id="SEC-001")

        artifact = EntitiesArtifact(mentions=[mention1, mention2, mention3])

        mentions = artifact.get_mentions_for_entity("ENT-0001")
        assert len(mentions) == 2

        mentions = artifact.get_mentions_for_entity("ENT-0002")
        assert len(mentions) == 1

    def test_get_tags_for_entity(self) -> None:
        """Test get_tags_for_entity method."""
        tag1 = EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-1"])
        tag2 = EntityTag(entity_id="ENT-0001", atom_ids=["ATOM-2"])
        tag3 = EntityTag(entity_id="ENT-0002", atom_ids=["ATOM-3"])

        artifact = EntitiesArtifact(tags=[tag1, tag2, tag3])

        tags = artifact.get_tags_for_entity("ENT-0001")
        assert len(tags) == 2

    def test_get_atom_ids_for_entity(self) -> None:
        """Test get_atom_ids_for_entity aggregates from mentions and tags."""
        mention = EntityMention(
            entity_id="ENT-0001",
            section_id="SEC-001",
            atom_ids=["ATOM-1", "ATOM-2"],
        )
        tag = EntityTag(
            entity_id="ENT-0001",
            atom_ids=["ATOM-2", "ATOM-3"],  # ATOM-2 overlaps
        )

        artifact = EntitiesArtifact(mentions=[mention], tags=[tag])

        atom_ids = artifact.get_atom_ids_for_entity("ENT-0001")
        assert len(atom_ids) == 3  # Unique atoms
        assert set(atom_ids) == {"ATOM-1", "ATOM-2", "ATOM-3"}

    def test_serialization_roundtrip(self) -> None:
        """Test serialization and deserialization."""
        entity = Entity(
            entity_id="ENT-0001",
            name="TestEntity",
            kind=EntityKind.DATA,
            canonical_symbol="TE",
        )
        mention = EntityMention(
            entity_id="ENT-0001",
            section_id="SEC-001",
            atom_ids=["ATOM-1"],
            confidence=0.8,
        )
        tag = EntityTag(
            entity_id="ENT-0001",
            evidence_id="EVID-001",
            atom_ids=["ATOM-1"],
            tag_type="definition",
        )

        artifact = EntitiesArtifact(
            entities=[entity],
            mentions=[mention],
            tags=[tag],
        )

        # Serialize and deserialize
        data = artifact.model_dump()
        restored = EntitiesArtifact.model_validate(data)

        assert len(restored.entities) == 1
        assert restored.entities[0].canonical_symbol == "TE"
        assert restored.mentions[0].confidence == 0.8
        assert restored.tags[0].tag_type == "definition"


class TestAllocateEntityId:
    """Test allocate_entity_id function."""

    def test_allocate_first_entity_id(self) -> None:
        """Test allocating first entity ID."""
        eid = allocate_entity_id(set())
        assert eid == "ENT-0001"

    def test_allocate_next_entity_id(self) -> None:
        """Test allocating next entity ID after existing ones."""
        existing = {"ENT-0001", "ENT-0002", "ENT-0005"}
        eid = allocate_entity_id(existing)
        assert eid == "ENT-0006"

    def test_allocate_ignores_invalid_ids(self) -> None:
        """Test allocation ignores non-matching IDs in set."""
        existing = {"ENT-0001", "INVALID-ID", "OTHER-0099"}
        eid = allocate_entity_id(existing)
        assert eid == "ENT-0002"
