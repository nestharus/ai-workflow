"""Lineage builder: consumes declared pin/edge evidence.

Lineage assembly uses pre-produced edge records (for example from
PinFunctionRegistry). Source scanning helpers remain optional fallback
discovery backends and are not authoritative.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source, infer_code_signals
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import PinFunctionRegistry, ProjectionType

# Language-agnostic import patterns (no AST dependency)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)
_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)


@dataclass
class RawImportRecord:
    """A raw import relationship from static analysis.

    Lightweight record used by LineageBuilder to trace atom-to-architecture
    projections. Contains the minimum fields needed for lineage building.

    Attributes:
        importer_file: File that contains the import statement.
        importer_location: file:class.method or file:module-level.
        imported_name: The name being imported (function/class).
        imported_from_module: The module being imported from.
        line_no: Line number of the import statement.
    """

    importer_file: str
    importer_location: str
    imported_name: str
    imported_from_module: str
    line_no: int = 0
    signal_type: str = "import_edge"
    transformation_hint: str | None = None
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)
    projection_type: ProjectionType | None = None

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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawImportRecord:
        """Deserialize from dictionary."""
        return cls(
            importer_file=data["importer_file"],
            importer_location=data["importer_location"],
            imported_name=data["imported_name"],
            imported_from_module=data["imported_from_module"],
            line_no=_coerce_int(data.get("line_no", 0)),
            signal_type=str(data.get("signal_type", "import_edge")),
            transformation_hint=(
                str(data["transformation_hint"]) if data.get("transformation_hint") else None
            ),
            confidence=_coerce_confidence(data.get("confidence", 1.0), default=1.0),
            details=data.get("details", {}) if isinstance(data.get("details"), dict) else {},
            projection_type=_coerce_projection_type(data.get("projection_type")),
        )


def scan_imports_from_directory(
    root_dir: Path,
    exclude_patterns: list[str] | None = None,
) -> list[RawImportRecord]:
    """Scan all Python files in a directory for import statements.

    Primary path uses ``infer_code_signals(requested={"import_edges"})``.
    Regex extraction remains only as a fallback migration path when no
    inferred edge data is returned.

    Args:
        root_dir: Root directory to scan.
        exclude_patterns: Glob patterns to exclude (e.g., ["__pycache__"]).

    Returns:
        List of RawImportRecord entries found across all files.
    """
    from spec_manager.core.language import source_rglob

    if exclude_patterns is None:
        exclude_patterns = []

    records: list[RawImportRecord] = []
    for py_file in source_rglob(root_dir):
        # Apply any additional caller-provided exclude patterns
        if exclude_patterns:
            skip = False
            for part in py_file.parts:
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(part, pattern):
                        skip = True
                        break
                if skip:
                    break
            if skip:
                continue
        records.extend(_scan_file_imports(py_file))
    return records


def scan_imports_from_files(file_paths: list[Path]) -> list[RawImportRecord]:
    """Scan specific files for import statements.

    Args:
        file_paths: List of source file paths to analyze.

    Returns:
        List of RawImportRecord entries found across all files.
    """
    from spec_manager.core.language import is_source_file

    records: list[RawImportRecord] = []
    for file_path in file_paths:
        if is_source_file(file_path.suffix) and file_path.exists():
            records.extend(_scan_file_imports(file_path))
    return records


def _scan_file_imports(file_path: Path) -> list[RawImportRecord]:
    """Scan a single source file for import statements.

    Uses inferred import-edge signals first, then regex fallback.

    Args:
        file_path: Path to source file.

    Returns:
        List of RawImportRecord entries found in the file.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    inferred_records = _scan_file_imports_from_signals(file_path, source)
    if inferred_records:
        return inferred_records

    return _scan_file_imports_with_regex(file_path, source)


def _scan_file_imports_from_signals(file_path: Path, source: str) -> list[RawImportRecord]:
    """Scan imports by consuming inferred code-signal facets."""
    signal_payload = infer_code_signals(
        file_path=str(file_path),
        source_text=source,
        spans=[],
        requested={"import_edges"},
    )
    if not isinstance(signal_payload, dict):
        return []

    records: list[RawImportRecord] = []
    for edge in _extract_import_edges(signal_payload):
        record = _import_record_from_edge(edge, str(file_path))
        if record is not None:
            records.append(record)
    return records


