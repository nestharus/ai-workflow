"""Provenance tracking for atom functions.

Tracks introduced_by, modified_by, and source_location chains for
each pin-function, enabling audit trails for layer promotion.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.schemas.pin_functions import PinFunctionRegistry


@dataclass
class AtomProvenance:
    """Provenance record for a single atom function.

    Mirrors TrackedUnit's provenance pattern but at the function level.

    Attributes:
        pin_func_id: Pin-function ID (e.g., "PFUNC-0001").
        function_name: Qualified function name.
        file_path: File where the function is defined.
        introduced_by: Plan/patch/commit that first created this function.
        modified_by: Ordered list of plans/patches/commits that modified it.
        source_location: Where in the spec research the function's details
            came from (file:section or evidence ID).
        content_hash: Current SHA-256 of function body.
        created_at: ISO-8601 timestamp of first detection.
        last_modified_at: ISO-8601 timestamp of last change detection.
    """

    pin_func_id: str
    function_name: str
    file_path: str
    introduced_by: str
    modified_by: list[str] = field(default_factory=list)
    source_location: str = ""
    content_hash: str = ""
    created_at: str = ""
    last_modified_at: str = ""

    def add_modification(self, modifier: str) -> None:
        """Record a modification."""
        if modifier not in self.modified_by:
            self.modified_by.append(modifier)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "pin_func_id": self.pin_func_id,
            "function_name": self.function_name,
            "file_path": self.file_path,
            "introduced_by": self.introduced_by,
            "modified_by": self.modified_by,
            "source_location": self.source_location,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "last_modified_at": self.last_modified_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtomProvenance:
        """Deserialize from dictionary."""
        return cls(
            pin_func_id=data["pin_func_id"],
            function_name=data["function_name"],
            file_path=data["file_path"],
            introduced_by=data["introduced_by"],
            modified_by=data.get("modified_by", []),
            source_location=data.get("source_location", ""),
            content_hash=data.get("content_hash", ""),
            created_at=data.get("created_at", ""),
            last_modified_at=data.get("last_modified_at", ""),
        )


@dataclass
class ProvenanceRegistry:
    """Registry of all atom function provenance records.

    Persisted alongside the PinFunctionRegistry.

    Attributes:
        records: Provenance records keyed by pin_func_id.
        schema_version: Version of the provenance schema.
    """

    records: dict[str, AtomProvenance] = field(default_factory=dict)
    schema_version: str = "1.0"

    def get(self, pin_func_id: str) -> AtomProvenance | None:
        """Get provenance record by pin_func_id."""
        return self.records.get(pin_func_id)

    def upsert(self, provenance: AtomProvenance) -> None:
        """Insert or update a provenance record."""
        self.records[provenance.pin_func_id] = provenance

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "schema_version": self.schema_version,
            "records": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceRegistry:
        """Deserialize from dictionary."""
        registry = cls(schema_version=data.get("schema_version", "1.0"))
        for key, record_data in data.get("records", {}).items():
            registry.records[key] = AtomProvenance.from_dict(record_data)
        return registry

    def save(self, path: Path) -> None:
        """Write provenance registry to disk."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> ProvenanceRegistry:
        """Load provenance registry from disk."""
        path = Path(path)
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


def update_provenance_from_registry(
    pin_registry: PinFunctionRegistry,
    existing_provenance: ProvenanceRegistry,
    modifier: str = "scan",
) -> ProvenanceRegistry:
    """Update provenance records based on current pin-function registry.

    For each pin-function in the registry:
    - If new (not in existing provenance): create record with introduced_by=modifier.
    - If content_hash changed: add modifier to modified_by chain.
    - If unchanged: no update.

    Args:
        pin_registry: Current PinFunctionRegistry.
        existing_provenance: Previous provenance state.
        modifier: Identifier for the current modification source.

    Returns:
        Updated ProvenanceRegistry.
    """
    now = datetime.now(UTC).isoformat()
    updated = ProvenanceRegistry(
        schema_version=existing_provenance.schema_version,
        records=dict(existing_provenance.records),
    )

    for pin_func in pin_registry.pin_functions:
        existing = updated.get(pin_func.pin_func_id)

        if existing is None:
            # New function: create provenance record
            updated.upsert(
                AtomProvenance(
                    pin_func_id=pin_func.pin_func_id,
                    function_name=pin_func.function_name,
                    file_path=pin_func.file_path,
                    introduced_by=modifier,
                    modified_by=[],
                    source_location="",
                    content_hash=pin_func.content_hash,
                    created_at=now,
                    last_modified_at=now,
                )
            )
        elif existing.content_hash != pin_func.content_hash:
            # Content changed: record modification
            existing.add_modification(modifier)
            existing.content_hash = pin_func.content_hash
            existing.last_modified_at = now
            existing.file_path = pin_func.file_path
            existing.function_name = pin_func.function_name
        # If unchanged, keep existing record as-is

    return updated


def check_provenance_complete(
    pin_registry: PinFunctionRegistry,
    provenance_registry: ProvenanceRegistry,
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: All atom functions have complete provenance.

    Checks that every pin-function in the registry has a corresponding
    provenance record with non-empty introduced_by and optionally
    source_location.

    gate_spec.params:
        - require_source_location (bool, default False): Whether
            source_location must be non-empty.

    Args:
        pin_registry: Current PinFunctionRegistry.
        provenance_registry: Current ProvenanceRegistry.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for functions missing provenance.
    """
    start = time.monotonic()
    require_source = gate_spec.params.get("require_source_location", False)

    findings: list[dict[str, Any]] = []

    for pin_func in pin_registry.pin_functions:
        record = provenance_registry.get(pin_func.pin_func_id)
        issues: list[str] = []

        if record is None:
            issues.append("No provenance record found")
        else:
            if not record.introduced_by:
                issues.append("Missing introduced_by")
            if require_source and not record.source_location:
                issues.append("Missing source_location")

        if issues:
            findings.append(
                {
                    "pin_func_id": pin_func.pin_func_id,
                    "function_name": pin_func.function_name,
                    "file_path": pin_func.file_path,
                    "issues": issues,
                }
            )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    total = len(pin_registry.pin_functions)
    complete = total - len(findings)

    return GateCheckResult(
        gate_id=GateId.PROVENANCE_COMPLETE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=(complete / total) if total > 0 else 1.0,
        findings=findings,
        summary=(
            f"All {total} pin-function(s) have complete provenance"
            if passed
            else f"{len(findings)} of {total} pin-function(s) missing provenance"
        ),
        duration_ms=duration,
    )
