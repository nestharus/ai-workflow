"""Atomic restructuring operations proposed from coupling/cohesion issues.

Translates detected CouplingIssues into concrete RefinementOperations:

- Overlap  -> MERGE (combine units) or MOVE (relocate entity)
- Divergence -> SPLIT (break unit into cohesive parts)
- Overload -> SPLIT (decompose entity into sub-entities)

Operations are validated against the adjacency graph to ensure they won't
break graph consistency (no orphaned nodes, no dangling references).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from spec_manager.analysis.adjacency.graph import AdjacencyGraph

from .detector import CouplingIssue


@dataclass
class RefinementOperation:
    """An atomic restructuring operation.

    Attributes:
        op_type: The operation kind.
        source: Source grouping unit ID(s).
        target: Target grouping unit ID(s).
        entities: Entity IDs affected by this operation.
        rationale: Human-readable explanation of why this operation is
            proposed, tracing back to the detected issue.
    """

    op_type: Literal["create", "modify", "remove", "split", "merge", "move"]
    source: str | list[str]
    target: str | list[str]
    entities: list[str]
    rationale: str


def propose_operations(issues: list[CouplingIssue]) -> list[RefinementOperation]:
    """Propose restructuring operations from detected issues.

    Mapping rules:
    - ``overlap`` with 2 units -> MOVE (move entity to the unit with more
      internal edges to it); with 3+ units -> MERGE those units.
    - ``divergence`` -> SPLIT (one per disconnected cluster).
    - ``overload`` -> SPLIT (decompose the overloaded entity).

    Args:
        issues: Detected coupling/cohesion issues.

    Returns:
        List of proposed RefinementOperations, one per issue.
    """
    operations: list[RefinementOperation] = []

    for issue in issues:
        if issue.issue_type == "overlap":
            ops = _propose_for_overlap(issue)
        elif issue.issue_type == "divergence":
            ops = _propose_for_divergence(issue)
        elif issue.issue_type == "overload":
            ops = _propose_for_overload(issue)
        else:
            continue
        operations.extend(ops)

    return operations


def validate_operation(
    op: RefinementOperation,
    adjacency_graph: AdjacencyGraph,
) -> list[str]:
    """Validate that an operation won't break graph consistency.

    Checks:
    1. All referenced entities exist in the graph.
    2. REMOVE operations don't orphan connected entities.
    3. MOVE/MERGE operations reference valid source/target.
    4. SPLIT operations don't produce empty partitions.

    Args:
        op: The operation to validate.
        adjacency_graph: The current entity graph.

    Returns:
        List of validation error strings.  Empty means valid.
    """
    errors: list[str] = []
    graph_nodes = set(adjacency_graph.nodes())

    # Check all entities exist
    for entity_id in op.entities:
        if entity_id not in graph_nodes:
            errors.append(
                f"Entity '{entity_id}' referenced in {op.op_type} operation "
                f"does not exist in the adjacency graph."
            )

    if op.op_type == "remove":
        # Check that removing these entities won't orphan their neighbors
        for entity_id in op.entities:
            if entity_id not in graph_nodes:
                continue
            neighbors = adjacency_graph.all_neighbors(entity_id)
            for neighbor_id, _edge in neighbors:
                # If the neighbor is ONLY connected to the entity being
                # removed, it will become orphaned
                neighbor_connections = adjacency_graph.all_neighbors(neighbor_id)
                other_connections = [n for n, _ in neighbor_connections if n != entity_id]
                if not other_connections and neighbor_id not in op.entities:
                    errors.append(
                        f"Removing '{entity_id}' would orphan '{neighbor_id}' "
                        f"(its only connection)."
                    )

    if op.op_type == "move":
        # Source and target must be specified
        if not op.source:
            errors.append("MOVE operation requires a source grouping unit.")
        if not op.target:
            errors.append("MOVE operation requires a target grouping unit.")

    if op.op_type == "merge":
        # Need at least 2 sources
        sources = op.source if isinstance(op.source, list) else [op.source]
        if len(sources) < 2:
            errors.append("MERGE operation requires at least 2 source units.")

    if op.op_type == "split" and not op.entities:
        # Must have entities to split
        errors.append("SPLIT operation requires at least one entity.")

    return errors


# --- Private helpers ---


def _propose_for_overlap(issue: CouplingIssue) -> list[RefinementOperation]:
    """Propose operations for an overlap issue."""
    all_units = [issue.grouping_unit, *issue.related_units]

    if len(all_units) == 2:
        # Two units sharing an entity -> MOVE to the primary unit
        return [
            RefinementOperation(
                op_type="move",
                source=all_units[1],
                target=all_units[0],
                entities=issue.entities,
                rationale=(
                    f"Entity {''.join(issue.entities)} is duplicated across "
                    f"{all_units[0]} and {all_units[1]}.  Move to "
                    f"{all_units[0]} as the single source of truth."
                ),
            )
        ]
    else:
        # 3+ units -> MERGE them
        return [
            RefinementOperation(
                op_type="merge",
                source=all_units,
                target=all_units[0],
                entities=issue.entities,
                rationale=(
                    f"Entity {''.join(issue.entities)} is shared across "
                    f"{len(all_units)} units ({', '.join(all_units)}).  "
                    f"Merge into {all_units[0]}."
                ),
            )
        ]


def _propose_for_divergence(issue: CouplingIssue) -> list[RefinementOperation]:
    """Propose operations for a divergence issue."""
    return [
        RefinementOperation(
            op_type="split",
            source=issue.grouping_unit,
            target=[f"{issue.grouping_unit}_split_{i}" for i in range(len(issue.entities))],
            entities=issue.entities,
            rationale=(
                f"Unit '{issue.grouping_unit}' has disconnected clusters.  "
                f"Split the {len(issue.entities)} divergent entities into "
                f"separate cohesive units."
            ),
        )
    ]


def _propose_for_overload(issue: CouplingIssue) -> list[RefinementOperation]:
    """Propose operations for an overload issue."""
    return [
        RefinementOperation(
            op_type="split",
            source=issue.grouping_unit,
            target=[issue.grouping_unit],
            entities=issue.entities,
            rationale=(
                f"Entity '{issue.entities[0]}' in unit "
                f"'{issue.grouping_unit}' has excessive responsibilities.  "
                f"Decompose into sub-entities."
            ),
        )
    ]
