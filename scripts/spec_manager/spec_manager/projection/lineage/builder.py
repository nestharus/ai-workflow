"""Lineage builder consuming declared pin/graph evidence only.

Lineage assembly in this module does not scan source files for imports.
It consumes explicit projection edges (for example from PinFunctionRegistry)
and projects them into ``ProjectionLineageTable``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import PinFunctionRegistry, ProjectionType


@dataclass
class RawImportRecord:
    """Normalized pin-to-architecture projection edge record."""

    importer_file: str
    importer_location: str
    imported_name: str
    imported_from_module: str
    line_no: int = 0
    signal_type: str = "pin_registry_edge"
    transformation_hint: str | None = None
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)
    projection_type: ProjectionType | None = None
    pin_func_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "importer_file": self.importer_file,
            "importer_location": self.importer_location,
            "imported_name": self.imported_name,
            "imported_from_module": self.imported_from_module,
            "line_no": self.line_no,
            "signal_type": self.signal_type,
            "transformation_hint": self.transformation_hint,
            "confidence": self.confidence,
            "details": dict(self.details),
            "projection_type": self.projection_type.value if self.projection_type else None,
            "pin_func_id": self.pin_func_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawImportRecord:
        """Deserialize from dictionary."""
        return cls(
            importer_file=str(data.get("importer_file", "")),
            importer_location=str(data.get("importer_location", "")),
            imported_name=str(data.get("imported_name", "")),
            imported_from_module=str(data.get("imported_from_module", "")),
            line_no=_coerce_int(data.get("line_no", 0)),
            signal_type=str(data.get("signal_type", "pin_registry_edge")),
            transformation_hint=(
                str(data["transformation_hint"]) if data.get("transformation_hint") else None
            ),
            confidence=_coerce_confidence(data.get("confidence", 1.0), default=1.0),
            details=data.get("details", {}) if isinstance(data.get("details"), dict) else {},
            projection_type=_coerce_projection_type(data.get("projection_type")),
            pin_func_id=(str(data["pin_func_id"]) if data.get("pin_func_id") else None),
        )


@dataclass
class AtomDefinition:
    """Registered atom (pin-function) for lineage tracking."""

    atom_id: str
    function_name: str
    file_path: str
    module_path: str
    signature_hash: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "atom_id": self.atom_id,
            "function_name": self.function_name,
            "file_path": self.file_path,
            "module_path": self.module_path,
            "signature_hash": self.signature_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AtomDefinition:
        """Deserialize from dictionary."""
        return cls(
            atom_id=str(data.get("atom_id", "")),
            function_name=str(data.get("function_name", "")),
            file_path=str(data.get("file_path", "")),
            module_path=str(data.get("module_path", "")),
            signature_hash=str(data.get("signature_hash", "")),
        )


class LineageBuilder:
    """Build ``ProjectionLineageTable`` from declared projection edge records."""

    def __init__(
        self,
        import_records: list[RawImportRecord],
        atoms: list[AtomDefinition],
    ) -> None:
        self.import_records = import_records
        self.atoms = atoms
        self._atoms_by_id: dict[str, AtomDefinition] = {a.atom_id: a for a in atoms}
        self._atoms_by_function: dict[str, AtomDefinition] = {a.function_name: a for a in atoms}

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage edges from declared pin/graph projection records."""
        table = ProjectionLineageTable()

        for record in self.import_records:
            atom = self._resolve_atom(record)
            if atom is None:
                continue
            if record.projection_type is None:
                continue

            table.add_edge(
                from_unit=atom.atom_id,
                to_unit=record.importer_location,
                transformation=record.projection_type,
                confidence=_coerce_confidence(record.confidence, default=1.0),
                details={"import_line": record.line_no, **record.details},
            )

        return table

    def _resolve_atom(self, record: RawImportRecord) -> AtomDefinition | None:
        if record.pin_func_id:
            atom = self._atoms_by_id.get(record.pin_func_id)
            if atom is not None:
                return atom
        return self._atoms_by_function.get(record.imported_name)


def import_records_from_pin_registry(pin_registry: PinFunctionRegistry) -> list[RawImportRecord]:
    """Project ``PinFunctionRegistry.import_edges`` into lineage records."""
    pin_by_id = {pin.pin_func_id: pin for pin in pin_registry.pin_functions}
    records: list[RawImportRecord] = []
    for edge in pin_registry.import_edges:
        pin = pin_by_id.get(edge.pin_func_id)
        if pin is None:
            continue
        records.append(
            RawImportRecord(
                importer_file=edge.arch_file_path,
                importer_location=edge.arch_location,
                imported_name=pin.function_name,
                imported_from_module=pin.module_path,
                line_no=edge.arch_line,
                signal_type="pin_registry_edge",
                transformation_hint=str(edge.projection_type),
                confidence=edge.confidence,
                details={"edge_id": edge.edge_id, "source": "pin_registry"},
                projection_type=edge.projection_type,
                pin_func_id=edge.pin_func_id,
            )
        )
    return records


def compute_signature_hash(file_path: str, function_name: str) -> str | None:
    """Compute a stable hash of canonical function-signature facts."""
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    analysis = analyze_source(source, file_path)

    for func in analysis.functions:
        if func.name != function_name and func.qualified_name != function_name:
            continue
        signature_facts = {
            "name": func.qualified_name or func.name,
            "args": list(func.args),
            "return_annotation": func.return_annotation or "",
            "is_async": bool(func.is_async),
            "decorators": list(func.decorators),
        }
        sig_str = json.dumps(signature_facts, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(sig_str.encode("utf-8")).hexdigest()

    return None


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_confidence(value: Any, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    return max(0.0, min(1.0, confidence))


def _coerce_projection_type(value: Any) -> ProjectionType | None:
    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    try:
        return ProjectionType(raw)
    except ValueError:
        return None


__all__ = [
    "AtomDefinition",
    "LineageBuilder",
    "RawImportRecord",
    "compute_signature_hash",
    "import_records_from_pin_registry",
]
