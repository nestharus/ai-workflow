"""Centralized schema registry for design templates.

This module provides a SchemaRegistry class that loads JSON schemas from
the design templates directory and provides schema validation.

Public API:
    SchemaRegistry: Registry for loading and accessing JSON schemas
    get_default_registry: Get a default schema registry instance

Usage:
    from spec_manager.compliance.schema_registry import SchemaRegistry

    registry = SchemaRegistry()
    schema = registry.get_schema("atoms")
    # Validate an artifact
    result = registry.validate({"file_uid": "...", ...}, "atoms")
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

_logger = logging.getLogger(__name__)

# Default schema directory: sibling 'schemas/' folder next to this file.
_DEFAULT_SCHEMA_DIR = Path(__file__).parent / "schemas"


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
        self._loaded: dict[str, tuple[str, dict[str, Any]]] = {}

    @property
    def schema_dir(self) -> Path:
        """Get the schema directory path."""
        return self._schema_dir

    def get_available_schemas(self) -> list[str]:
        """Get list of available schema IDs."""
        return list(self.SCHEMA_MAP.keys())

    def _schema_path_for(self, schema_id: str) -> Path:
        """Resolve a schema id to an on-disk schema path."""
        if schema_id not in self.SCHEMA_MAP:
            raise KeyError(
                f"Unknown schema ID: {schema_id}. Available: {list(self.SCHEMA_MAP.keys())}"
            )
        return self._schema_dir / self.SCHEMA_MAP[schema_id]

    @staticmethod
    def _content_identity(content: str) -> str:
        """Compute content identity for cache validation."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _load_schema(self, schema_id: str) -> tuple[str, dict[str, Any]]:
        """Load a schema from file and return its content identity."""
        schema_path = self._schema_path_for(schema_id)
        if not schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        _logger.debug(f"Loading schema '{schema_id}' from {schema_path}")
        content = schema_path.read_text(encoding="utf-8")
        return self._content_identity(content), json.loads(content)

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
        identity, schema = self._load_schema(schema_id)
        cached = self._loaded.get(schema_id)
        if cached is not None:
            cached_identity, cached_schema = cached
            if cached_identity == identity:
                return cached_schema
        self._loaded[schema_id] = (identity, schema)
        return schema

    def is_schema_available(self, schema_id: str) -> bool:
        """Check if a schema is available and its file exists.

        Args:
            schema_id: The schema identifier.

        Returns:
            True if the schema file exists, False otherwise.
        """
        if schema_id not in self.SCHEMA_MAP:
            return False
        schema_path = self._schema_path_for(schema_id)
        return schema_path.exists()

    def clear_cache(self) -> None:
        """Clear all cached schemas."""
        self._loaded.clear()


def get_default_registry() -> SchemaRegistry:
    """Get a default schema registry instance.

    Returns:
        A new SchemaRegistry instance.
    """
    return SchemaRegistry()
