"""Tests for local ID resolver (ALG-CORE-0007).

Tests:
- test_resolve_new_items: New item allocation
- test_resolve_existing_references: Existing item references
- test_resolve_relations: Relation endpoint rewriting
- test_idempotence: Same fingerprint -> same ID
"""

import pytest

from spec_manager.core.local_id_resolver import (
    DeterministicIdAllocatorState,
    LocalIdResolver,
    ResolvedDelta,
)
from spec_manager.schemas.tag_delta import (
    TagIndexDelta,
    TagItem,
    TagRelation,
)


class TestDeterministicIdAllocatorState:
    """Test DeterministicIdAllocatorState."""

    def test_counter_operations(self) -> None:
        """Test counter get and increment."""
        state = DeterministicIdAllocatorState()

        assert state.get_counter("REQ-LIB-0001") == 0
        assert state.increment_counter("REQ-LIB-0001") == 1
        assert state.get_counter("REQ-LIB-0001") == 1
        assert state.increment_counter("REQ-LIB-0001") == 2

    def test_reserved_ids(self) -> None:
        """Test ID reservation."""
        state = DeterministicIdAllocatorState()

        assert not state.is_reserved("REQ-LIB-0001-0001")
        state.reserve_id("REQ-LIB-0001-0001")
        assert state.is_reserved("REQ-LIB-0001-0001")

    def test_stable_maps(self) -> None:
        """Test stable ID mapping."""
        state = DeterministicIdAllocatorState()

        assert state.get_stable_id("fingerprint1") is None
        state.set_stable_id("fingerprint1", "REQ-LIB-0001-0001")
        assert state.get_stable_id("fingerprint1") == "REQ-LIB-0001-0001"


