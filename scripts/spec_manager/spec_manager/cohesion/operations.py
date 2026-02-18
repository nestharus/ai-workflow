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

    op_type: Literal["create", "remove", "split", "merge", "move"]
    source: str | list[str]
    target: str | list[str]
    entities: list[str]
    rationale: str


def propose_operations(issues: list[CouplingIssue]) -> list[RefinementOperation]:
    """Propose restructuring operations from detected issues.

    Mapping rules:
    - ``overlap`` -> MOVE/MERGE using detector-provided edge evidence.
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
            raise ValueError(
                f"Unhandled issue_type '{issue.issue_type}' for unit '{issue.grouping_unit}'."
            )
        operations.extend(ops)

    return operations


def validate_operation(
    op: RefinementOperation,
    adjacency_graph: AdjacencyGraph,
    source_memberships: dict[str, set[str]] | None = None,
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
        source_memberships: Optional projection of source unit -> member
            entities. Required for full REMOVE blast-radius validation.

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
        # REMOVE affects all entities in the source slice(s), not only op.entities.
        sources = op.source if isinstance(op.source, list) else [op.source]
        affected_entities = set(op.entities)
        if source_memberships is None:
            errors.append(
                "REMOVE validation requires source_memberships to assess full "
                "source-slice blast radius."
            )
        else:
            for source in sources:
                members = source_memberships.get(source)
                if members is None:
                    errors.append(f"REMOVE source '{source}' missing from source_memberships.")
                    continue
                affected_entities.update(members)

        # Ensure all affected entities are known to the graph.
        for entity_id in sorted(affected_entities):
            if entity_id in graph_nodes:
                continue
            if entity_id in op.entities:
                # Already reported by the generic entity existence check.
                continue
            errors.append(
                f"Entity '{entity_id}' affected by remove operation is not "
                "present in the adjacency graph."
            )

        # Check that removing affected entities won't orphan neighbors.
        seen_orphans: set[tuple[str, str]] = set()
        for entity_id in sorted(affected_entities):
            if entity_id not in graph_nodes:
                continue
            neighbors = adjacency_graph.all_neighbors(entity_id)
            for neighbor_id, _edge in neighbors:
                if neighbor_id in affected_entities:
                    continue
                neighbor_connections = adjacency_graph.all_neighbors(neighbor_id)
                remaining_connections = [
                    n for n, _ in neighbor_connections if n not in affected_entities
                ]
                if remaining_connections:
                    continue
                key = (entity_id, neighbor_id)
                if key in seen_orphans:
                    continue
                seen_orphans.add(key)
                errors.append(
                    f"Removing '{entity_id}' would orphan '{neighbor_id}' "
                    "(its only remaining connections are removed)."
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
    if len(all_units) < 2:
        raise ValueError(
            f"Overlap issue for '{issue.grouping_unit}' must include at least two units."
        )
    target_unit = _pick_overlap_target(issue, all_units)
    entity_list = ", ".join(issue.entities)

    if len(all_units) == 2:
        source_unit = all_units[0] if target_unit == all_units[1] else all_units[1]
        return [
            RefinementOperation(
                op_type="move",
                source=source_unit,
                target=target_unit,
                entities=issue.entities,
                rationale=(
                    f"Entity {entity_list} is duplicated across "
                    f"{all_units[0]} and {all_units[1]}.  Move to "
                    f"{target_unit} based on higher internal edge score."
                ),
            )
        ]
    else:
        # 3+ units -> MERGE them
        return [
            RefinementOperation(
                op_type="merge",
                source=all_units,
                target=target_unit,
                entities=issue.entities,
                rationale=(
                    f"Entity {entity_list} is shared across "
                    f"{len(all_units)} units ({', '.join(all_units)}).  "
                    f"Merge into {target_unit} based on overlap edge evidence."
                ),
            )
        ]


def _propose_for_divergence(issue: CouplingIssue) -> list[RefinementOperation]:
    """Propose operations for a divergence issue."""
    if not issue.entity_clusters:
        raise ValueError(
            f"Divergence issue for '{issue.grouping_unit}' missing cluster "
            "structure (entity_clusters)."
        )

    operations: list[RefinementOperation] = []
    for idx, cluster in enumerate(issue.entity_clusters, start=1):
        if not cluster:
            raise ValueError(
                f"Divergence issue for '{issue.grouping_unit}' contains an empty cluster."
            )
        operations.append(
            RefinementOperation(
                op_type="split",
                source=issue.grouping_unit,
                target=f"{issue.grouping_unit}_split_{idx}",
                entities=cluster,
                rationale=(
                    f"Unit '{issue.grouping_unit}' has disconnected clusters.  "
                    f"Split cluster {idx} ({', '.join(cluster)}) into its own "
                    "cohesive unit."
                ),
            )
        )
    return operations


def _propose_for_overload(issue: CouplingIssue) -> list[RefinementOperation]:
    """Propose operations for an overload issue."""
    if not issue.entities:
        raise ValueError(f"Overload issue for '{issue.grouping_unit}' is missing entities.")
    overloaded_entity = issue.entities[0]
    return [
        RefinementOperation(
            op_type="split",
            source=issue.grouping_unit,
            target=f"{issue.grouping_unit}_overload_{overloaded_entity}",
            entities=issue.entities,
            rationale=(
                f"Entity '{overloaded_entity}' in unit "
                f"'{issue.grouping_unit}' has excessive responsibilities.  "
                f"Decompose into sub-entities."
            ),
        )
    ]


def _pick_overlap_target(issue: CouplingIssue, all_units: list[str]) -> str:
    """Choose overlap target unit using detector-provided edge scores."""
    if not issue.unit_edge_scores:
        raise ValueError(f"Overlap issue for '{issue.grouping_unit}' missing unit_edge_scores.")

    missing_units = [unit for unit in all_units if unit not in issue.unit_edge_scores]
    if missing_units:
        raise ValueError(
            f"Overlap issue for '{issue.grouping_unit}' missing scores for units: "
            f"{', '.join(missing_units)}."
        )

    top_score = max(issue.unit_edge_scores[unit] for unit in all_units)
    top_units = [unit for unit in all_units if issue.unit_edge_scores[unit] == top_score]
    if len(top_units) != 1:
        raise ValueError(
            "Ambiguous overlap target: tie on internal edge scores for units "
            f"{', '.join(sorted(top_units))}."
        )
    return top_units[0]
