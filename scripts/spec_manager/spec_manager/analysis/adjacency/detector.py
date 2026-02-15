"""Relationship-facts graph construction and disconnected component detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from spec_manager.schemas.lineage import RelationshipFacts

from .graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


class IsolationClassification(Enum):
    """How a disconnected component is classified."""

    TRULY_ISOLATED = "truly_isolated"
    POTENTIALLY_MISSED = "potentially_missed"
    SUSPICIOUSLY_ISOLATED = "suspiciously_isolated"


@dataclass
class ComponentReport:
    """Report for a single connected component."""

    component_id: int
    nodes: set[str]
    size: int
    signal_types_present: set[SignalType]
    total_internal_weight: float
    classification: IsolationClassification | None = None  # None for the main component
    classification_reason: str = ""
    bridge_candidates: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "nodes": sorted(self.nodes),
            "size": self.size,
            "signal_types_present": sorted(s.value for s in self.signal_types_present),
            "total_internal_weight": round(self.total_internal_weight, 4),
            "classification": self.classification.value if self.classification else None,
            "classification_reason": self.classification_reason,
            "bridge_candidates": self.bridge_candidates,
        }


@dataclass
class AdjacencyReport:
    """Full adjacency analysis report."""

    total_nodes: int
    total_edges: int
    num_components: int
    components: list[ComponentReport]
    signal_type_counts: dict[str, int]  # edges per signal type
    signal_type_weights: dict[str, float]  # total weight per signal type
    disconnected_warnings: list[str]  # human-readable warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "num_components": self.num_components,
            "components": [c.to_dict() for c in self.components],
            "signal_type_counts": self.signal_type_counts,
            "signal_type_weights": {k: round(v, 4) for k, v in self.signal_type_weights.items()},
            "disconnected_warnings": self.disconnected_warnings,
        }

    def to_markdown(self) -> str:
        """Render as markdown report."""
        lines: list[str] = []
        lines.append("# Adjacency Analysis Report\n")

        lines.append("## Summary\n")
        lines.append(f"- **Total nodes**: {self.total_nodes}")
        lines.append(f"- **Total edges**: {self.total_edges}")
        lines.append(f"- **Connected components**: {self.num_components}")
        lines.append("")

        if self.signal_type_counts:
            lines.append("## Signal Type Distribution\n")
            lines.append("| Signal Type | Edge Count | Total Weight |")
            lines.append("|---|---|---|")
            for sig_type in sorted(self.signal_type_counts.keys()):
                count = self.signal_type_counts[sig_type]
                weight = self.signal_type_weights.get(sig_type, 0.0)
                lines.append(f"| {sig_type} | {count} | {weight:.2f} |")
            lines.append("")

        if self.components:
            lines.append("## Components\n")
            for comp in self.components:
                classification_str = (
                    f" [{comp.classification.value}]" if comp.classification else ""
                )
                lines.append(f"### Component {comp.component_id}{classification_str}\n")
                lines.append(f"- **Size**: {comp.size} nodes")
                signal_list = ", ".join(
                    s.value for s in sorted(comp.signal_types_present, key=lambda x: x.value)
                )
                lines.append(f"- **Signal types**: {signal_list}")
                lines.append(f"- **Total weight**: {comp.total_internal_weight:.2f}")

                if comp.classification_reason:
                    lines.append(f"- **Reason**: {comp.classification_reason}")

                if comp.bridge_candidates:
                    lines.append(f"- **Bridge candidates**: {len(comp.bridge_candidates)}")
                    for bridge in comp.bridge_candidates[:5]:
                        lines.append(
                            f"  - {bridge.get('source', '?')} -> {bridge.get('target', '?')} "
                            f"via {bridge.get('signal_type', '?')}"
                        )

                lines.append(f"- **Nodes**: {', '.join(sorted(comp.nodes))}")
                lines.append("")

        if self.disconnected_warnings:
            lines.append("## Warnings\n")
            for warning in self.disconnected_warnings:
                lines.append(f"- {warning}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdjacencyReport:
        components = []
        for comp_data in data.get("components", []):
            components.append(
                ComponentReport(
                    component_id=comp_data["component_id"],
                    nodes=set(comp_data["nodes"]),
                    size=comp_data["size"],
                    signal_types_present={SignalType(s) for s in comp_data["signal_types_present"]},
                    total_internal_weight=comp_data["total_internal_weight"],
                    classification=(
                        IsolationClassification(comp_data["classification"])
                        if comp_data.get("classification")
                        else None
                    ),
                    classification_reason=comp_data.get("classification_reason", ""),
                    bridge_candidates=comp_data.get("bridge_candidates", []),
                )
            )
        return cls(
            total_nodes=data["total_nodes"],
            total_edges=data["total_edges"],
            num_components=data["num_components"],
            components=components,
            signal_type_counts=data.get("signal_type_counts", {}),
            signal_type_weights=data.get("signal_type_weights", {}),
            disconnected_warnings=data.get("disconnected_warnings", []),
        )


DEFAULT_SIGNAL_WEIGHTS: dict[SignalType, float] = {
    SignalType.CALL: 1.0,
    SignalType.REFERENCE: 0.7,
    SignalType.STORE_TOUCH: 0.5,
    SignalType.CO_OCCURRENCE: 0.3,
    SignalType.EVENT: 0.8,
}


def build_unified_graph(
    relationship_facts: RelationshipFacts,
    weight_overrides: dict[SignalType, float] | None = None,
) -> AdjacencyGraph:
    """Build a unified graph directly from LLM relationship facts.

    Args:
        relationship_facts: Unified calls/events/stores relationship payload
        weight_overrides: Optional weight multipliers per signal type.
            Overrides are multiplicative against DEFAULT_SIGNAL_WEIGHTS.

    Returns:
        Unified AdjacencyGraph containing all declared signals
    """
    unified = AdjacencyGraph()
    weights = {
        signal_type: base * (weight_overrides.get(signal_type, 1.0) if weight_overrides else 1.0)
        for signal_type, base in DEFAULT_SIGNAL_WEIGHTS.items()
    }

    for call in relationship_facts.calls:
        unified.add_node(call.caller_pin, NodeInfo(node_id=call.caller_pin, node_type="pin"))
        unified.add_node(call.callee_pin, NodeInfo(node_id=call.callee_pin, node_type="pin"))
        signal = EdgeSignal(
            signal_type=SignalType.CALL,
            weight=weights[SignalType.CALL] * call.confidence,
            details={"confidence": call.confidence, "evidence_pin": call.evidence_pin},
        )
        unified.add_edge(call.caller_pin, call.callee_pin, signal)

    for event in relationship_facts.events:
        unified.add_node(event.emitter_pin, NodeInfo(node_id=event.emitter_pin, node_type="pin"))
        unified.add_node(event.event_id, NodeInfo(node_id=event.event_id, node_type="event"))
        emit_signal = EdgeSignal(
            signal_type=SignalType.EVENT,
            weight=weights[SignalType.EVENT],
            details={"event_id": event.event_id, "role": "emit"},
        )
        unified.add_edge(event.emitter_pin, event.event_id, emit_signal)
        if event.consumer_pin:
            unified.add_node(
                event.consumer_pin,
                NodeInfo(node_id=event.consumer_pin, node_type="pin"),
            )
            consume_signal = EdgeSignal(
                signal_type=SignalType.EVENT,
                weight=weights[SignalType.EVENT],
                details={"event_id": event.event_id, "role": "consume"},
            )
            unified.add_edge(event.event_id, event.consumer_pin, consume_signal)

    for store in relationship_facts.stores:
        unified.add_node(store.pin, NodeInfo(node_id=store.pin, node_type="pin"))
        unified.add_node(store.store_id, NodeInfo(node_id=store.store_id, node_type="store"))
        signal = EdgeSignal(
            signal_type=SignalType.STORE_TOUCH,
            weight=weights[SignalType.STORE_TOUCH],
            details={"access_type": store.access_type, "store_id": store.store_id},
        )
        unified.add_edge(store.pin, store.store_id, signal)

    return unified


def detect_disconnected_components(
    unified_graph: AdjacencyGraph,
    partial_graphs: dict[str, AdjacencyGraph] | None = None,
) -> AdjacencyReport:
    """Analyze the unified graph for disconnected components.

    Classifies each component using the three-tier system:
    - truly_isolated: no store or co-occurrence links to other components
    - potentially_missed: disconnected in call+event but linked via store/co-occurrence
    - suspiciously_isolated: single-node component

    Args:
        unified_graph: The merged graph from build_unified_graph()
        partial_graphs: Optional individual signal graphs for cross-checking.
            Keys should be signal type names ("call", "event", "store", "cooccurrence").

    Returns:
        AdjacencyReport with component analysis
    """
    components = unified_graph.connected_components()
    # Sort by size descending
    components.sort(key=lambda c: len(c), reverse=True)

    # Compute signal type statistics
    signal_type_counts: dict[str, int] = {}
    signal_type_weights: dict[str, float] = {}

    for edge in unified_graph.edges():
        for signal in edge.signals:
            st = signal.signal_type.value
            signal_type_counts[st] = signal_type_counts.get(st, 0) + 1
            signal_type_weights[st] = signal_type_weights.get(st, 0.0) + signal.weight

    # Build component reports
    component_reports: list[ComponentReport] = []
    warnings: list[str] = []

    for idx, component in enumerate(components):
        sub = unified_graph.subgraph(component)
        signal_types = set()
        total_weight = 0.0

        for edge in sub.edges():
            for signal in edge.signals:
                signal_types.add(signal.signal_type)
                total_weight += signal.weight

        # Classify disconnected components (not the largest/main component)
        classification = None
        reason = ""
        bridge_candidates: list[dict[str, Any]] = []

        if len(components) > 1:
            classification, reason, bridge_candidates = _classify_component(
                component, components, unified_graph, partial_graphs
            )

        report = ComponentReport(
            component_id=idx,
            nodes=component,
            size=len(component),
            signal_types_present=signal_types,
            total_internal_weight=total_weight,
            classification=classification,
            classification_reason=reason,
            bridge_candidates=bridge_candidates,
        )
        component_reports.append(report)

    # Generate warnings
    for report in component_reports:
        if report.classification == IsolationClassification.SUSPICIOUSLY_ISOLATED:
            warnings.append(
                f"Component {report.component_id}: single node "
                f"{sorted(report.nodes)[0]} has no connections. "
                f"May be standalone or extraction missed connections."
            )
        elif report.classification == IsolationClassification.POTENTIALLY_MISSED:
            warnings.append(
                f"Component {report.component_id}: {report.size} nodes are disconnected "
                f"in call+event graph but have {len(report.bridge_candidates)} "
                f"store/co-occurrence links to other components. "
                f"Likely missing explicit dependency."
            )
        elif report.classification == IsolationClassification.TRULY_ISOLATED and report.size > 1:
            warnings.append(
                f"Component {report.component_id}: {report.size} nodes are truly isolated "
                f"with no connections to other components."
            )

    return AdjacencyReport(
        total_nodes=len(unified_graph.nodes()),
        total_edges=len(unified_graph.edges()),
        num_components=len(components),
        components=component_reports,
        signal_type_counts=signal_type_counts,
        signal_type_weights=signal_type_weights,
        disconnected_warnings=warnings,
    )


def _classify_component(
    component: set[str],
    all_components: list[set[str]],
    unified_graph: AdjacencyGraph,
    partial_graphs: dict[str, AdjacencyGraph] | None,
) -> tuple[IsolationClassification, str, list[dict[str, Any]]]:
    """Classify a disconnected component.

    Returns (classification, reason, bridge_candidates).
    """
    bridge_candidates: list[dict[str, Any]] = []

    # Check for single-node component
    if len(component) == 1:
        node = next(iter(component))
        return (
            IsolationClassification.SUSPICIOUSLY_ISOLATED,
            f"Single node '{node}' with no connections",
            [],
        )

    # Check partial graphs for cross-component connections
    other_nodes: set[str] = set()
    for other in all_components:
        if other != component:
            other_nodes |= other

    if partial_graphs:
        # Check store and co-occurrence graphs for cross-component edges
        weak_signal_graphs = {
            name: graph
            for name, graph in partial_graphs.items()
            if name in ("store", "cooccurrence", "store_touch", "co_occurrence")
        }

        for graph_name, graph in weak_signal_graphs.items():
            for node in component:
                for neighbor, edge in graph.all_neighbors(node):
                    if neighbor in other_nodes:
                        bridge_candidates.append(
                            {
                                "source": node,
                                "target": neighbor,
                                "signal_type": graph_name,
                                "weight": edge.total_weight,
                            }
                        )

    if bridge_candidates:
        return (
            IsolationClassification.POTENTIALLY_MISSED,
            f"Disconnected in call+event graph but {len(bridge_candidates)} "
            f"store/co-occurrence links exist to other components",
            bridge_candidates,
        )

    return (
        IsolationClassification.TRULY_ISOLATED,
        "No store or co-occurrence links to other components",
        [],
    )
