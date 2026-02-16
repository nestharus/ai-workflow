"""Coupling/cohesion issue detection using the adjacency graph.

Detects three structural states by analyzing entity membership across
grouping units (libraries, components, slices):

- **Overlap**: Same entity appears in multiple grouping units.
- **Divergence**: A grouping unit has entities with low internal connectivity.
- **Overload**: A single entity has too many outgoing edges (too many
  responsibilities).

All detection is mechanical/graph-based.  No TF-IDF, no stopwords, no
confidence thresholds, no fuzzy matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from spec_manager.analysis.adjacency.graph import AdjacencyGraph

logger = logging.getLogger(__name__)


@dataclass
class GroupingUnit:
    """A logical grouping of entities (library, component, slice).

    Attributes:
        unit_id: Unique identifier for this grouping unit.
        name: Human-readable name.
        entity_ids: Set of entity IDs (node IDs from the adjacency graph)
            that belong to this grouping unit.
    """

    unit_id: str
    name: str
    entity_ids: set[str] = field(default_factory=set)


@dataclass
class CouplingIssue:
    """A detected coupling/cohesion issue.

    Attributes:
        issue_type: One of overlap, divergence, or overload.
        grouping_unit: The primary grouping unit ID affected.
        entities: Entity IDs involved in the issue.
        severity: 0.0 (minor) to 1.0 (critical).  Computed from graph
            metrics, not from heuristic confidence scores.
        description: Human-readable explanation of the issue.
        related_units: Other grouping unit IDs involved (for overlap).
        entity_clusters: Disconnected entity clusters (for divergence).
        unit_edge_scores: Per-unit neighbor counts for overlap evidence.
    """

    issue_type: Literal["overlap", "divergence", "overload"]
    grouping_unit: str
    entities: list[str]
    severity: float
    description: str
    related_units: list[str] = field(default_factory=list)
    entity_clusters: list[list[str]] = field(default_factory=list)
    unit_edge_scores: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class DroppedEntity:
    """Entity excluded from detection because it was absent from the graph."""

    unit_id: str
    entity_id: str
    detector: Literal["overlap", "divergence", "overload"]


def detect_overlap(
    adjacency_graph: AdjacencyGraph,
    grouping_units: list[GroupingUnit],
    *,
    dropped_entities: list[DroppedEntity] | None = None,
) -> list[CouplingIssue]:
    """Detect entities that exist in multiple grouping units.

    An entity is overlapping if it appears in the ``entity_ids`` of more
    than one grouping unit.  Severity is proportional to the number of
    units sharing the entity relative to total units.

    This is a purely mechanical check: set intersection across grouping
    unit membership lists.

    Args:
        adjacency_graph: The entity graph (used to verify node existence).
        grouping_units: The grouping units to check.
        dropped_entities: Optional collector for entities missing from graph.

    Returns:
        List of CouplingIssue with issue_type="overlap".
    """
    issues: list[CouplingIssue] = []
    graph_nodes = set(adjacency_graph.nodes())
    unit_entity_map = {unit.unit_id: set(unit.entity_ids) for unit in grouping_units}

    # Build entity -> [unit_id, ...] membership map
    entity_to_units: dict[str, list[str]] = {}
    for unit in grouping_units:
        for entity_id in unit.entity_ids:
            # Only consider entities that actually exist in the graph
            if entity_id in graph_nodes:
                entity_to_units.setdefault(entity_id, []).append(unit.unit_id)
            elif dropped_entities is not None:
                dropped_entities.append(
                    DroppedEntity(
                        unit_id=unit.unit_id,
                        entity_id=entity_id,
                        detector="overlap",
                    )
                )

    total_units = len(grouping_units) if grouping_units else 1

    for entity_id, unit_ids in entity_to_units.items():
        if len(unit_ids) > 1:
            # Severity: fraction of units sharing this entity
            severity = min(1.0, len(unit_ids) / total_units)
            neighbor_ids = {
                neighbor_id for neighbor_id, _edge in adjacency_graph.all_neighbors(entity_id)
            }
            unit_edge_scores = {
                unit_id: len((unit_entity_map.get(unit_id, set()) - {entity_id}) & neighbor_ids)
                for unit_id in unit_ids
            }
            issues.append(
                CouplingIssue(
                    issue_type="overlap",
                    grouping_unit=unit_ids[0],
                    entities=[entity_id],
                    severity=severity,
                    description=(
                        f"Entity '{entity_id}' exists in {len(unit_ids)} "
                        f"grouping units: {', '.join(unit_ids)}. "
                        f"Deduplicate to a single source of truth."
                    ),
                    related_units=unit_ids[1:],
                    unit_edge_scores=unit_edge_scores,
                )
            )

    return issues


def detect_divergence(
    adjacency_graph: AdjacencyGraph,
    grouping_units: list[GroupingUnit],
    *,
    dropped_entities: list[DroppedEntity] | None = None,
) -> list[CouplingIssue]:
    """Detect grouping units whose entities have low internal connectivity.

    A grouping unit is divergent when its entities form multiple
    disconnected subgraphs within the adjacency graph.  Each disconnected
    cluster inside a single grouping unit indicates unrelated capabilities
    packed together.

    Detection is mechanical: extract the subgraph for each unit's entities
    and count connected components.  More than one component = divergence.
    Severity is ``1 - (1 / num_components)``.

    Args:
        adjacency_graph: The entity graph.
        grouping_units: The grouping units to check.
        dropped_entities: Optional collector for entities missing from graph.

    Returns:
        List of CouplingIssue with issue_type="divergence".
    """
    issues: list[CouplingIssue] = []
    graph_nodes = set(adjacency_graph.nodes())

    for unit in grouping_units:
        # Filter to entities that exist in the graph while accounting for dropped input.
        missing_entities = sorted(unit.entity_ids - graph_nodes)
        if dropped_entities is not None:
            dropped_entities.extend(
                [
                    DroppedEntity(
                        unit_id=unit.unit_id,
                        entity_id=entity_id,
                        detector="divergence",
                    )
                    for entity_id in missing_entities
                ]
            )
        valid_entities = unit.entity_ids - set(missing_entities)
        if len(valid_entities) < 2:
            # A unit with 0 or 1 entities cannot be divergent
            continue

        subgraph = adjacency_graph.subgraph(valid_entities)
        components = subgraph.connected_components()

        if len(components) > 1:
            severity = 1.0 - (1.0 / len(components))
            # Report the entities in the smaller (non-primary) components
            # as the divergent set.  The largest component is the "core".
            components_sorted = sorted(components, key=len, reverse=True)
            divergent_clusters = [sorted(comp) for comp in components_sorted[1:]]
            divergent_entities: list[str] = []
            for cluster in divergent_clusters:
                divergent_entities.extend(cluster)

            issues.append(
                CouplingIssue(
                    issue_type="divergence",
                    grouping_unit=unit.unit_id,
                    entities=divergent_entities,
                    severity=severity,
                    description=(
                        f"Grouping unit '{unit.unit_id}' has {len(components)} "
                        f"disconnected clusters among its {len(valid_entities)} "
                        f"entities.  Consider splitting into cohesive units."
                    ),
                    entity_clusters=divergent_clusters,
                )
            )

    return issues


def detect_overload(
    adjacency_graph: AdjacencyGraph,
    grouping_units: list[GroupingUnit],
    *,
    dropped_entities: list[DroppedEntity] | None = None,
) -> list[CouplingIssue]:
    """Detect entities with too many responsibilities (excessive edges).

    An entity is overloaded when its total edge count (incoming + outgoing)
    exceeds a threshold derived from the graph's own statistics: any entity
    whose degree exceeds ``mean + 2 * stdev`` of the degree distribution
    within its grouping unit is flagged.

    This is a statistical outlier detection on degree, not a heuristic
    confidence threshold.  The threshold adapts to the graph's scale.

    Args:
        adjacency_graph: The entity graph.
        grouping_units: The grouping units to check.
        dropped_entities: Optional collector for entities missing from graph.

    Returns:
        List of CouplingIssue with issue_type="overload".
    """
    issues: list[CouplingIssue] = []
    graph_nodes = set(adjacency_graph.nodes())

    for unit in grouping_units:
        missing_entities = sorted(unit.entity_ids - graph_nodes)
        if dropped_entities is not None:
            dropped_entities.extend(
                [
                    DroppedEntity(
                        unit_id=unit.unit_id,
                        entity_id=entity_id,
                        detector="overload",
                    )
                    for entity_id in missing_entities
                ]
            )
        valid_entities = unit.entity_ids - set(missing_entities)
        if len(valid_entities) < 3:
            # Need at least 3 entities to compute meaningful statistics
            continue

        # Compute degree for each entity within this unit's subgraph
        subgraph = adjacency_graph.subgraph(valid_entities)
        degrees: dict[str, int] = {}
        for entity_id in valid_entities:
            neighbors = subgraph.all_neighbors(entity_id)
            degrees[entity_id] = len(neighbors)

        if not degrees:
            continue

        # Compute mean and standard deviation of degrees
        degree_values = list(degrees.values())
        n = len(degree_values)
        mean = sum(degree_values) / n
        variance = sum((d - mean) ** 2 for d in degree_values) / n
        stdev = variance**0.5

        # Threshold: mean + 2 * stdev (statistical outlier)
        threshold = mean + 2.0 * stdev
        # Ensure threshold is at least 1 to avoid flagging trivially
        threshold = max(threshold, 1.0)

        for entity_id, degree in degrees.items():
            if degree > threshold:
                # Severity: how far above the threshold, capped at 1.0
                excess_ratio = (degree - threshold) / max(threshold, 1.0)
                severity = min(1.0, excess_ratio)

                issues.append(
                    CouplingIssue(
                        issue_type="overload",
                        grouping_unit=unit.unit_id,
                        entities=[entity_id],
                        severity=severity,
                        description=(
                            f"Entity '{entity_id}' in unit '{unit.unit_id}' has "
                            f"degree {degree} (threshold {threshold:.1f} = "
                            f"mean {mean:.1f} + 2*stdev {stdev:.1f}).  "
                            f"Consider decomposing this entity."
                        ),
                    )
                )

    return issues


def detect_all(
    adjacency_graph: AdjacencyGraph,
    grouping_units: list[GroupingUnit],
    *,
    dropped_entities: list[DroppedEntity] | None = None,
) -> list[CouplingIssue]:
    """Run all three detectors and return combined results.

    Results are sorted by severity (highest first).

    Args:
        adjacency_graph: The entity graph.
        grouping_units: The grouping units to check.
        dropped_entities: Optional collector for entities missing from graph.

    Returns:
        Combined list of all detected CouplingIssues, sorted by severity
        descending.
    """
    issues: list[CouplingIssue] = []
    dropped: list[DroppedEntity] = []
    issues.extend(
        detect_overlap(
            adjacency_graph,
            grouping_units,
            dropped_entities=dropped,
        )
    )
    issues.extend(
        detect_divergence(
            adjacency_graph,
            grouping_units,
            dropped_entities=dropped,
        )
    )
    issues.extend(
        detect_overload(
            adjacency_graph,
            grouping_units,
            dropped_entities=dropped,
        )
    )
    issues.sort(key=lambda i: i.severity, reverse=True)
    if dropped_entities is not None:
        seen: set[tuple[str, str, str]] = set()
        for dropped_entity in dropped:
            key = (
                dropped_entity.unit_id,
                dropped_entity.entity_id,
                dropped_entity.detector,
            )
            if key in seen:
                continue
            seen.add(key)
            dropped_entities.append(dropped_entity)
    if dropped:
        logger.warning(
            "Skipped %d unit-entity assignments missing from adjacency graph.",
            len(dropped),
        )
    return issues
