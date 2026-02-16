"""ID generation and management for spec decomposition."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path


class IDType(Enum):
    """Types of IDs used in spec decomposition."""

    ENTITY = "E"  # Entity ID (E-001, E-002, ...)
    RELATION = "R"  # Relation ID (R-001, R-002, ...)
    CONTEXT = "C"  # Context ID (C-001, C-002, ...)
    COMPOSITION = "X"  # Composition ID (X-001, X-002, ...)
    ORPHAN = "O"  # Orphan ID (O-001, O-002, ...)
    SNIPPET = "S"  # Snippet ID (S-001, S-002, ...)
    FACT = "F"  # Fact ID anchored to a source line (F-001, F-002, ...)


def generate_id(id_type: IDType, id_map: dict) -> str:
    """Generate a unique ID of the given type.

    Args:
        id_type: Type of ID to generate
        id_map: Current ID map to check for existing IDs

    Returns:
        New unique ID (e.g., "E-001", "R-002")
    """
    prefix = id_type.value

    # Find highest existing number for this prefix
    existing_nums = []
    for id_str in id_map:
        if id_str.startswith(f"{prefix}-"):
            num_part = id_str.split("-")[1]
            if num_part.isdigit():
                existing_nums.append(int(num_part))

    next_num = max(existing_nums, default=0) + 1
    return f"{prefix}-{next_num:03d}"


def load_id_map(workspace: Path) -> dict:
    """Load ID map from workspace.

    The ID map tracks:
    {
        "E-001": [
            {"file": "spec.md", "line": 42, "type": "entity"},
            {"file": "spec.md", "line": 89, "type": "entity"}
        ],
        "R-001": [
            {
                "file": "spec.md",
                "line": 156,
                "type": "relation",
                "source": "E-001",
                "target": "E-002",
            }
        ]
    }
    """
    id_map_file = workspace / "id_map.json"
    if id_map_file.exists():
        return json.loads(id_map_file.read_text())
    return {}


def save_id_map(workspace: Path, id_map: dict) -> None:
    """Save ID map to workspace."""
    id_map_file = workspace / "id_map.json"
    id_map_file.write_text(json.dumps(id_map, indent=2))


def get_ids_by_type(id_map: dict, id_type: IDType) -> list[str]:
    """Get all IDs of a specific type."""
    prefix = id_type.value
    return [id_str for id_str in id_map if id_str.startswith(f"{prefix}-")]


def get_source_lines(id_map: dict, id_str: str) -> list[dict]:
    """Get all source lines associated with an ID."""
    return id_map.get(id_str, [])
