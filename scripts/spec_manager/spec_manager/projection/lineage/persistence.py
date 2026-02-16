"""Persistence utilities for lineage tracking data.

Provides JSON read/write for ProjectionLineageTable,
following the workspace indexes pattern used by edge_list.json and
interface_index.json.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from spec_manager.projection.lineage.table import ProjectionLineageTable


def save_lineage_table(table: ProjectionLineageTable, path: Path) -> None:
    """Save lineage table to a JSON file.

    Args:
        table: The lineage table to persist.
        path: File path to write to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        history_dir = path.parent / f".{path.stem}_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        snapshot_name = f"{path.stem}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.json"
        snapshot_path = history_dir / snapshot_name
        snapshot_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

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


__all__ = [
    "load_lineage_table",
    "save_lineage_table",
]
