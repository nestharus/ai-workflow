"""Import graph builder for pin-function tracing.

Builds the import graph that maps which architectural files import which
pin-functions. Scans Python source files for ``ast.Import`` and
``ast.ImportFrom`` nodes, matches them against registered pin-function
names, and classifies each usage site's projection type.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import ImportEdge, PinFunction, ProjectionType


@dataclass
class UsageSite:
    """A location where an imported pin-function is called."""

    line: int  # Line number of the call
    enclosing_function: str  # Function/method containing the call
    enclosing_class: str | None = None  # Class containing the method (if any)
    call_pattern: str = "direct"  # "direct", "wrapped", "partial", "lambda"


@dataclass
class ImportReference:
    """A detected import of a pin-function in an architectural file."""

    pin_func_name: str  # Name of the imported function
    import_module: str  # Module it was imported from
    file_path: str  # File containing the import
    import_line: int  # Line number of import statement
    usage_sites: list[UsageSite] = field(default_factory=list)
    alias: str | None = None  # Import alias if renamed


@dataclass
class ImportGraphConfig:
    """Configuration for import graph construction."""

    algorithmic_roots: list[str] = field(
        default_factory=lambda: ["atoms", "shapes"]
    )
    architectural_roots: list[str] = field(
        default_factory=lambda: ["services", "handlers"]
    )
    follow_reexports: bool = True


class ImportGraphBuilder:
    """Builds the import graph between algorithmic and architectural layers."""

    def __init__(self, config: ImportGraphConfig | None = None) -> None:
        self.config = config or ImportGraphConfig()
        self._edge_counter = 0

    def build_graph(
        self,
        pin_functions: list[PinFunction],
        arch_directory: Path,
    ) -> list[ImportEdge]:
        """Build the full import graph by scanning architectural files.

        Args:
            pin_functions: List of registered pin-functions.
            arch_directory: Root directory of architectural code to scan.

        Returns:
            List of ImportEdge objects representing the import graph.
        """
        from spec_manager.schemas.pin_functions import ImportEdge as ImportEdgeModel

        # Build lookup of pin-function names to pin-function objects
        pf_by_name: dict[str, PinFunction] = {}
        for pf in pin_functions:
            pf_by_name[pf.function_name] = pf

        edges: list[ImportEdge] = []

        # Scan all Python files in the architectural directory
        for py_file in sorted(arch_directory.rglob("*.py")):
            if not py_file.is_file():
                continue

            references = self.scan_file_imports(py_file)

            for ref in references:
                # Match against registered pin-functions
                pf = pf_by_name.get(ref.pin_func_name)
                if pf is None:
                    continue

                # Create an edge for each usage site
                if ref.usage_sites:
                    for usage in ref.usage_sites:
                        proj_type = self.classify_projection_type(ref, usage)
                        self._edge_counter += 1
                        edge = ImportEdgeModel(
                            edge_id=f"IMEDGE-{self._edge_counter:04d}",
                            pin_func_id=pf.pin_func_id,
                            arch_location=self._build_arch_location(
                                str(py_file), usage
                            ),
                            arch_file_path=str(py_file),
                            arch_line=usage.line,
                            projection_type=proj_type,
                            confidence=1.0,
                            is_direct_import=True,
                        )
                        edges.append(edge)
                else:
                    # Import exists but no call sites found
                    self._edge_counter += 1
                    from spec_manager.schemas.pin_functions import (
                        ProjectionType as PT,
                    )

                    edge = ImportEdgeModel(
                        edge_id=f"IMEDGE-{self._edge_counter:04d}",
                        pin_func_id=pf.pin_func_id,
                        arch_location=f"{py_file}:<module>",
                        arch_file_path=str(py_file),
                        arch_line=ref.import_line,
                        projection_type=PT.PASS_THROUGH,
                        confidence=0.5,
                        is_direct_import=True,
                    )
                    edges.append(edge)

        # Detect smeared functions and update projection types
        self._apply_smear_detection(edges)

        return edges

    def scan_file_imports(self, file_path: Path) -> list[ImportReference]:
        """Scan a single file for import statements and their usage sites.

        Args:
            file_path: Path to the Python source file.

        Returns:
            List of ImportReference objects detected in the file.
        """
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            return []

        references: list[ImportReference] = []

        # Collect all imports from algorithmic roots
        imported_names: dict[str, ImportReference] = {}

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                # Check if module is from algorithmic roots
                if self._is_algorithmic_module(node.module):
                    for alias_node in node.names:
                        local_name = alias_node.asname or alias_node.name
                        ref = ImportReference(
                            pin_func_name=alias_node.name,
                            import_module=node.module,
                            file_path=str(file_path),
                            import_line=node.lineno,
                            alias=alias_node.asname,
                        )
                        imported_names[local_name] = ref
                        references.append(ref)

            elif isinstance(node, ast.Import):
                for alias_node in node.names:
                    if self._is_algorithmic_module(alias_node.name):
                        local_name = alias_node.asname or alias_node.name
                        ref = ImportReference(
                            pin_func_name=alias_node.name,
                            import_module=alias_node.name,
                            file_path=str(file_path),
                            import_line=node.lineno,
                            alias=alias_node.asname,
                        )
                        imported_names[local_name] = ref
                        references.append(ref)

        # Find usage sites for imported names
        if imported_names:
            self._find_usage_sites(tree, imported_names, source)

        return references

    def classify_projection_type(
        self,
        reference: ImportReference,
        usage: UsageSite,
    ) -> ProjectionType:
        """Classify how an architectural location uses a pin-function.

        Args:
            reference: The import reference.
            usage: The usage site within the architectural file.

        Returns:
            The projection type classification.
        """
        from spec_manager.schemas.pin_functions import ProjectionType as PT

        if usage.call_pattern == "wrapped":
            return PT.MIDDLEWARE_WRAP
        if usage.call_pattern == "partial":
            return PT.MIDDLEWARE_WRAP
        if usage.call_pattern == "lambda":
            return PT.MIDDLEWARE_WRAP
        # Default: direct call
        return PT.PASS_THROUGH

    def detect_smeared_functions(
        self,
        references: list[ImportReference],
    ) -> list[tuple[str, list[str]]]:
        """Detect smeared functions: enclosing functions that call 2+ pin-functions.

        Args:
            references: All import references from a single file.

        Returns:
            List of (enclosing_function, [pin_func_names]) tuples for smeared functions.
        """
        # Group usage sites by enclosing function
        by_enclosing: dict[str, list[str]] = {}
        for ref in references:
            for usage in ref.usage_sites:
                key = usage.enclosing_function
                if usage.enclosing_class:
                    key = f"{usage.enclosing_class}.{usage.enclosing_function}"
                if key not in by_enclosing:
                    by_enclosing[key] = []
                if ref.pin_func_name not in by_enclosing[key]:
                    by_enclosing[key].append(ref.pin_func_name)

        # Return only functions that call 2+ pin-functions
        return [
            (func, names)
            for func, names in by_enclosing.items()
            if len(names) >= 2
        ]

    # --- Private helpers ---

    def _is_algorithmic_module(self, module_name: str) -> bool:
        """Check if a module name belongs to an algorithmic root."""
        module_parts = module_name.split(".")
        for root in self.config.algorithmic_roots:
            if root in module_parts:
                return True
        return False

    def _find_usage_sites(
        self,
        tree: ast.Module,
        imported_names: dict[str, ImportReference],
        source: str,
    ) -> None:
        """Find all call sites for imported pin-functions in the AST.

        Mutates the ImportReference objects to add usage sites.

        Args:
            tree: The parsed AST module.
            imported_names: Map of local names to their ImportReference.
            source: The full source code.
        """
        # Walk the tree and track enclosing function/class context
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                enclosing_class = self._find_enclosing_class(tree, node)
                is_decorated = len(node.decorator_list) > 0

                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        call_name = self._get_call_name(child)
                        if call_name and call_name in imported_names:
                            # Determine call pattern
                            call_pattern = "direct"
                            if is_decorated:
                                call_pattern = "wrapped"

                            usage = UsageSite(
                                line=child.lineno,
                                enclosing_function=node.name,
                                enclosing_class=enclosing_class,
                                call_pattern=call_pattern,
                            )
                            imported_names[call_name].usage_sites.append(usage)

    def _find_enclosing_class(
        self, tree: ast.Module, target_func: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> str | None:
        """Find the class that directly contains the target function."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for child in node.body:
                    if child is target_func:
                        return node.name
        return None

    def _get_call_name(self, call_node: ast.Call) -> str | None:
        """Get the local name of a called function."""
        func = call_node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            # For module.func() style calls
            if isinstance(func.value, ast.Name):
                return func.value.id
        return None

    def _build_arch_location(self, file_path: str, usage: UsageSite) -> str:
        """Build an architectural location string."""
        if usage.enclosing_class:
            return f"{file_path}:{usage.enclosing_class}.{usage.enclosing_function}"
        return f"{file_path}:{usage.enclosing_function}"

    def _apply_smear_detection(self, edges: list[ImportEdge]) -> None:
        """Detect and mark smeared edges: multiple pin-functions used in same location.

        Mutates edges in-place to set projection_type to SMEAR where applicable.
        """
        # Group edges by arch_location
        by_location: dict[str, list[ImportEdge]] = {}
        for edge in edges:
            if edge.arch_location not in by_location:
                by_location[edge.arch_location] = []
            by_location[edge.arch_location].append(edge)

        # Mark locations with 2+ pin-functions as SMEAR
        from spec_manager.schemas.pin_functions import ProjectionType as PT

        for location, loc_edges in by_location.items():
            unique_pins = {e.pin_func_id for e in loc_edges}
            if len(unique_pins) >= 2:
                for edge in loc_edges:
                    # Pydantic models are mutable by default; update in-place
                    edge.projection_type = PT.SMEAR


__all__ = [
    "ImportGraphBuilder",
    "ImportGraphConfig",
    "ImportReference",
    "UsageSite",
]
