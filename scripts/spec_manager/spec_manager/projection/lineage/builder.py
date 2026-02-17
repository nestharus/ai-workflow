"""Shape-level lineage builder for deterministic import-scan evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.projection.lineage.edges import ProjectionType
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.routing.shapes import ShapeId, ShapePackIndex, resolve_shape_for_file

SignalType = Literal["import_scan"]
EdgeKind = Literal["declared", "observed"]

_SINGLE_LAYER_PHASES: tuple[PhaseId, ...] = ("libraries", "architecture", "quality")


@dataclass
class RawImportRecord:
    importer_file: str
    importer_shape_id: ShapeId | None
    imported_module: str
    imported_shape_id: ShapeId | None
    line_no: int
    signal_type: SignalType = "import_scan"
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "importer_file": self.importer_file,
            "importer_shape_id": str(self.importer_shape_id) if self.importer_shape_id else None,
            "imported_module": self.imported_module,
            "imported_shape_id": str(self.imported_shape_id) if self.imported_shape_id else None,
            "line_no": self.line_no,
            "signal_type": self.signal_type,
            "confidence": self.confidence,
            "details": dict(self.details),
        }
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawImportRecord:
        if not isinstance(data, dict):
            raise TypeError("RawImportRecord payload must be an object.")

        details_raw = data.get("details", {})
        if not isinstance(details_raw, dict):
            raise TypeError("RawImportRecord.details must be an object.")

        signal = _require_non_empty_str(data.get("signal_type", "import_scan"), field_name="signal_type")
        if signal != "import_scan":
            raise ValueError("signal_type must be 'import_scan'.")

        importer_shape_raw = data.get("importer_shape_id")
        if importer_shape_raw is None:
            importer_shape_id: ShapeId | None = None
        elif not isinstance(importer_shape_raw, str):
            raise TypeError("importer_shape_id must be a string or null.")
        else:
            importer_shape_id = ShapeId(importer_shape_raw.strip()) or None
            if not importer_shape_raw.strip():
                importer_shape_id = None

        imported_shape_raw = data.get("imported_shape_id")
        if imported_shape_raw is None:
            imported_shape_id: ShapeId | None = None
        elif not isinstance(imported_shape_raw, str):
            raise TypeError("imported_shape_id must be a string or null.")
        else:
            imported_shape_id = ShapeId(imported_shape_raw.strip()) or None
            if not imported_shape_raw.strip():
                imported_shape_id = None

        return cls(
            importer_file=_require_non_empty_str(data.get("importer_file"), field_name="importer_file"),
            importer_shape_id=importer_shape_id,
            imported_module=_require_non_empty_str(
                data.get("imported_module"),
                field_name="imported_module",
            ),
            imported_shape_id=imported_shape_id,
            line_no=_require_non_negative_int(data.get("line_no", 0), field_name="line_no"),
            signal_type="import_scan",
            confidence=_require_confidence(data.get("confidence", 1.0), field_name="confidence"),
            details=details_raw,
        )


@dataclass
class ShapeLineageEdge:
    from_shape_id: ShapeId
    to_shape_id: ShapeId
    evidence_refs: list[str] = field(default_factory=list)
    edge_kind: EdgeKind = "observed"
    confidence: float = 1.0


@dataclass
class _LineageRejection:
    index: int
    reason: str
    record: RawImportRecord


def import_records_from_dependency_scan(
    scan_payload: list[dict[str, Any]],
    shape_index: ShapePackIndex,
) -> list[RawImportRecord]:
    # IMPL(single-layer): this conversion is consumed by matcher and architecture
    # drift checks across libraries/architecture/quality.
    """Convert dependency scan payload to shape-centric import records."""

    if not isinstance(scan_payload, list):
        raise TypeError("scan_payload must be a list.")
    if not isinstance(shape_index, ShapePackIndex):
        raise TypeError("shape_index must be ShapePackIndex.")

    known_shape_ids = {str(shape_id) for shape_id in shape_index.shapes}
    records: list[RawImportRecord] = []
    for index, raw in enumerate(scan_payload):
        if not isinstance(raw, dict):
            raise TypeError(f"scan_payload[{index}] must be a dict.")

        record = RawImportRecord.from_dict(raw)
        record.details = dict(record.details)

        rejection_reasons: list[str] = []
        reasons_hint = _coerce_reasons(record)
        if reasons_hint:
            rejection_reasons.extend(reasons_hint)

        if record.importer_shape_id is not None:
            if str(record.importer_shape_id) not in known_shape_ids:
                rejection_reasons.append(
                    f"importer_shape_id_not_in_shape_index:{record.importer_shape_id}"
                )
                record.importer_shape_id = None
        if record.importer_shape_id is None:
            resolved, reason = _resolve_shape_for_file(record.importer_file, shape_index)
            if resolved is None:
                rejection_reasons.append(reason)
            else:
                record.importer_shape_id = resolved

        if record.imported_shape_id is not None:
            if str(record.imported_shape_id) not in known_shape_ids:
                rejection_reasons.append(
                    f"imported_shape_id_not_in_shape_index:{record.imported_shape_id}"
                )
                record.imported_shape_id = None
        if record.imported_shape_id is None:
            resolved, reason = _resolve_shape_for_module(record.imported_module, shape_index)
            if resolved is None:
                rejection_reasons.append(reason)
            else:
                record.imported_shape_id = resolved

        if rejection_reasons:
            record.details["rejection_reasons"] = sorted(set(rejection_reasons))

        records.append(record)

    return records


def build_shape_lineage(import_records: list[RawImportRecord]) -> ProjectionLineageTable:
    # IMPL(single-layer): preserve deterministic audit trail by moving unresolved
    # mappings and self-loops into table.removed_edges.
    """Build shape-level import lineage edges from normalized import records."""
    if not isinstance(import_records, list):
        raise TypeError("import_records must be a list.")

    table = ProjectionLineageTable()
    table.removed_edges = []

    for index, record in enumerate(import_records):
        if isinstance(record, dict):
            record = RawImportRecord.from_dict(record)
        elif not isinstance(record, RawImportRecord):
            raise TypeError(f"import_records[{index}] must be RawImportRecord.")

        reason = _validate_shape_record(record)
        if reason is not None:
            _record_rejection(table, index=index, record=record, reason=reason)
            continue

        edge_kind = _coerce_edge_kind(record.details.get("edge_kind"))
        evidence_refs = _coerce_evidence_refs(record.details.get("evidence_refs"))
        if record.line_no:
            evidence_refs.append(f"{record.importer_file}:{record.line_no}")
        evidence_refs = sorted(set(evidence_refs))

        shape_edge = ShapeLineageEdge(
            from_shape_id=record.importer_shape_id,
            to_shape_id=record.imported_shape_id,
            evidence_refs=evidence_refs,
            edge_kind=edge_kind,
            confidence=_require_confidence(record.confidence, field_name="confidence"),
        )

        details = dict(record.details)
        details["signal_type"] = record.signal_type
        details["importer_file"] = record.importer_file
        details["imported_module"] = record.imported_module
        details["from_shape_id"] = str(shape_edge.from_shape_id)
        details["to_shape_id"] = str(shape_edge.to_shape_id)
        details["edge_kind"] = shape_edge.edge_kind
        details["evidence_refs"] = list(shape_edge.evidence_refs)

        table.add_edge(
            from_unit=str(shape_edge.from_shape_id),
            to_unit=str(shape_edge.to_shape_id),
            transformation=_projection_transformation_from_kind(shape_edge.edge_kind),
            confidence=shape_edge.confidence,
            details=details,
        )

    return table


def _coerce_reasons(record: RawImportRecord) -> list[str]:
    reasons: list[str] = []
    if not record.importer_file:
        reasons.append("missing_importer_file")
    if not record.imported_module:
        reasons.append("missing_imported_module")
    if record.line_no < 0:
        reasons.append("negative_line_no")
    return reasons


def _resolve_shape_for_file(path: str, shape_index: ShapePackIndex) -> tuple[ShapeId | None, str]:
    shape_id = resolve_shape_for_file(path, shape_index)
    if shape_id is None:
        return None, f"unresolved_shape_for_importer_file:{path}"
    return shape_id, ""


def _resolve_shape_for_module(
    imported_module: str,
    shape_index: ShapePackIndex,
) -> tuple[ShapeId | None, str]:
    module = _normalize_import_module(imported_module)
    if not module:
        return None, "missing_imported_module"

    candidates = _module_to_paths(module)
    for candidate in candidates:
        shape_id = resolve_shape_for_file(candidate, shape_index)
        if shape_id is not None:
            return shape_id, ""

    return (
        None,
        f"unresolved_shape_for_imported_module:{imported_module}",
    )


def _normalize_import_module(value: str) -> str:
    normalized = value.strip().replace("\\", "/").strip()
    normalized = normalized.lstrip(".")
    normalized = normalized.replace(".", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.strip("/")


def _module_to_paths(module: str) -> list[str]:
    parts = [part for part in module.split("/") if part]
    if not parts:
        return []

    candidates: list[str] = []
    for length in range(len(parts), 0, -1):
        base = "/".join(parts[:length])
        for suffix in ("", ".py", "/__init__.py"):
            candidate = f"{base}{suffix}"
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _validate_shape_record(record: RawImportRecord) -> str | None:
    if record.signal_type != "import_scan":
        return "unsupported_signal_type"

    if record.importer_shape_id is None:
        return "unresolved_importer_shape"

    if record.imported_shape_id is None:
        return "unresolved_imported_shape"

    if record.importer_shape_id == record.imported_shape_id:
        return "self_loop"

    try:
        _require_non_empty_str(record.importer_file, field_name="importer_file")
        _require_non_empty_str(record.imported_module, field_name="imported_module")
        _require_non_negative_int(record.line_no, field_name="line_no")
        _require_confidence(record.confidence, field_name="confidence")
    except (TypeError, ValueError) as exc:
        return str(exc)

    return None


def _coerce_edge_kind(value: Any) -> EdgeKind:
    if value is None:
        return "observed"
    if not isinstance(value, str):
        raise TypeError("edge_kind must be a string.")
    normalized = value.strip().lower()
    if normalized not in {"declared", "observed"}:
        raise ValueError("edge_kind must be 'declared' or 'observed'.")
    return normalized  # type: ignore[return-value]


def _coerce_evidence_refs(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("evidence_refs must be a list.")
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item:
            refs.append(item)
    return refs


def _projection_transformation_from_kind(kind: EdgeKind) -> ProjectionType:
    if kind == "declared":
        return ProjectionType.PASS_THROUGH
    return ProjectionType.PASS_THROUGH


def _record_rejection(
    table: ProjectionLineageTable,
    *,
    index: int,
    record: RawImportRecord,
    reason: str,
) -> None:
    table.removed_edges.append(
        {
            "index": index,
            "rejected_at": datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
            "reason": reason,
            "record": record.to_dict(),
        }
    )


def _require_non_empty_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string.")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty.")
    return cleaned


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


__all__ = [
    "_SINGLE_LAYER_PHASES",
    "RawImportRecord",
    "ShapeLineageEdge",
    "build_shape_lineage",
    "import_records_from_dependency_scan",
]
