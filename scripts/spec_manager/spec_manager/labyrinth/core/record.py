"""Data records for the labyrinth processing pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InputRecord:
    """Input record fed into the rule processing pipeline.

    Attributes:
        record_id: Unique identifier for this record.
        data: Key-value payload with arbitrary fields.
        metadata: Optional metadata (e.g., source, timestamp).
    """

    record_id: str
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the data payload."""
        return self.data.get(key, default)


@dataclass
class OutputRecord:
    """Output record produced by rule processing.

    Attributes:
        record_id: Matches the input record ID.
        source_rule_id: ID of the rule that produced this output.
        data: Key-value output payload.
        metadata: Optional metadata.
        applied_rules: List of rule IDs that were applied.
    """

    record_id: str
    source_rule_id: str
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    applied_rules: list[str] = field(default_factory=list)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the data payload."""
        return self.data.get(key, default)
