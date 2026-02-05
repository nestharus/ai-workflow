"""Local ID resolver (ALG-CORE-0007).

This module resolves agent-assigned local IDs to stable element IDs,
ensuring consistent ID allocation across processing iterations.

Design References:
- ALG-CORE-0007: ResolveLocalIdsToStableIds
- CON-0019: local_id resolution
- DS-CORE-0009: DeterministicIdAllocatorState
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.tag_delta import TagIndexDelta, TagItem, TagRelation

from spec_manager.schemas.derived_elements import (
    DerivedElement,
    RelationEdge,
    allocate_element_id,
)


@dataclass
class DeterministicIdAllocatorState:
    """State for deterministic ID allocation (DS-CORE-0009).

    Attributes:
        counters: Mapping of prefix/namespace to current counter
        reserved: Set of reserved IDs that cannot be allocated
        stable_maps: Mapping of fingerprint to allocated ID
    """

    counters: dict[str, int] = field(default_factory=dict)
    reserved: set[str] = field(default_factory=set)
    stable_maps: dict[str, str] = field(default_factory=dict)

    def get_counter(self, prefix: str) -> int:
        """Get the current counter for a prefix.

        Args:
            prefix: The prefix to get counter for (e.g., "REQ-LIB-0001")

        Returns:
            Current counter value
        """
        return self.counters.get(prefix, 0)

    def increment_counter(self, prefix: str) -> int:
        """Increment and return counter for a prefix.

        Args:
            prefix: The prefix to increment

        Returns:
            New counter value after increment
        """
        current = self.counters.get(prefix, 0)
        self.counters[prefix] = current + 1
        return current + 1

    def reserve_id(self, elem_id: str) -> None:
        """Reserve an ID to prevent future allocation.

        Args:
            elem_id: The ID to reserve
        """
        self.reserved.add(elem_id)

    def is_reserved(self, elem_id: str) -> bool:
        """Check if an ID is reserved.

        Args:
            elem_id: The ID to check

        Returns:
            True if reserved, False otherwise
        """
        return elem_id in self.reserved

    def get_stable_id(self, fingerprint: str) -> str | None:
        """Get the stable ID for a fingerprint.

        Args:
            fingerprint: The fingerprint to look up

        Returns:
            Stable ID if found, None otherwise
        """
        return self.stable_maps.get(fingerprint)

    def set_stable_id(self, fingerprint: str, elem_id: str) -> None:
        """Set the stable ID for a fingerprint.

        Args:
            fingerprint: The fingerprint to map
            elem_id: The stable ID to assign
        """
        self.stable_maps[fingerprint] = elem_id


@dataclass
class ResolvedItem:
    """A resolved item with stable ID.

    Attributes:
        stable_id: The resolved stable element ID
        local_id: The original local ID
        element: The DerivedElement created from this item (None for references)
        is_reference: True if this is a reference to existing element
    """

    stable_id: str
    local_id: str
    element: DerivedElement | None
    is_reference: bool = False


@dataclass
class ResolvedRelation:
    """A resolved relation with stable IDs.

    Attributes:
        from_stable_id: Resolved source element ID
        to_stable_id: Resolved target element ID
        edge: The RelationEdge created from this relation
    """

    from_stable_id: str
    to_stable_id: str
    edge: RelationEdge


@dataclass
class ResolvedDelta:
    """The result of resolving a TagIndexDelta.

    Attributes:
        items: List of resolved items
        relations: List of resolved relations
        local_to_stable: Mapping of local_id to stable_id
    """

    items: list[ResolvedItem] = field(default_factory=list)
    relations: list[ResolvedRelation] = field(default_factory=list)
    local_to_stable: dict[str, str] = field(default_factory=dict)

    def get_elements(self) -> list[DerivedElement]:
        """Get all resolved elements (excluding references).

        Returns:
            List of DerivedElement objects
        """
        return [item.element for item in self.items if item.element is not None]

    def get_edges(self) -> list[RelationEdge]:
        """Get all resolved relation edges.

        Returns:
            List of RelationEdge objects
        """
        return [rel.edge for rel in self.relations]


class LocalIdResolver:
    """Resolver for local IDs to stable IDs (ALG-CORE-0007).

    Resolves agent-assigned local IDs to stable element IDs using
    deterministic allocation based on content fingerprints.
    """

    def __init__(self, allocator_state: DeterministicIdAllocatorState | None = None):
        """Initialize the resolver.

        Args:
            allocator_state: Optional pre-existing allocator state
        """
        self.state = allocator_state or DeterministicIdAllocatorState()

    def resolve(
        self,
        tag_delta: "TagIndexDelta",
    ) -> ResolvedDelta:
        """Resolve local IDs to stable IDs (ALG-CORE-0007).

        For each item in the delta:
        1. If existing_elem_id is set, use that stable ID
        2. Otherwise, compute fingerprint and allocate new stable ID

        Args:
            tag_delta: The delta with local IDs to resolve

        Returns:
            ResolvedDelta with stable IDs
        """
        result = ResolvedDelta()
        local_to_stable: dict[str, str] = {}

        # First pass: resolve all items
        for item in tag_delta.items:
            if item.existing_elem_id:
                # Reference to existing element - no new element created
                stable_id = item.existing_elem_id
                local_to_stable[item.local_id] = stable_id
                result.items.append(
                    ResolvedItem(
                        stable_id=stable_id,
                        local_id=item.local_id,
                        element=None,
                        is_reference=True,
                    )
                )
            else:
                # New item - allocate stable ID and create element
                stable_id = self._allocate_stable_id(item)
                element = self._create_element_from_item(item, stable_id)
                local_to_stable[item.local_id] = stable_id
                result.items.append(
                    ResolvedItem(
                        stable_id=stable_id,
                        local_id=item.local_id,
                        element=element,
                        is_reference=False,
                    )
                )

        result.local_to_stable = local_to_stable

        # Second pass: resolve relations
        for relation in tag_delta.relations:
            from_stable = local_to_stable.get(relation.from_local_id)
            to_stable = local_to_stable.get(relation.to_local_id)

            if from_stable and to_stable:
                edge = RelationEdge(
                    from_id=from_stable,
                    to_id=to_stable,
                    relation_type=relation.relation_type,  # type: ignore[arg-type]
                    evidence_atom_ids=relation.evidence_atom_ids,
                )
                result.relations.append(
                    ResolvedRelation(
                        from_stable_id=from_stable,
                        to_stable_id=to_stable,
                        edge=edge,
                    )
                )

        return result

    def _allocate_stable_id(self, item: "TagItem") -> str:
        """Allocate a stable ID for a new item.

        Uses content fingerprint for idempotent allocation.

        Args:
            item: The item to allocate ID for

        Returns:
            Allocated stable element ID
        """
        # Compute fingerprint from content
        fingerprint = self._compute_fingerprint(item)

        # Check if we've seen this fingerprint before
        existing_id = self.state.get_stable_id(fingerprint)
        if existing_id:
            return existing_id

        # Allocate new ID
        existing_ids = self.state.reserved.copy()
        stable_id = allocate_element_id(
            kind=item.kind,  # type: ignore[arg-type]
            lib_id=item.lib_id,
            existing_ids=existing_ids,
        )

        # Record allocation
        self.state.reserve_id(stable_id)
        self.state.set_stable_id(fingerprint, stable_id)

        return stable_id

    def _compute_fingerprint(self, item: "TagItem") -> str:
        """Compute content fingerprint for an item.

        The fingerprint is based on:
        - Kind
        - Library ID
        - Title
        - Body (first 500 chars)
        - Sorted evidence atom IDs

        Args:
            item: The item to fingerprint

        Returns:
            SHA256 fingerprint string
        """
        content = "|".join(
            [
                item.kind,
                item.lib_id,
                item.title,
                item.body[:500],  # Limit body for stability
                ",".join(sorted(item.evidence_atom_ids)),
            ]
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _create_element_from_item(
        self, item: "TagItem", stable_id: str
    ) -> DerivedElement:
        """Create a DerivedElement from a TagItem.

        Args:
            item: The source TagItem
            stable_id: The resolved stable ID

        Returns:
            A DerivedElement instance
        """
        return DerivedElement(
            elem_id=stable_id,
            kind=item.kind,  # type: ignore[arg-type]
            lib_id=item.lib_id,
            title=item.title,
            body=item.body,
            evidence_atom_ids=item.evidence_atom_ids,
        )
