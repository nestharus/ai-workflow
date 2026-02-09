"""Lineage builder: bridges import records to lineage table.

Infers ProjectionLineageEdge entries from import relationships
and classifies transformation types based on architectural patterns.
"""

from __future__ import annotations

import fnmatch
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import analyze_source
from spec_manager.projection.lineage.table import ProjectionLineageTable
from spec_manager.schemas.pin_functions import ProjectionType

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

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "importer_file": self.importer_file,
            "importer_location": self.importer_location,
            "imported_name": self.imported_name,
            "imported_from_module": self.imported_from_module,
            "line_no": self.line_no,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RawImportRecord:
        """Deserialize from dictionary."""
        return cls(
            importer_file=data["importer_file"],
            importer_location=data["importer_location"],
            imported_name=data["imported_name"],
            imported_from_module=data["imported_from_module"],
            line_no=data.get("line_no", 0),
        )


def scan_imports_from_directory(
    root_dir: Path,
    exclude_patterns: list[str] | None = None,
) -> list[RawImportRecord]:
    """Scan all Python files in a directory for import statements.

    Uses regex patterns to extract import relationships without
    requiring language-specific AST parsing.

    Args:
        root_dir: Root directory to scan.
        exclude_patterns: Glob patterns to exclude (e.g., ["__pycache__"]).

    Returns:
        List of RawImportRecord entries found across all files.
    """
    if exclude_patterns is None:
        exclude_patterns = ["__pycache__"]

    records: list[RawImportRecord] = []
    for py_file in root_dir.rglob("*.py"):
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
    records: list[RawImportRecord] = []
    for file_path in file_paths:
        if file_path.suffix == ".py" and file_path.exists():
            records.extend(_scan_file_imports(file_path))
    return records


