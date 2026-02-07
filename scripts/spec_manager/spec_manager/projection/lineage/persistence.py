"""Persistence utilities for lineage tracking data.

Provides JSON read/write for ProjectionLineageTable and ImportGraph,
following the workspace indexes pattern used by edge_list.json and
interface_index.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from spec_manager.projection.lineage.import_graph import ImportGraph
from spec_manager.projection.lineage.table import ProjectionLineageTable


def save_lineage_table(table: ProjectionLineageTable, path: Path) -> None:
    """Save lineage table to a JSON file.

    Args:
        table: The lineage table to persist.
        path: File path to write to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = table.to_dict()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_lineage_table(path: Path) -> ProjectionLineageTable:
    """Load lineage table from a JSON file.

    Args:
        path: File path to read from.

    Returns:
        Reconstructed ProjectionLineageTable.
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return ProjectionLineageTable.from_dict(data)


def save_import_graph(graph: ImportGraph, path: Path) -> None:
    """Save import graph to a JSON file.

    Args:
        graph: The import graph to persist.
        path: File path to write to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = graph.to_dict()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_import_graph(path: Path) -> ImportGraph:
    """Load import graph from a JSON file.

    Args:
        path: File path to read from.

    Returns:
        Reconstructed ImportGraph.
    """
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    return ImportGraph.from_dict(data)


__all__ = [
    "load_import_graph",
    "load_lineage_table",
    "save_import_graph",
    "save_lineage_table",
]
