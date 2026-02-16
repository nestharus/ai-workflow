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
        if not isinstance(data, dict):
            raise TypeError("RawImportRecord payload must be a dictionary.")

        details_raw = data.get("details", {})
        if not isinstance(details_raw, dict):
            raise TypeError("RawImportRecord.details must be an object.")

        return cls(
            importer_file=_require_non_empty_str(
                data.get("importer_file"), field_name="importer_file"
            ),
            importer_location=_require_non_empty_str(
                data.get("importer_location"),
                field_name="importer_location",
            ),
            imported_name=_require_non_empty_str(
                data.get("imported_name"), field_name="imported_name"
            ),
            imported_from_module=_require_non_empty_str(
                data.get("imported_from_module"),
                field_name="imported_from_module",
            ),
            line_no=_require_non_negative_int(data.get("line_no", 0), field_name="line_no"),
            signal_type=_require_non_empty_str(
                data.get("signal_type", "pin_registry_edge"),
                field_name="signal_type",
            ),
            transformation_hint=(
                _require_non_empty_str(
                    data["transformation_hint"], field_name="transformation_hint"
                )
                if data.get("transformation_hint") is not None
                else None
            ),
            confidence=_require_confidence(data.get("confidence", 1.0), field_name="confidence"),
            details=details_raw,
            projection_type=_parse_projection_type(data.get("projection_type")),
            pin_func_id=_optional_non_empty_str(data.get("pin_func_id"), field_name="pin_func_id"),
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


@dataclass
class LineageRecordRejection:
    """Rejected record with explicit reason for traceability."""

    index: int
    reason: str
    record: RawImportRecord

    def to_dict(self) -> dict[str, Any]:
        """Serialize rejection for diagnostics output."""
        return {
            "index": self.index,
            "reason": self.reason,
            "record": self.record.to_dict(),
        }


class LineageBuilder:
    """Build ``ProjectionLineageTable`` from declared projection edge records."""

    def __init__(
        self,
        import_records: list[RawImportRecord],
        atoms: list[AtomDefinition],
    ) -> None:
        self.import_records = import_records
        self.atoms = atoms
        self.rejected_records: list[LineageRecordRejection] = []
        self._atoms_by_id: dict[str, AtomDefinition] = {}
        self._atoms_by_module_function: dict[tuple[str, str], AtomDefinition] = {}

        for atom in atoms:
            if atom.atom_id in self._atoms_by_id:
                raise ValueError(f"Duplicate atom_id in lineage atoms: {atom.atom_id}")
            self._atoms_by_id[atom.atom_id] = atom

            key = (atom.module_path, atom.function_name)
            if key in self._atoms_by_module_function:
                raise ValueError(
                    "Ambiguous atom identity for module/function key "
                    f"{atom.module_path}:{atom.function_name}"
                )
            self._atoms_by_module_function[key] = atom

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage edges from declared pin/graph projection records."""
        table = ProjectionLineageTable()
        self.rejected_records = []

        for index, record in enumerate(self.import_records):
            atom, reason = self._resolve_atom(record)
            if atom is None:
                self._reject(index=index, record=record, reason=reason)
                continue
            if record.projection_type is None:
                self._reject(index=index, record=record, reason="missing_projection_type")
                continue

            try:
                confidence = _require_confidence(record.confidence, field_name="confidence")
            except ValueError as exc:
                self._reject(index=index, record=record, reason=f"invalid_confidence:{exc}")
                continue

            table.add_edge(
                from_unit=atom.atom_id,
                to_unit=record.importer_location,
                transformation=record.projection_type,
                confidence=confidence,
                details={
                    "import_line": record.line_no,
                    "importer_file": record.importer_file,
                    "imported_from_module": record.imported_from_module,
                    "imported_name": record.imported_name,
                    **record.details,
                },
            )

        return table

    def _resolve_atom(self, record: RawImportRecord) -> tuple[AtomDefinition | None, str]:
        if record.pin_func_id:
            atom = self._atoms_by_id.get(record.pin_func_id)
            if atom is not None:
                return atom, ""
            return None, f"unknown_pin_func_id:{record.pin_func_id}"

        key = (record.imported_from_module, record.imported_name)
        atom = self._atoms_by_module_function.get(key)
        if atom is not None:
            return atom, ""

        return (
            None,
            "missing_pin_func_id_and_no_unique_module_function_match:"
            f"{record.imported_from_module}:{record.imported_name}",
        )

    def _reject(self, *, index: int, record: RawImportRecord, reason: str) -> None:
        self.rejected_records.append(
            LineageRecordRejection(index=index, reason=reason, record=record)
        )


def import_records_from_pin_registry(pin_registry: PinFunctionRegistry) -> list[RawImportRecord]:
    """Project ``PinFunctionRegistry.import_edges`` into lineage records."""
    pin_by_id = {pin.pin_func_id: pin for pin in pin_registry.pin_functions}
    records: list[RawImportRecord] = []
    for edge in pin_registry.import_edges:
        pin = pin_by_id.get(edge.pin_func_id)
        if pin is None:
            records.append(
                RawImportRecord(
                    importer_file=edge.arch_file_path,
                    importer_location=edge.arch_location,
                    imported_name=edge.pin_func_id,
                    imported_from_module="__unknown__",
                    line_no=edge.arch_line,
                    signal_type="pin_registry_edge",
                    transformation_hint=edge.projection_type.value,
                    confidence=edge.confidence,
                    details={
                        "edge_id": edge.edge_id,
                        "source": "pin_registry",
                        "invalid_edge": "pin_func_id_not_found",
                    },
                    projection_type=edge.projection_type,
                    pin_func_id=edge.pin_func_id,
                )
            )
            continue
        records.append(
            RawImportRecord(
                importer_file=edge.arch_file_path,
                importer_location=edge.arch_location,
                imported_name=pin.function_name,
                imported_from_module=pin.module_path,
                line_no=edge.arch_line,
                signal_type="pin_registry_edge",
                transformation_hint=edge.projection_type.value,
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


def _require_non_empty_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


def _optional_non_empty_str(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string when provided.")
    cleaned = value.strip()
    return cleaned or None


def _require_non_negative_int(value: Any, *, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer.") from None
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return parsed


def _require_confidence(value: Any, *, field_name: str) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a float.") from None
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"{field_name} must be within [0.0, 1.0].")
    return confidence


def _parse_projection_type(value: Any) -> ProjectionType | None:
    if value is None:
        return None
    if isinstance(value, ProjectionType):
        return value
    if not isinstance(value, str):
        raise TypeError("projection_type must be a string when provided.")
    raw = value.strip().lower()
    if not raw:
        return None
    try:
        return ProjectionType(raw)
    except ValueError:
        raise ValueError(f"Invalid projection_type: {value}") from None


__all__ = [
    "AtomDefinition",
    "LineageBuilder",
    "LineageRecordRejection",
    "RawImportRecord",
    "compute_signature_hash",
    "import_records_from_pin_registry",
]