def _scan_file_imports(file_path: Path) -> list[RawImportRecord]:
    """Scan a single source file for import statements.

    Uses regex patterns to extract import relationships.

    Args:
        file_path: Path to source file.

    Returns:
        List of RawImportRecord entries found in the file.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    records: list[RawImportRecord] = []
    file_str = str(file_path)

    # Build a line-number lookup: map character offset -> line number
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
                )
            )

    return records


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


# Patterns that suggest event handler architecture
_EVENT_HANDLER_BASES = {"EventHandler", "Handler", "MessageHandler", "Consumer"}
_EVENT_HANDLER_DECORATORS = {"on_event", "subscribe", "handles", "event_handler"}

# Patterns that suggest middleware architecture
_MIDDLEWARE_BASES = {"Middleware", "BaseMiddleware"}
_MIDDLEWARE_DECORATORS = {"middleware", "use_middleware"}

# Patterns that suggest retry/resilience wrappers
_RETRY_DECORATORS = {"retry", "retryable", "circuit_breaker", "resilient", "backoff"}


class LineageBuilder:
    """Builds ProjectionLineageTable from import records and atom definitions.

    Analyzes import relationships to determine how atoms are projected
    into architectural locations, classifying transformations based on
    patterns found in the importing code.
    """

    def __init__(
        self,
        import_records: list[RawImportRecord],
        atoms: list[AtomDefinition],
    ) -> None:
        self.import_records = import_records
        self.atoms = atoms
        self._atoms_by_function: dict[str, AtomDefinition] = {a.function_name: a for a in atoms}
        self._atoms_by_module: dict[str, list[AtomDefinition]] = {}
        for atom in atoms:
            self._atoms_by_module.setdefault(atom.module_path, []).append(atom)
        # Cache for handler pattern detection per file
        self._handler_pattern_cache: dict[str, str | None] = {}

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage table by matching imports against known atoms.

        For each import record, checks if the imported name matches a
        known atom function. If so, classifies the transformation type
        and creates a lineage edge.

        Returns:
            Populated ProjectionLineageTable.
        """
        table = ProjectionLineageTable()

        # Track which atoms appear per importer file to detect smear
        atoms_per_file: dict[str, list[tuple[RawImportRecord, AtomDefinition]]] = {}

        for record in self.import_records:
            atom = self._atoms_by_function.get(record.imported_name)
            if atom is None:
                continue
            atoms_per_file.setdefault(record.importer_file, []).append((record, atom))

        for _file_path, atom_imports in atoms_per_file.items():
            if len(atom_imports) > 1:
                # Multiple atoms imported in the same file: SMEAR
                for record, atom in atom_imports:
                    table.add_edge(
                        from_unit=atom.atom_id,
                        to_unit=record.importer_location,
                        transformation=ProjectionType.SMEAR,
                        confidence=0.8,
                        details={
                            "import_line": record.line_no,
                            "co_imported_atoms": [a.atom_id for _, a in atom_imports if a != atom],
                        },
                    )
            else:
                record, atom = atom_imports[0]
                transformation, confidence = self._classify_transformation(
                    record, atom, record.importer_file
                )
                table.add_edge(
                    from_unit=atom.atom_id,
                    to_unit=record.importer_location,
                    transformation=transformation,
                    confidence=confidence,
                    details={"import_line": record.line_no},
                )

        return table

    def _classify_transformation(
        self,
        record: RawImportRecord,
        atom: AtomDefinition,
        importer_context: str,
    ) -> tuple[ProjectionType, float]:
        """Classify the transformation type and assign confidence.

        Classification rules:
        - Direct import + direct call: PASS_THROUGH, confidence=1.0
        - Import in event handler class: EVENT_BRIDGE, confidence=0.9
        - Import in middleware class: MIDDLEWARE_WRAP, confidence=0.9
        - Import in retry/resilience wrapper: RETRY_DECORATE, confidence=0.9
        - Default (no pattern match): PASS_THROUGH, confidence=1.0

        Args:
            record: The import record.
            atom: The matched atom definition.
            importer_context: File path of the importing module.

        Returns:
            Tuple of (transformation_type, confidence).
        """
        pattern = self._detect_handler_pattern(importer_context)

        pattern_mapping = {
            "event_handler": (ProjectionType.EVENT_BRIDGE, 0.9),
            "middleware": (ProjectionType.MIDDLEWARE_WRAP, 0.9),
            "retry": (ProjectionType.RETRY_DECORATE, 0.9),
        }
        if pattern in pattern_mapping:
            return pattern_mapping[pattern]

        # Default: direct import = pass_through
        return ProjectionType.PASS_THROUGH, 1.0

    def _detect_handler_pattern(self, file_path: str) -> str | None:
        """Detect if a file follows event handler, middleware, or retry patterns.

        Uses regex for class base detection and analyze_source for
        decorator pattern detection.

        Args:
            file_path: Path to the source file to analyze.

        Returns:
            Pattern name ("event_handler", "middleware", "retry") or None.
        """
        if file_path in self._handler_pattern_cache:
            return self._handler_pattern_cache[file_path]

        result = self._analyze_handler_pattern(file_path)
        self._handler_pattern_cache[file_path] = result
        return result

    def _analyze_handler_pattern(self, file_path: str) -> str | None:
        """Detect handler patterns using analyze_source and simple line parsing.

        Uses analyze_source for function/decorator detection and simple
        line parsing for class base class detection (class bases are not
        part of RawFunctionInfo).

        Args:
            file_path: Path to the source file.

        Returns:
            Pattern name ("event_handler", "middleware", "retry") or None.
        """
        path = Path(file_path)
        if not path.exists():
            return None

        try:
            source = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

        # --- Check class base classes via line parsing ---
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("class ") and "(" in stripped and stripped.endswith(":"):
                # Extract base classes from "class Foo(Base1, Base2):"
                paren_start = stripped.index("(")
                paren_end = stripped.rindex(")")
                bases_str = stripped[paren_start + 1 : paren_end]
                bases = [b.strip().rsplit(".", 1)[-1] for b in bases_str.split(",")]
                for base_name in bases:
                    if base_name in _EVENT_HANDLER_BASES:
                        return "event_handler"
                    if base_name in _MIDDLEWARE_BASES:
                        return "middleware"

        # --- Check decorators via analyze_source ---
        analysis = analyze_source(source, file_path)
        for func in analysis.functions:
            for dec in func.decorators:
                # Extract the simple name from dotted or call decorators
                dec_name = dec.rsplit(".", 1)[-1].split("(")[0]
                if dec_name in _EVENT_HANDLER_DECORATORS:
                    return "event_handler"
                if dec_name in _MIDDLEWARE_DECORATORS:
                    return "middleware"
                if dec_name in _RETRY_DECORATORS:
                    return "retry"

        return None


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
    "scan_imports_from_directory",
    "scan_imports_from_files",
]
