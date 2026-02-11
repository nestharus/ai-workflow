"""Centralized schema registry for design templates.

This module provides a SchemaRegistry class that loads JSON schemas from
the design templates directory and provides schema validation.

Public API:
    SchemaRegistry: Registry for loading and accessing JSON schemas
    get_default_registry: Get the singleton default registry instance

Usage:
    from spec_manager.compliance.schema_registry import SchemaRegistry

    registry = SchemaRegistry()
    schema = registry.get_schema("atoms")
    # Validate an artifact
    result = registry.validate({"file_uid": "...", ...}, "atoms")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, ClassVar

_logger = logging.getLogger(__name__)

# Default schema directory relative to this file
# Path: scripts/spec_manager/spec_manager/compliance/schema_registry.py
# parents[0] = compliance/
# parents[1] = spec_manager/spec_manager/
# parents[2] = spec_manager/
# parents[3] = scripts/
# parents[4] = ai-workflow/ (project root)
# Design templates: .tasks/plans/spec manager/design/templates/
_DEFAULT_SCHEMA_DIR = Path(__file__).parents[4] / ".tasks/plans/spec manager/design/templates"


class SchemaRegistry:
    """Centralized registry for JSON schemas from design templates.

    Provides lazy loading of schemas and schema-based validation.
    Schemas are loaded from the design templates directory on first access.

    Attributes:
        SCHEMA_MAP: Mapping from schema IDs to filenames.
    """

    SCHEMA_MAP: ClassVar[dict[str, str]] = {
        "atoms": "atoms.schema.json",
        "section_map": "section_map.schema.json",
        "decomposition_output": "decomposition_output.schema.json",
        "library_labels": "library_labels.schema.json",
        "gap_element": "gap_element.schema.json",
        "task_plan": "task_plan.schema.json",
        "derived_elements": "derived_elements.schema.json",
        "tag_index_delta": "tag_index_delta.schema.json",
    }

    def __init__(self, schema_dir: Path | None = None) -> None:
        """Initialize the schema registry.

        Args:
            schema_dir: Directory containing schema files. Defaults to design templates.
        """
        self._schema_dir = schema_dir or _DEFAULT_SCHEMA_DIR
        self._loaded: dict[str, dict[str, Any]] = {}

    @property
    def schema_dir(self) -> Path:
        """Get the schema directory path."""
        return self._schema_dir

    def get_available_schemas(self) -> list[str]:
        """Get list of available schema IDs."""
        return list(self.SCHEMA_MAP.keys())

    def _load_schema(self, schema_id: str) -> dict[str, Any]:
        """Load a schema from file.

        Args:
            schema_id: The schema identifier (e.g., "atoms", "derived_elements").

        Returns:
            The JSON schema as a dictionary.

        Raises:
            KeyError: If schema_id is not in SCHEMA_MAP.
            FileNotFoundError: If schema file doesn't exist.
            json.JSONDecodeError: If schema file is not valid JSON.
        """
        if schema_id not in self.SCHEMA_MAP:
            raise KeyError(
                f"Unknown schema ID: {schema_id}. Available: {list(self.SCHEMA_MAP.keys())}"
            )

        filename = self.SCHEMA_MAP[schema_id]
        schema_path = self._schema_dir / filename

        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        _logger.debug(f"Loading schema '{schema_id}' from {schema_path}")
        with open(schema_path, encoding="utf-8") as f:
            return json.load(f)

    def get_schema(self, schema_id: str) -> dict[str, Any]:
        """Get a schema by ID, loading from file if needed.

        Schemas are cached after first load for performance.

        Args:
            schema_id: The schema identifier.

        Returns:
            The JSON schema as a dictionary.

        Raises:
            KeyError: If schema_id is unknown.
            FileNotFoundError: If schema file doesn't exist.
        """
        if schema_id not in self._loaded:
            self._loaded[schema_id] = self._load_schema(schema_id)
        return self._loaded[schema_id]

    def is_schema_available(self, schema_id: str) -> bool:
        """Check if a schema is available and its file exists.

        Args:
            schema_id: The schema identifier.

        Returns:
            True if the schema file exists, False otherwise.
        """
        if schema_id not in self.SCHEMA_MAP:
            return False
        filename = self.SCHEMA_MAP[schema_id]
        schema_path = self._schema_dir / filename
        return schema_path.exists()

    def clear_cache(self) -> None:
        """Clear all cached schemas."""
        self._loaded.clear()


# Singleton default registry
_default_registry: SchemaRegistry | None = None


def get_default_registry() -> SchemaRegistry:
    """Get the singleton default schema registry instance.

    Returns:
        The default SchemaRegistry instance.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = SchemaRegistry()
    return _default_registry
