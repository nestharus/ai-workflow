"""Local ID resolver for stable ID allocation (ALG-CORE-0007).

Resolves local (agent-assigned) IDs in TagIndexDelta to stable,
deterministic IDs based on content fingerprints.

Design References:
- ALG-CORE-0007: ResolveLocalIdsToStableIds
- CON-0019: local_id resolution
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from spec_manager.schemas.tag_delta import TagIndexDelta, TagItem


@dataclass
class DeterministicIdAllocatorState:
    """State for deterministic ID allocation across multiple resolutions.

    Tracks counters per prefix, reserved IDs, and fingerprint-to-stable-ID
    mappings to ensure idempotent allocation.
    """

    counters: dict[str, int] = field(default_factory=dict)
    reserved: set[str] = field(default_factory=set)
    stable_map: dict[str, str] = field(default_factory=dict)

    def get_counter(self, prefix: str) -> int:
        """Get current counter value for a prefix.

        Args:
            prefix: The ID prefix (e.g., 'REQ-LIB-0001')

        Returns:
            Current counter value (0 if not set)
        """
        return self.counters.get(prefix, 0)

    def increment_counter(self, prefix: str) -> int:
        """Increment and return new counter value for a prefix.

        Args:
            prefix: The ID prefix (e.g., 'REQ-LIB-0001')

        Returns:
            New counter value after increment
        """
        current = self.counters.get(prefix, 0) + 1
        self.counters[prefix] = current
        return current

    def is_reserved(self, stable_id: str) -> bool:
        """Check if a stable ID is already reserved.

        Args:
            stable_id: The stable ID to check

        Returns:
            True if reserved
        """
        return stable_id in self.reserved

    def reserve_id(self, stable_id: str) -> None:
        """Reserve a stable ID.

        Args:
            stable_id: The stable ID to reserve
        """
        self.reserved.add(stable_id)

    def get_stable_id(self, fingerprint: str) -> str | None:
        """Get stable ID for a fingerprint.

        Args:
            fingerprint: Content fingerprint

        Returns:
            Stable ID if known, None otherwise
        """
        return self.stable_map.get(fingerprint)

    def set_stable_id(self, fingerprint: str, stable_id: str) -> None:
        """Map a fingerprint to a stable ID.

        Args:
            fingerprint: Content fingerprint
            stable_id: The stable ID to associate
        """
        self.stable_map[fingerprint] = stable_id


@dataclass
class ResolvedElement:
    """A resolved spec element with stable ID."""

    kind: str
    stable_id: str
    lib_id: str
    title: str
    body: str
    evidence_atom_ids: list[str] = field(default_factory=list)


@dataclass
class ResolvedItem:
    """A resolved item linking local_id to stable_id."""

    local_id: str
    stable_id: str
    element: ResolvedElement | None = None
    is_reference: bool = False


@dataclass
class ResolvedRelation:
    """A resolved relation with stable ID endpoints."""

    from_stable_id: str
    to_stable_id: str
    relation_type: str
    evidence_atom_ids: list[str] = field(default_factory=list)


@dataclass
class ResolvedDelta:
    """Result of resolving a TagIndexDelta."""

    items: list[ResolvedItem] = field(default_factory=list)
    relations: list[ResolvedRelation] = field(default_factory=list)
    local_to_stable: dict[str, str] = field(default_factory=dict)

    def get_elements(self) -> list[ResolvedElement]:
        """Get all resolved elements (excluding references).

        Returns:
            List of ResolvedElement objects
        """
        return [item.element for item in self.items if item.element is not None]

    def get_edges(self) -> list[ResolvedRelation]:
        """Get all resolved relation edges.

        Returns:
            List of ResolvedRelation objects
        """
        return list(self.relations)


def _compute_fingerprint(item: TagItem) -> str:
    """Compute a content-based fingerprint for a TagItem.

    The fingerprint is based on kind, lib_id, title, body, and evidence_atom_ids
    to ensure that identical content always gets the same stable ID.

    Args:
        item: The TagItem to fingerprint

    Returns:
        Hex digest fingerprint string
    """
    parts = [
        item.kind,
        item.lib_id,
        item.title,
        item.body,
        "|".join(sorted(item.evidence_atom_ids)),
    ]
    content = "\n".join(parts)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class LocalIdResolver:
    """Resolves local IDs in TagIndexDelta to stable IDs (ALG-CORE-0007).

    Uses content-based fingerprinting for idempotent allocation:
    same content always produces the same stable ID.

    Args:
        state: Optional shared allocator state for cross-resolution persistence
    """

    def __init__(self, state: DeterministicIdAllocatorState | None = None) -> None:
        self.state = state or DeterministicIdAllocatorState()

    def resolve(self, delta: TagIndexDelta) -> ResolvedDelta:
        """Resolve all local IDs in a delta to stable IDs.

        Args:
            delta: The TagIndexDelta containing items with local IDs

        Returns:
            ResolvedDelta with stable IDs allocated
        """
        result = ResolvedDelta()

        # Phase 1: Resolve items
        for item in delta.items:
            resolved_item = self._resolve_item(item)
            result.items.append(resolved_item)
            result.local_to_stable[item.local_id] = resolved_item.stable_id

        # Phase 2: Resolve relations using the local->stable mapping
        for relation in delta.relations:
            from_stable = result.local_to_stable.get(relation.from_local_id, relation.from_local_id)
            to_stable = result.local_to_stable.get(relation.to_local_id, relation.to_local_id)
            result.relations.append(
                ResolvedRelation(
                    from_stable_id=from_stable,
                    to_stable_id=to_stable,
                    relation_type=relation.relation_type,
                    evidence_atom_ids=list(relation.evidence_atom_ids),
                )
            )

        return result

    def _resolve_item(self, item: TagItem) -> ResolvedItem:
        """Resolve a single item to a stable ID.

        Args:
            item: The TagItem to resolve

        Returns:
            ResolvedItem with stable ID
        """
        # If referencing an existing element, use that ID
        if item.existing_elem_id:
            return ResolvedItem(
                local_id=item.local_id,
                stable_id=item.existing_elem_id,
                element=None,
                is_reference=True,
            )

        # Compute fingerprint for idempotent allocation
        fingerprint = _compute_fingerprint(item)
        existing_stable_id = self.state.get_stable_id(fingerprint)

        if existing_stable_id:
            stable_id = existing_stable_id
        else:
            stable_id = self._allocate_stable_id(item)
            self.state.set_stable_id(fingerprint, stable_id)

        self.state.reserve_id(stable_id)

        element = ResolvedElement(
            kind=item.kind,
            stable_id=stable_id,
            lib_id=item.lib_id,
            title=item.title,
            body=item.body,
            evidence_atom_ids=list(item.evidence_atom_ids),
        )

        return ResolvedItem(
            local_id=item.local_id,
            stable_id=stable_id,
            element=element,
            is_reference=False,
        )

    def _allocate_stable_id(self, item: TagItem) -> str:
        """Allocate a new stable ID for an item.

        Format: {KIND}-{LIB_ID}-{####}

        Args:
            item: The TagItem needing an ID

        Returns:
            Newly allocated stable ID
        """
        prefix = f"{item.kind}-{item.lib_id}"
        seq = self.state.increment_counter(prefix)
        stable_id = f"{prefix}-{seq:04d}"

        # Handle collisions with reserved IDs
        while self.state.is_reserved(stable_id):
            seq = self.state.increment_counter(prefix)
            stable_id = f"{prefix}-{seq:04d}"

        return stable_id
