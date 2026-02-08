"""TagIndexDelta schema for local_id handling (CON-0019).

This module defines the TagIndexDelta schema used for agent outputs
that use local IDs, which are later resolved to stable IDs.

Design References:
- CON-0019: local_id resolution
- ALG-CORE-0007: ResolveLocalIdsToStableIds
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class TagItem(BaseModel):
    """A tagged item with local ID for agent outputs.

    Attributes:
        local_id: Agent-assigned temporary ID (e.g., "item_1", "new_req_a")
        existing_elem_id: Set if referencing existing element
        kind: Element kind (REQ, FLOW, INV, DEC, ALG, DS, NOTE, GAP)
        lib_id: Library ID this item belongs to
        evidence_atom_ids: Atom IDs providing evidence
        title: Short title for the item
        body: Full content/description
    """

    local_id: str
    existing_elem_id: str | None = None
    kind: str
    lib_id: str
    evidence_atom_ids: list[str] = Field(default_factory=list)
    title: str
    body: str

    @model_validator(mode="after")
    def validate_evidence_or_existing(self) -> TagItem:
        """Validate that new items have evidence."""
        if self.existing_elem_id is None and not self.evidence_atom_ids:
            raise ValueError("New items (without existing_elem_id) must have evidence_atom_ids")
        return self


class TagRelation(BaseModel):
    """A relation using local IDs for agent outputs.

    Attributes:
        from_local_id: Local ID of source item
        to_local_id: Local ID of target item
        relation_type: Type of relationship
        evidence_atom_ids: Atom IDs providing evidence
    """

    from_local_id: str
    to_local_id: str
    relation_type: str
    evidence_atom_ids: list[str] = Field(default_factory=list)


class TagIndexDelta(BaseModel):
    """A delta containing items and relations with local IDs.

    This is the output format for agents that create new elements.
    Local IDs are resolved to stable IDs by LocalIdResolver.

    Attributes:
        items: List of tagged items with local IDs
        relations: List of relations using local IDs
        lib_id: Target library ID
    """

    items: list[TagItem] = Field(default_factory=list)
    relations: list[TagRelation] = Field(default_factory=list)
    lib_id: str = ""

    def get_item_by_local_id(self, local_id: str) -> TagItem | None:
        """Get an item by its local ID.

        Args:
            local_id: The local ID to look up

        Returns:
            The TagItem if found, None otherwise
        """
        for item in self.items:
            if item.local_id == local_id:
                return item
        return None

    def get_local_ids(self) -> set[str]:
        """Get all local IDs in this delta.

        Returns:
            Set of all local IDs
        """
        return {item.local_id for item in self.items}

    def validate_relation_references(self) -> list[str]:
        """Validate that all relation references exist.

        Returns:
            List of error messages (empty if valid)
        """
        errors: list[str] = []
        local_ids = self.get_local_ids()

        for relation in self.relations:
            if relation.from_local_id not in local_ids:
                errors.append(
                    f"Relation references unknown from_local_id: {relation.from_local_id}"
                )
            if relation.to_local_id not in local_ids:
                errors.append(f"Relation references unknown to_local_id: {relation.to_local_id}")

        return errors
