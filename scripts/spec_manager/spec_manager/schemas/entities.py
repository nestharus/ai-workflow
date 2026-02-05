"""Entity schemas for DS-STRUCT-0003..0005 compliance.

This module defines the Entity, EntityMention, EntityTag, and EntitiesArtifact
schemas used in library discovery to represent domain concepts extracted from
evidence content.

Design References:
- DS-STRUCT-0003: Entity schema
- DS-STRUCT-0004: EntityMention schema
- DS-STRUCT-0005: EntityTag schema
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# Entity ID pattern: ENT-#### (4 digits)
_ENTITY_ID_PATTERN = re.compile(r"^ENT-\d{4}$")


class EntityKind(str, Enum):
    """Types of entities that can be extracted from evidence content."""

    CONCEPT = "CONCEPT"  # Abstract concept or idea
    TERM = "TERM"  # Technical term or definition
    COMPONENT = "COMPONENT"  # System component or module
    ACTOR = "ACTOR"  # User, system, or external actor
    DATA = "DATA"  # Data structure or schema
    PROCESS = "PROCESS"  # Process or workflow
    CONSTRAINT = "CONSTRAINT"  # Constraint or rule


class Entity(BaseModel):
    """A domain entity extracted from evidence content (DS-STRUCT-0003).

    Entities represent named concepts, terms, components, or other domain
    objects that appear in the specification evidence.

    Attributes:
        entity_id: Unique entity identifier (ENT-####)
        name: Human-readable name for the entity
        kind: Classification of the entity type
        canonical_symbol: Optional canonical symbol/alias
        description: Optional description of the entity
    """

    entity_id: str
    name: str
    kind: EntityKind
    canonical_symbol: str | None = None
    description: str | None = None

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        """Validate entity ID format (ENT-####)."""
        if not _ENTITY_ID_PATTERN.fullmatch(value):
            raise ValueError("entity_id must match ENT-#### format (e.g., ENT-0001)")
        return value


class EntityMention(BaseModel):
    """A mention of an entity within a section (DS-STRUCT-0004).

    EntityMentions track where entities appear in the evidence content,
    linking them to specific sections and atom IDs.

    Attributes:
        entity_id: Reference to the mentioned entity
        section_id: Section where the mention occurs
        atom_ids: List of atom IDs where the entity is mentioned
        confidence: Confidence score for the mention (0.0-1.0)
        mention_text: The text that triggered this mention
    """

    entity_id: str
    section_id: str
    atom_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    mention_text: str | None = None

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        """Validate entity ID format."""
        if not _ENTITY_ID_PATTERN.fullmatch(value):
            raise ValueError("entity_id must match ENT-#### format")
        return value


class EntityTag(BaseModel):
    """An entity tag linking entity to evidence (DS-STRUCT-0005).

    EntityTags represent the relationship between an entity and the
    evidence that supports its existence or characteristics.

    Attributes:
        entity_id: Reference to the tagged entity
        evidence_id: Optional evidence range ID
        atom_ids: List of atom IDs providing evidence for this tag
        confidence: Confidence score for the tag (0.0-1.0)
        tag_type: Type of tag (definition, usage, reference)
    """

    entity_id: str
    evidence_id: str | None = None
    atom_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    tag_type: Literal["definition", "usage", "reference"] = "usage"

    @field_validator("entity_id")
    @classmethod
    def validate_entity_id(cls, value: str) -> str:
        """Validate entity ID format."""
        if not _ENTITY_ID_PATTERN.fullmatch(value):
            raise ValueError("entity_id must match ENT-#### format")
        return value

    @model_validator(mode="after")
    def validate_evidence_linkage(self) -> "EntityTag":
        """Validate that the tag has some form of evidence linkage."""
        if not self.evidence_id and not self.atom_ids:
            raise ValueError("EntityTag must have either evidence_id or atom_ids")
        return self


class EntitiesArtifact(BaseModel):
    """Collection of entities, mentions, and tags from extraction (DS-STRUCT-0003).

    This artifact represents the output of entity extraction, containing
    all entities found in the evidence along with their mentions and tags.

    Attributes:
        schema_version: Schema version string
        entities: List of extracted entities
        mentions: List of entity mentions
        tags: List of entity tags
        extraction_method: Method used for extraction
        source_file: Optional source file reference
    """

    schema_version: str = "1.0"
    entities: list[Entity] = Field(default_factory=list)
    mentions: list[EntityMention] = Field(default_factory=list)
    tags: list[EntityTag] = Field(default_factory=list)
    extraction_method: str = "llm_extraction"
    source_file: str | None = None

    def get_entity_by_id(self, entity_id: str) -> Entity | None:
        """Get an entity by its ID.

        Args:
            entity_id: The entity ID to look up

        Returns:
            The Entity if found, None otherwise
        """
        for entity in self.entities:
            if entity.entity_id == entity_id:
                return entity
        return None

    def get_mentions_for_entity(self, entity_id: str) -> list[EntityMention]:
        """Get all mentions of a specific entity.

        Args:
            entity_id: The entity ID to look up mentions for

        Returns:
            List of EntityMention objects for this entity
        """
        return [m for m in self.mentions if m.entity_id == entity_id]

    def get_tags_for_entity(self, entity_id: str) -> list[EntityTag]:
        """Get all tags for a specific entity.

        Args:
            entity_id: The entity ID to look up tags for

        Returns:
            List of EntityTag objects for this entity
        """
        return [t for t in self.tags if t.entity_id == entity_id]

    def get_atom_ids_for_entity(self, entity_id: str) -> list[str]:
        """Get all atom IDs associated with an entity.

        Aggregates atom IDs from both mentions and tags.

        Args:
            entity_id: The entity ID to look up

        Returns:
            List of unique atom IDs associated with this entity
        """
        atom_ids: set[str] = set()
        for mention in self.get_mentions_for_entity(entity_id):
            atom_ids.update(mention.atom_ids)
        for tag in self.get_tags_for_entity(entity_id):
            atom_ids.update(tag.atom_ids)
        return sorted(atom_ids)


def allocate_entity_id(existing_ids: set[str]) -> str:
    """Allocate a new entity ID.

    Finds the next available ENT-#### ID based on existing IDs.

    Args:
        existing_ids: Set of already allocated entity IDs

    Returns:
        A new unique entity ID in ENT-#### format
    """
    max_seq = 0
    for eid in existing_ids:
        if _ENTITY_ID_PATTERN.fullmatch(eid):
            seq = int(eid.split("-")[1])
            max_seq = max(max_seq, seq)
    return f"ENT-{max_seq + 1:04d}"
