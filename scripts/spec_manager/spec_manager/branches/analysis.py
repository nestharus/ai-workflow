"""Analysis branch generator (design doc Section 13).

The analysis branch is always a computed artifact -- never manually
edited.  It is regenerated on demand from the pin-function import
graph, the atom registry, and the slice navigator.

Produces:
- lineage_table.json: Pin map (atom -> architectural locations)
- adjacency_graph.json: Co-occurrence and store-touch edges
- drift_report.md: Detected drift between branches

Delegates graph construction and connected-component analysis to the
canonical ``analysis.adjacency.graph.AdjacencyGraph``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.analysis.adjacency.graph import (
    AdjacencyGraph,
    EdgeSignal,
    SignalType,
)

from .atoms import AtomRegistry
from .layout import BranchLayout
from .pins import PinRegistry
from .slices import SliceNavigator
from .types import AtomKind, PinProjection, ProjectionType


@dataclass
class AnalysisArtifact:
    """Generated analysis for an atom."""

    atom_id: str
    architectural_imports: list[PinProjection]  # Forward trace
    projection_types: dict[str, ProjectionType]  # pin_id -> projection type
    adjacencies: list[str]  # Co-occurrence and store-touch edges
    data_flow_in: list[str]  # Signals into this atom
    data_flow_out: list[str]  # Signals out of this atom
    stores_touched: list[str]  # Stores read/written
    unprojected: bool  # No architectural usage

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "atom_id": self.atom_id,
            "architectural_imports": [p.to_dict() for p in self.architectural_imports],
            "projection_types": {k: v.value for k, v in self.projection_types.items()},
            "adjacencies": self.adjacencies,
            "data_flow_in": self.data_flow_in,
            "data_flow_out": self.data_flow_out,
            "stores_touched": self.stores_touched,
            "unprojected": self.unprojected,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisArtifact:
        """Deserialize from dictionary."""
        return cls(
            atom_id=data["atom_id"],
            architectural_imports=[
                PinProjection.from_dict(p) for p in data["architectural_imports"]
            ],
            projection_types={k: ProjectionType(v) for k, v in data["projection_types"].items()},
            adjacencies=data.get("adjacencies", []),
            data_flow_in=data.get("data_flow_in", []),
            data_flow_out=data.get("data_flow_out", []),
            stores_touched=data.get("stores_touched", []),
            unprojected=data.get("unprojected", False),
        )


@dataclass
class AnalysisReport:
    """Full analysis branch content."""

    generated_at: str
    atoms: list[AnalysisArtifact]
    orphaned_architectural: list[str]  # Arch code with no atom
    disconnected_subgraphs: list[list[str]]  # Isolated atom groups
    store_touch_edges: list[tuple[str, str, str]]  # (atom1, store, atom2)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "generated_at": self.generated_at,
            "atoms": [a.to_dict() for a in self.atoms],
            "orphaned_architectural": self.orphaned_architectural,
            "disconnected_subgraphs": self.disconnected_subgraphs,
            "store_touch_edges": [list(edge) for edge in self.store_touch_edges],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisReport:
        """Deserialize from dictionary."""
        return cls(
            generated_at=data["generated_at"],
            atoms=[AnalysisArtifact.from_dict(a) for a in data["atoms"]],
            orphaned_architectural=data.get("orphaned_architectural", []),
            disconnected_subgraphs=data.get("disconnected_subgraphs", []),
            store_touch_edges=[(e[0], e[1], e[2]) for e in data.get("store_touch_edges", [])],
        )


# ---- Adapter helpers ----


def _build_adjacency_graph(
    atoms: list[Any],
    slices: list[Any],
    store_atom_map: dict[str, set[str]],
) -> AdjacencyGraph:
    """Build a canonical AdjacencyGraph from branches data structures.

    Adds co-occurrence edges from vertical slices and store-touch edges.
    """
    graph = AdjacencyGraph()

    # Add all atom nodes
    for atom in atoms:
        graph.add_node(atom.atom_id)

    # Add co-occurrence edges from slices
    for vs in slices:
        for i, aid_a in enumerate(vs.atom_ids):
            for aid_b in vs.atom_ids[i + 1 :]:
                graph.add_edge(
                    aid_a,
                    aid_b,
                    EdgeSignal(SignalType.CO_OCCURRENCE, 1.0),
                )

    # Add store-touch edges
    for store_id, touching_atoms in store_atom_map.items():
        for aid in touching_atoms:
            graph.add_edge(
                aid,
                store_id,
                EdgeSignal(SignalType.STORE_TOUCH, 1.0),
            )

    return graph


class AnalysisGenerator:
    """Generates the analysis branch from current state.

    The analysis branch is ALWAYS computed, never manually edited.
    It is regenerated on demand from the pin-function import graph.

    Delegates graph construction and connected-component analysis to
    ``analysis.adjacency.graph.AdjacencyGraph``.
    """

    def __init__(
        self,
        layout: BranchLayout,
        atom_registry: AtomRegistry,
        pin_registry: PinRegistry,
        slice_navigator: SliceNavigator,
    ) -> None:
        self._layout = layout
        self._atom_registry = atom_registry
        self._pin_registry = pin_registry
        self._slice_navigator = slice_navigator

    def generate(self) -> AnalysisReport:
        """Generate the full analysis branch.

        Returns:
            AnalysisReport with per-atom analysis, orphaned code,
            disconnected subgraphs, and store-touch edges.
        """
        all_atoms = self._atom_registry.list_all()
        artifacts: list[AnalysisArtifact] = []
        slices = self._slice_navigator.list_all_slices()

        # Build store-touch map: store_id -> set of atom_ids
        store_atom_map: dict[str, set[str]] = {}
        for atom in all_atoms:
            if atom.kind == AtomKind.STORE:
                store_atom_map.setdefault(atom.atom_id, set())
        for vs in slices:
            for store_id in vs.store_ids:
                store_atom_map.setdefault(store_id, set()).update(vs.atom_ids)

        # Build the canonical adjacency graph
        adj_graph = _build_adjacency_graph(
            all_atoms,
            slices,
            store_atom_map,
        )

        # Build per-atom analysis using the graph for adjacencies
        for atom in all_atoms:
            artifact = self._analyze_atom(atom, store_atom_map, adj_graph)
            artifacts.append(artifact)

        # Detect orphaned architectural code
        orphaned = self._pin_registry.get_orphaned_architectural_code()

        # Detect disconnected subgraphs using the canonical graph
        subgraphs = self._find_disconnected_subgraphs(adj_graph, all_atoms)

        # Build store-touch edges
        store_touch_edges = self._build_store_touch_edges(store_atom_map)

        return AnalysisReport(
            generated_at=datetime.now(UTC).isoformat(),
            atoms=artifacts,
            orphaned_architectural=orphaned,
            disconnected_subgraphs=subgraphs,
            store_touch_edges=store_touch_edges,
        )

    def write_lineage_table(self, report: AnalysisReport) -> Path:
        """Write lineage_table.json to analysis/ directory.

        Args:
            report: The analysis report to write.

        Returns:
            Path to the written file.
        """
        analysis_dir = self._layout.analysis_dir()
        analysis_dir.mkdir(parents=True, exist_ok=True)
        path = analysis_dir / "lineage_table.json"

        lineage = {
            "generated_at": report.generated_at,
            "entries": [
                {
                    "atom_id": a.atom_id,
                    "pins": [p.to_dict() for p in a.architectural_imports],
                    "projection_types": {k: v.value for k, v in a.projection_types.items()},
                    "unprojected": a.unprojected,
                }
                for a in report.atoms
            ],
        }

        path.write_text(json.dumps(lineage, indent=2), encoding="utf-8")
        return path

    def write_adjacency_graph(self, report: AnalysisReport) -> Path:
        """Write adjacency_graph.json to analysis/ directory.

        Args:
            report: The analysis report to write.

        Returns:
            Path to the written file.
        """
        analysis_dir = self._layout.analysis_dir()
        analysis_dir.mkdir(parents=True, exist_ok=True)
        path = analysis_dir / "adjacency_graph.json"

        graph = {
            "generated_at": report.generated_at,
            "store_touch_edges": [list(e) for e in report.store_touch_edges],
            "disconnected_subgraphs": report.disconnected_subgraphs,
            "per_atom_adjacencies": {a.atom_id: a.adjacencies for a in report.atoms},
        }

        path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        return path

    def write_drift_report(self, report: AnalysisReport) -> Path:
        """Write drift_report.md to analysis/ directory.

        Args:
            report: The analysis report to write.

        Returns:
            Path to the written file.
        """
        analysis_dir = self._layout.analysis_dir()
        analysis_dir.mkdir(parents=True, exist_ok=True)
        path = analysis_dir / "drift_report.md"

        drift_reports = self._pin_registry.detect_drift(self._atom_registry)

        lines = [
            "# Drift Report",
            "",
            f"Generated: {report.generated_at}",
            "",
        ]

        if not drift_reports:
            lines.append("No drift detected.")
        else:
            lines.append(f"## Detected Drift ({len(drift_reports)} items)")
            lines.append("")
            for dr in drift_reports:
                lines.append(f"### {dr.pin_id}")
                lines.append(f"- **Atom**: {dr.atom_id}")
                lines.append(f"- **Type**: {dr.drift_type}")
                lines.append(f"- **Location**: {dr.architectural_location}")
                lines.append(f"- **Projection**: {dr.projection_type.value}")
                lines.append(f"- **Details**: {dr.details}")
                lines.append("")

        # Unprojected atoms
        unprojected = [a for a in report.atoms if a.unprojected]
        if unprojected:
            lines.append(f"## Unprojected Atoms ({len(unprojected)})")
            lines.append("")
            for a in unprojected:
                lines.append(f"- {a.atom_id}")
            lines.append("")

        # Disconnected subgraphs
        if len(report.disconnected_subgraphs) > 1:
            lines.append(f"## Disconnected Subgraphs ({len(report.disconnected_subgraphs)})")
            lines.append("")
            for i, group in enumerate(report.disconnected_subgraphs, 1):
                lines.append(f"### Group {i}")
                for atom_id in group:
                    lines.append(f"- {atom_id}")
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # ---- Internal helpers ----

    def _analyze_atom(
        self,
        atom: Any,
        store_atom_map: dict[str, set[str]],
        adj_graph: AdjacencyGraph,
    ) -> AnalysisArtifact:
        """Generate analysis artifact for a single atom.

        Uses the canonical AdjacencyGraph for adjacency computation.
        """
        # Forward trace
        pins = self._pin_registry.get_architectural_locations(atom.atom_id)
        projection_types = {p.pin_id: p.projection_type for p in pins}

        # Determine adjacencies from the canonical graph
        adjacencies: list[str] = []
        for neighbor_id, _edge in adj_graph.all_neighbors(atom.atom_id):
            if neighbor_id != atom.atom_id and neighbor_id not in adjacencies:
                adjacencies.append(neighbor_id)

        # Determine stores touched
        stores_touched: list[str] = []
        if atom.kind == AtomKind.STORE:
            stores_touched.append(atom.atom_id)
            store_atom_map.setdefault(atom.atom_id, set()).add(atom.atom_id)

        return AnalysisArtifact(
            atom_id=atom.atom_id,
            architectural_imports=pins,
            projection_types=projection_types,
            adjacencies=adjacencies,
            data_flow_in=[],
            data_flow_out=[],
            stores_touched=stores_touched,
            unprojected=len(pins) == 0,
        )

    def _find_disconnected_subgraphs(
        self,
        adj_graph: AdjacencyGraph,
        atoms: list[Any],
    ) -> list[list[str]]:
        """Find disconnected subgraphs using the canonical AdjacencyGraph.

        Delegates to ``AdjacencyGraph.connected_components()`` which
        uses BFS for undirected component detection.
        """
        if not atoms:
            return []

        # Ensure all atom nodes are in the graph
        atom_id_set = {a.atom_id for a in atoms}
        for aid in atom_id_set:
            adj_graph.add_node(aid)

        components = adj_graph.connected_components()

        # Filter components to only include atom IDs (not store-only nodes)
        result: list[list[str]] = []
        for component in components:
            atom_members = [nid for nid in component if nid in atom_id_set]
            if atom_members:
                result.append(sorted(atom_members))

        return result

    def _build_store_touch_edges(
        self,
        store_atom_map: dict[str, set[str]],
    ) -> list[tuple[str, str, str]]:
        """Build store-touch edges: (atom1, store, atom2).

        Two atoms are connected via a store if they both touch it.
        """
        edges: list[tuple[str, str, str]] = []
        for store_id, touching_atoms in store_atom_map.items():
            atoms_list = sorted(touching_atoms)
            for i in range(len(atoms_list)):
                for j in range(i + 1, len(atoms_list)):
                    edges.append((atoms_list[i], store_id, atoms_list[j]))
        return edges
