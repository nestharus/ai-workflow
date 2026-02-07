"""Lineage builder: bridges import graph to lineage table.

Infers ProjectionLineageEdge entries from import relationships
and classifies transformation types based on architectural patterns.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.schemas.pin_functions import ProjectionType
from spec_manager.projection.lineage.import_graph import ImportEdge, ImportGraph
from spec_manager.projection.lineage.table import ProjectionLineageTable


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
    """Builds ProjectionLineageTable from ImportGraph and atom definitions.

    Analyzes import relationships to determine how atoms are projected
    into architectural locations, classifying transformations based on
    patterns found in the importing code.
    """

    def __init__(
        self,
        import_graph: ImportGraph,
        atoms: list[AtomDefinition],
    ) -> None:
        self.import_graph = import_graph
        self.atoms = atoms
        self._atoms_by_function: dict[str, AtomDefinition] = {
            a.function_name: a for a in atoms
        }
        self._atoms_by_module: dict[str, list[AtomDefinition]] = {}
        for atom in atoms:
            self._atoms_by_module.setdefault(atom.module_path, []).append(atom)
        # Cache for handler pattern detection per file
        self._handler_pattern_cache: dict[str, str | None] = {}

    def build_lineage(self) -> ProjectionLineageTable:
        """Build lineage table by matching imports against known atoms.

        For each import edge in the import graph, checks if the imported
        name matches a known atom function. If so, classifies the
        transformation type and creates a lineage edge.

        Returns:
            Populated ProjectionLineageTable.
        """
        table = ProjectionLineageTable()

        # Track which atoms appear per importer file to detect smear
        atoms_per_file: dict[str, list[tuple[ImportEdge, AtomDefinition]]] = {}

        for import_edge in self.import_graph.edges:
            atom = self._atoms_by_function.get(import_edge.imported_name)
            if atom is None:
                continue
            atoms_per_file.setdefault(import_edge.importer_file, []).append(
                (import_edge, atom)
            )

        for file_path, atom_imports in atoms_per_file.items():
            if len(atom_imports) > 1:
                # Multiple atoms imported in the same file: SMEAR
                for import_edge, atom in atom_imports:
                    table.add_edge(
                        from_unit=atom.atom_id,
                        to_unit=import_edge.importer_location,
                        transformation=ProjectionType.SMEAR,
                        confidence=0.8,
                        details={
                            "import_line": import_edge.line_no,
                            "co_imported_atoms": [
                                a.atom_id for _, a in atom_imports if a != atom
                            ],
                        },
                    )
            else:
                import_edge, atom = atom_imports[0]
                transformation, confidence = self._classify_transformation(
                    import_edge, atom, import_edge.importer_file
                )
                table.add_edge(
                    from_unit=atom.atom_id,
                    to_unit=import_edge.importer_location,
                    transformation=transformation,
                    confidence=confidence,
                    details={"import_line": import_edge.line_no},
                )

        return table

    def _classify_transformation(
        self,
        import_edge: ImportEdge,
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
            import_edge: The import relationship.
            atom: The matched atom definition.
            importer_context: File path of the importing module.

        Returns:
            Tuple of (transformation_type, confidence).
        """
        pattern = self._detect_handler_pattern(importer_context)

        if pattern == "event_handler":
            return ProjectionType.EVENT_BRIDGE, 0.9
        elif pattern == "middleware":
            return ProjectionType.MIDDLEWARE_WRAP, 0.9
        elif pattern == "retry":
            return ProjectionType.RETRY_DECORATE, 0.9

        # Default: direct import = pass_through
        return ProjectionType.PASS_THROUGH, 1.0

    def _detect_handler_pattern(self, file_path: str) -> str | None:
        """Detect if a file follows event handler, middleware, or retry patterns.

        Uses AST analysis to check class bases and decorator patterns.

        Args:
            file_path: Path to the Python file to analyze.

        Returns:
            Pattern name ("event_handler", "middleware", "retry") or None.
        """
        if file_path in self._handler_pattern_cache:
            return self._handler_pattern_cache[file_path]

        result = self._analyze_handler_pattern(file_path)
        self._handler_pattern_cache[file_path] = result
        return result

    def _analyze_handler_pattern(self, file_path: str) -> str | None:
        """Perform AST analysis of a file to detect handler patterns.

        Args:
            file_path: Path to the Python file.

        Returns:
            Pattern name or None.
        """
        path = Path(file_path)
        if not path.exists() or not path.suffix == ".py":
            return None

        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, UnicodeDecodeError):
            return None

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check base classes
                for base in node.bases:
                    base_name = _extract_name(base)
                    if base_name in _EVENT_HANDLER_BASES:
                        return "event_handler"
                    if base_name in _MIDDLEWARE_BASES:
                        return "middleware"

                # Check class decorators
                for decorator in node.decorator_list:
                    dec_name = _extract_name(decorator)
                    if dec_name in _EVENT_HANDLER_DECORATORS:
                        return "event_handler"
                    if dec_name in _MIDDLEWARE_DECORATORS:
                        return "middleware"
                    if dec_name in _RETRY_DECORATORS:
                        return "retry"

            elif isinstance(node, ast.FunctionDef):
                # Check function decorators
                for decorator in node.decorator_list:
                    dec_name = _extract_name(decorator)
                    if dec_name in _RETRY_DECORATORS:
                        return "retry"
                    if dec_name in _EVENT_HANDLER_DECORATORS:
                        return "event_handler"
                    if dec_name in _MIDDLEWARE_DECORATORS:
                        return "middleware"

        return None


def compute_signature_hash(file_path: str, function_name: str) -> str | None:
    """Compute a hash of a function's signature from source code.

    Uses AST analysis to extract the function signature (parameter names
    and annotations) and returns an MD5 hash for comparison.

    Args:
        file_path: Path to the Python file containing the function.
        function_name: Name of the function to hash.

    Returns:
        MD5 hex digest of the signature, or None if function not found.
    """
    path = Path(file_path)
    if not path.exists():
        return None

    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, UnicodeDecodeError):
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                sig_parts = _extract_signature_parts(node)
                sig_str = "|".join(sig_parts)
                return hashlib.md5(sig_str.encode()).hexdigest()

    return None


def _extract_signature_parts(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Extract signature components from a function AST node.

    Args:
        func_node: AST function definition node.

    Returns:
        List of signature component strings.
    """
    parts: list[str] = [func_node.name]

    # Parameters
    args = func_node.args
    for arg in args.args:
        annotation = ast.dump(arg.annotation) if arg.annotation else ""
        parts.append(f"arg:{arg.arg}:{annotation}")

    for arg in args.kwonlyargs:
        annotation = ast.dump(arg.annotation) if arg.annotation else ""
        parts.append(f"kwonly:{arg.arg}:{annotation}")

    if args.vararg:
        parts.append(f"vararg:{args.vararg.arg}")
    if args.kwarg:
        parts.append(f"kwarg:{args.kwarg.arg}")

    # Return annotation
    if func_node.returns:
        parts.append(f"return:{ast.dump(func_node.returns)}")

    return parts


def _extract_name(node: ast.expr) -> str | None:
    """Extract a simple name from an AST expression node.

    Handles Name, Attribute, and Call nodes.

    Args:
        node: AST expression node.

    Returns:
        Extracted name string or None.
    """
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return node.attr
    elif isinstance(node, ast.Call):
        return _extract_name(node.func)
    return None


__all__ = [
    "AtomDefinition",
    "LineageBuilder",
    "compute_signature_hash",
]
