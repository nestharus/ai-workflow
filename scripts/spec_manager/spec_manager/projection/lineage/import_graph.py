"""Import graph builder using Python AST static analysis.

Builds a graph of Python import relationships from source files,
enabling queries like "who imports function X?" for pin-function tracing.
"""

from __future__ import annotations

import ast
import fnmatch
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ImportEdge:
    """A raw Python import relationship from AST analysis.

    Not to be confused with:
    - ``schemas.pin_functions.ImportEdge``: a higher-level pin-function-to-
      architecture mapping edge (PFUNC -> arch location with projection type).
    - ``projection.lineage.edges.ProjectionLineageEdge``: a lineage
      transformation edge tracking how atoms map to architecture over time.

    Attributes:
        importer_file: File that contains the import statement.
        importer_location: file:class.method or file:module-level.
        imported_name: The name being imported (function/class).
        imported_from_module: The module being imported from.
        imported_from_file: Resolved file path (if resolvable).
        line_no: Line number of the import statement.
        is_direct: Direct import vs re-export.
    """

    importer_file: str
    importer_location: str
    imported_name: str
    imported_from_module: str
    imported_from_file: str = ""
    line_no: int = 0
    is_direct: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "importer_file": self.importer_file,
            "importer_location": self.importer_location,
            "imported_name": self.imported_name,
            "imported_from_module": self.imported_from_module,
            "imported_from_file": self.imported_from_file,
            "line_no": self.line_no,
            "is_direct": self.is_direct,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImportEdge:
        """Deserialize from dictionary."""
        return cls(
            importer_file=data["importer_file"],
            importer_location=data["importer_location"],
            imported_name=data["imported_name"],
            imported_from_module=data["imported_from_module"],
            imported_from_file=data.get("imported_from_file", ""),
            line_no=data.get("line_no", 0),
            is_direct=data.get("is_direct", True),
        )


class ImportGraph:
    """Graph of Python import relationships.

    Built from static analysis of ast.Import and ast.ImportFrom nodes.
    Enables "who imports function X?" queries for pin-function tracing.
    """

    def __init__(self) -> None:
        self.edges: list[ImportEdge] = []
        self._by_imported_name: dict[str, list[ImportEdge]] = defaultdict(list)
        self._by_importer_file: dict[str, list[ImportEdge]] = defaultdict(list)

    # --- Build ---

    @classmethod
    def build_from_directory(
        cls,
        root_dir: Path,
        exclude_patterns: list[str] | None = None,
    ) -> ImportGraph:
        """Build import graph from all Python files in a directory.

        Args:
            root_dir: Root directory to scan.
            exclude_patterns: Glob patterns to exclude (e.g., ["__pycache__"]).

        Returns:
            Populated ImportGraph.
        """
        if exclude_patterns is None:
            exclude_patterns = ["__pycache__"]

        graph = cls()
        for py_file in root_dir.rglob("*.py"):
            # Check if any parent directory matches exclude patterns
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

            edges = graph._analyze_file(py_file)
            for edge in edges:
                graph._add_edge(edge)

        return graph

    @classmethod
    def build_from_files(
        cls,
        file_paths: list[Path],
    ) -> ImportGraph:
        """Build import graph from a specific list of files.

        Args:
            file_paths: List of Python file paths to analyze.

        Returns:
            Populated ImportGraph.
        """
        graph = cls()
        for file_path in file_paths:
            if file_path.suffix == ".py" and file_path.exists():
                edges = graph._analyze_file(file_path)
                for edge in edges:
                    graph._add_edge(edge)
        return graph

    def _add_edge(self, edge: ImportEdge) -> None:
        """Add an edge to the graph and update indexes."""
        self.edges.append(edge)
        self._by_imported_name[edge.imported_name].append(edge)
        self._by_importer_file[edge.importer_file].append(edge)

    def _analyze_file(self, file_path: Path) -> list[ImportEdge]:
        """Analyze a Python file for import statements.

        Uses ast.parse to extract Import and ImportFrom nodes.

        Args:
            file_path: Path to Python file.

        Returns:
            List of ImportEdge entries found in the file.
        """
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError):
            return []

        edges: list[ImportEdge] = []
        file_str = str(file_path)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    edges.append(
                        ImportEdge(
                            importer_file=file_str,
                            importer_location=f"{file_str}:module-level",
                            imported_name=name,
                            imported_from_module=module,
                            imported_from_file="",
                            line_no=node.lineno,
                        )
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    edges.append(
                        ImportEdge(
                            importer_file=file_str,
                            importer_location=f"{file_str}:module-level",
                            imported_name=name,
                            imported_from_module=alias.name,
                            imported_from_file="",
                            line_no=node.lineno,
                        )
                    )

        return edges

    # --- Query ---

    def importers_of(self, function_name: str) -> list[ImportEdge]:
        """Find all files that import a given function/name.

        Args:
            function_name: The imported name to search for.

        Returns:
            List of ImportEdge entries where the name is imported.
        """
        return list(self._by_imported_name.get(function_name, []))

    def imports_in(self, file_path: str) -> list[ImportEdge]:
        """Find all imports in a given file.

        Args:
            file_path: Path to the file.

        Returns:
            List of ImportEdge entries from that file.
        """
        return list(self._by_importer_file.get(file_path, []))

    def resolve_module_to_file(
        self,
        module_path: str,
        search_roots: list[Path],
    ) -> str | None:
        """Resolve a dotted module path to a filesystem path.

        Tries to find the module as either a package (__init__.py)
        or a module (.py file) under each search root.

        Args:
            module_path: Dotted module path (e.g., "spec_manager.core.provenance").
            search_roots: Directories to search in.

        Returns:
            Resolved file path string, or None if not found.
        """
        parts = module_path.split(".")
        for root in search_roots:
            # Try as a module file
            candidate = root / Path(*parts).with_suffix(".py")
            if candidate.exists():
                return str(candidate)
            # Try as a package
            candidate = root / Path(*parts) / "__init__.py"
            if candidate.exists():
                return str(candidate)
        return None

    # --- Serialization ---

    def to_dict(self) -> list[dict[str, Any]]:
        """Serialize to a list of edge dictionaries."""
        return [e.to_dict() for e in self.edges]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> ImportGraph:
        """Deserialize from a list of edge dictionaries.

        Args:
            data: List of serialized edge dictionaries.

        Returns:
            Reconstructed ImportGraph with indexes.
        """
        graph = cls()
        for edge_data in data:
            edge = ImportEdge.from_dict(edge_data)
            graph._add_edge(edge)
        return graph


__all__ = [
    "ImportEdge",
    "ImportGraph",
]