def _extract_import_edges(signal_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract import-like edges from a signal payload."""
    for key in ("import_edges", "lineage_edges"):
        value = signal_payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    value = signal_payload.get("edges")
    if isinstance(value, list):
        return [
            item
            for item in value
            if isinstance(item, dict)
            and str(item.get("signal_type", "")).lower()
            in {"import", "import_edge", "reference", "reference_edge"}
        ]

    facets = signal_payload.get("facets")
    if isinstance(facets, dict):
        value = facets.get("import_edges")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return []


def _import_record_from_edge(edge: dict[str, Any], default_file: str) -> RawImportRecord | None:
    """Normalize one inferred edge dictionary into a RawImportRecord."""
    imported_name = str(
        edge.get("imported_name")
        or edge.get("import_name")
        or edge.get("dst_name")
        or edge.get("target_name")
        or ""
    ).strip()
    if not imported_name:
        return None

    importer_file = str(edge.get("importer_file") or edge.get("source_file") or default_file)
    importer_location = str(
        edge.get("importer_location") or edge.get("src_id") or f"{importer_file}:module-level"
    )
    imported_from_module = str(
        edge.get("imported_from_module")
        or edge.get("from_module")
        or edge.get("module")
        or edge.get("src_module")
        or ""
    )

    details = edge.get("details")
    projection_type = _coerce_projection_type(edge.get("projection_type"))
    return RawImportRecord(
        importer_file=importer_file,
        importer_location=importer_location,
        imported_name=imported_name,
        imported_from_module=imported_from_module,
        line_no=_coerce_int(edge.get("line_no") or edge.get("line") or edge.get("line_start")),
        signal_type=str(edge.get("signal_type", "import_edge")),
        transformation_hint=(str(edge["transformation"]) if edge.get("transformation") else None)
        or (str(edge["projection_type"]) if edge.get("projection_type") else None),
        confidence=_coerce_confidence(edge.get("confidence"), default=1.0),
        details=details if isinstance(details, dict) else {},
        projection_type=projection_type,
    )


def _scan_file_imports_with_regex(file_path: Path, source: str) -> list[RawImportRecord]:
    """Fallback import scan for migration/test-double scenarios."""
    records: list[RawImportRecord] = []
    file_str = str(file_path)

    line_starts: list[int] = [0]
    for i, ch in enumerate(source):
        if ch == "\n":
            line_starts.append(i + 1)

    def _offset_to_lineno(offset: int) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if line_starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    for m in _FROM_IMPORT_RE.finditer(source):
        module = m.group(1)
        names_str = m.group(2).strip().rstrip("\\")
        lineno = _offset_to_lineno(m.start())
        for part in names_str.split(","):
            part = part.strip()
            if not part or part.startswith("#") or part == "(":
                continue
            part = part.split("#")[0].strip().rstrip(")")
            if not part:
                continue
            tokens = part.split()
            name = tokens[2] if len(tokens) >= 3 and tokens[1] == "as" else tokens[0]
            records.append(
                RawImportRecord(
                    importer_file=file_str,
                    importer_location=f"{file_str}:module-level",
                    imported_name=name,
                    imported_from_module=module,
                    line_no=lineno,
                    details={"fallback": "regex"},
                )
            )

    for m in _IMPORT_RE.finditer(source):
        names_str = m.group(1).strip()
        lineno = _offset_to_lineno(m.start())
        for part in names_str.split(","):
            part = part.strip()
            if not part or part.startswith("#"):
                continue
            part = part.split("#")[0].strip()
            if not part:
                continue
            tokens = part.split()
            name = tokens[2] if len(tokens) >= 3 and tokens[1] == "as" else tokens[0]
            records.append(
                RawImportRecord(
                    importer_file=file_str,
                    importer_location=f"{file_str}:module-level",
                    imported_name=name,
                    imported_from_module=tokens[0],
                    line_no=lineno,
                    details={"fallback": "regex"},
                )
            )

    return records


def _coerce_int(value: Any) -> int:
    """Best-effort integer parsing."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_confidence(value: Any, *, default: float) -> float:
    """Best-effort confidence parsing with [0, 1] clamp."""
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


@dataclass
class AtomDefinition:
    """A registered atom (pin-function) for lineage tracking.

    Attributes:
        atom_id: Unique atom identifier (e.g., "validate_payment").
        function_name: Python function name.
        file_path: File where atom is defined.
        module_path: Python module path.
        signature_hash: Hash of function signature for drift detection.
    """

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
            atom_id=data["atom_id"],
            function_name=data["function_name"],
            file_path=data["file_path"],
            module_path=data["module_path"],
            signature_hash=data["signature_hash"],
        )