class TestLocalIdResolver:
    """Test LocalIdResolver."""

    def test_resolve_new_item(self) -> None:
        """Test resolving a new item allocates stable ID."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="new_req",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="New Requirement",
                    body="This is a new requirement.",
                    evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
                )
            ],
            lib_id="LIB-0001",
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        assert len(result.items) == 1
        assert result.items[0].local_id == "new_req"
        # Stable ID should match REQ-LIB-0001-#### format
        assert result.items[0].stable_id.startswith("REQ-LIB-0001-")
        assert result.items[0].element is not None
        assert result.items[0].element.kind == "REQ"

    def test_resolve_existing_reference(self) -> None:
        """Test resolving a reference to existing element."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="ref_existing",
                    existing_elem_id="REQ-LIB-0001-0042",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Existing",
                    body="Reference to existing",
                )
            ],
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        assert len(result.items) == 1
        assert result.items[0].stable_id == "REQ-LIB-0001-0042"
        assert result.items[0].is_reference is True
        assert result.items[0].element is None  # No new element created for references
        assert result.local_to_stable["ref_existing"] == "REQ-LIB-0001-0042"

    def test_resolve_relations(self) -> None:
        """Test relation endpoints are rewritten."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_a",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item A",
                    body="First item",
                    evidence_atom_ids=["ATOM-1"],
                ),
                TagItem(
                    local_id="item_b",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item B",
                    body="Second item",
                    evidence_atom_ids=["ATOM-2"],
                ),
            ],
            relations=[
                TagRelation(
                    from_local_id="item_a",
                    to_local_id="item_b",
                    relation_type="DEPENDS_ON",
                    evidence_atom_ids=["ATOM-1", "ATOM-2"],
                )
            ],
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        assert len(result.relations) == 1
        # Endpoints should be stable IDs, not local IDs
        assert result.relations[0].from_stable_id.startswith("REQ-LIB-0001-")
        assert result.relations[0].to_stable_id.startswith("REQ-LIB-0001-")
        assert result.relations[0].from_stable_id != "item_a"
        assert result.relations[0].to_stable_id != "item_b"

    def test_idempotence_same_fingerprint(self) -> None:
        """Test same content produces same stable ID."""
        item = TagItem(
            local_id="item_1",
            kind="REQ",
            lib_id="LIB-0001",
            title="Consistent Requirement",
            body="This requirement should always get the same ID.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
        )

        # Resolve twice with same content
        resolver = LocalIdResolver()

        delta1 = TagIndexDelta(items=[item])
        result1 = resolver.resolve(delta1)

        # Change local_id but keep same content
        item2 = TagItem(
            local_id="item_2_different_local",
            kind="REQ",
            lib_id="LIB-0001",
            title="Consistent Requirement",
            body="This requirement should always get the same ID.",
            evidence_atom_ids=["ATOM-F0001-R0001-L0001"],
        )
        delta2 = TagIndexDelta(items=[item2])
        result2 = resolver.resolve(delta2)

        # Should get same stable ID due to same fingerprint
        assert result1.items[0].stable_id == result2.items[0].stable_id

    def test_different_content_different_id(self) -> None:
        """Test different content produces different stable IDs."""
        resolver = LocalIdResolver()

        delta1 = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_1",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="First Requirement",
                    body="First content",
                    evidence_atom_ids=["ATOM-1"],
                )
            ]
        )
        result1 = resolver.resolve(delta1)

        delta2 = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_2",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Second Requirement",
                    body="Different content",
                    evidence_atom_ids=["ATOM-2"],
                )
            ]
        )
        result2 = resolver.resolve(delta2)

        # Should get different stable IDs
        assert result1.items[0].stable_id != result2.items[0].stable_id

    def test_resolve_multiple_kinds(self) -> None:
        """Test resolving multiple element kinds."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="req_1",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Requirement",
                    body="Req body",
                    evidence_atom_ids=["ATOM-1"],
                ),
                TagItem(
                    local_id="alg_1",
                    kind="ALG",
                    lib_id="LIB-0001",
                    title="Algorithm",
                    body="Alg body",
                    evidence_atom_ids=["ATOM-2"],
                ),
                TagItem(
                    local_id="ds_1",
                    kind="DS",
                    lib_id="LIB-0001",
                    title="Data Structure",
                    body="DS body",
                    evidence_atom_ids=["ATOM-3"],
                ),
            ]
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        assert len(result.items) == 3

        # Each should have appropriate prefix
        prefixes = {item.stable_id.split("-")[0] for item in result.items}
        assert prefixes == {"REQ", "ALG", "DS"}

    def test_get_elements(self) -> None:
        """Test get_elements returns all elements."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_1",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item 1",
                    body="Body 1",
                    evidence_atom_ids=["ATOM-1"],
                ),
                TagItem(
                    local_id="item_2",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item 2",
                    body="Body 2",
                    evidence_atom_ids=["ATOM-2"],
                ),
            ]
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        elements = result.get_elements()
        assert len(elements) == 2
        assert all(e.kind == "REQ" for e in elements)

    def test_get_edges(self) -> None:
        """Test get_edges returns all relation edges."""
        delta = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_1",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item 1",
                    body="Body 1",
                    evidence_atom_ids=["ATOM-1"],
                ),
                TagItem(
                    local_id="item_2",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Item 2",
                    body="Body 2",
                    evidence_atom_ids=["ATOM-2"],
                ),
            ],
            relations=[
                TagRelation(
                    from_local_id="item_1",
                    to_local_id="item_2",
                    relation_type="REFINES",
                )
            ],
        )

        resolver = LocalIdResolver()
        result = resolver.resolve(delta)

        edges = result.get_edges()
        assert len(edges) == 1
        assert edges[0].relation_type == "REFINES"

    def test_preserve_allocator_state(self) -> None:
        """Test resolver preserves state across resolutions."""
        state = DeterministicIdAllocatorState()
        resolver = LocalIdResolver(state)

        delta1 = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_1",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="First",
                    body="Body",
                    evidence_atom_ids=["ATOM-1"],
                )
            ]
        )
        resolver.resolve(delta1)

        # State should now have reserved the allocated ID
        assert len(state.reserved) == 1

        delta2 = TagIndexDelta(
            items=[
                TagItem(
                    local_id="item_2",
                    kind="REQ",
                    lib_id="LIB-0001",
                    title="Second",
                    body="Different body",
                    evidence_atom_ids=["ATOM-2"],
                )
            ]
        )
        resolver.resolve(delta2)

        # Should have allocated second ID
        assert len(state.reserved) == 2