class LineageBuilder:
    """Builds ProjectionLineageTable from declared edge evidence and atoms."""

    def __init__(
        self,
        import_records: list[RawImportRecord],
        atoms: list[AtomDefinition],
    ) -> None:
        self.import_records = import_records
        self.atoms = atoms
        self._atoms_by_function: dict[str, AtomDefinition] = {a.function_name: a for a in atoms}

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage table by matching pre-produced edge records to atoms.

        Returns:
            Populated ProjectionLineageTable.
        """
        table = ProjectionLineageTable()
        for record in self.import_records:
            atom = self._atoms_by_function.get(record.imported_name)
            if atom is None:
                continue
            if record.projection_type is None:
                # Lineage builder consumes declared projection types rather
                # than inferring semantic classes from import topology.
                continue

            table.add_edge(
                from_unit=atom.atom_id,
                to_unit=record.importer_location,
                transformation=record.projection_type,
                confidence=_coerce_confidence(record.confidence, default=1.0),
                details={"import_line": record.line_no, **record.details},
            )

        return table


def import_records_from_pin_registry(pin_registry: PinFunctionRegistry) -> list[RawImportRecord]:
    """Project PinFunctionRegistry edges into lineage-builder records."""
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
            )
        )
    return records


def compute_signature_hash(file_path: str, function_name: str) -> str | None:
    """Compute a hash of a function's signature from source code.

    Uses analyze_source to extract function info and builds a hash
    from the function name, args, and return annotation.

    Args:
        file_path: Path to the source file containing the function.
        function_name: Name of the function to hash.

    Returns:
        MD5 hex digest of the signature, or None if function not found.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        source = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    analysis = analyze_source(source, file_path)

    for func in analysis.functions:
        if func.name == function_name:
            sig_parts = _extract_signature_parts_from_info(func)
            sig_str = "|".join(sig_parts)
            return hashlib.md5(sig_str.encode()).hexdigest()  # noqa: S324

    return None


def _extract_signature_parts_from_info(func: object) -> list[str]:
    """Extract signature components from a RawFunctionInfo.

    Builds a list of signature components from the language-agnostic
    function info returned by analyze_source.

    Args:
        func: RawFunctionInfo instance with name, args, return_annotation.

    Returns:
        List of signature component strings.
    """
    parts: list[str] = [func.name]  # type: ignore[union-attr]

    for arg_str in func.args:  # type: ignore[union-attr]
        # args come as strings like "amount", "*args", "**kwargs"
        if arg_str.startswith("**"):
            parts.append(f"kwarg:{arg_str[2:]}")
        elif arg_str.startswith("*"):
            parts.append(f"vararg:{arg_str[1:]}")
        else:
            parts.append(f"arg:{arg_str}")

    if func.return_annotation:  # type: ignore[union-attr]
        parts.append(f"return:{func.return_annotation}")  # type: ignore[union-attr]

    return parts


__all__ = [
    "AtomDefinition",
    "LineageBuilder",
    "RawImportRecord",
    "compute_signature_hash",
    "import_records_from_pin_registry",
    "scan_imports_from_directory",
    "scan_imports_from_files",
]
