"""Codebase collapse to Layer 1 (design doc Section 6).

Ingests an existing codebase that has no layer separation and collapses
it to Layer 1 (algorithmic representation) by extracting algorithmic
intent from the source files.

The collapse engine:
1. Parses all Python files for function definitions
2. Classifies each function: algorithm, store, shape, or architecture
3. Extracts algorithms/stores/shapes into atoms/
4. Records architectural remnants for future projection
5. Builds initial atom registry

Delegates function shape detection, store reference detection, signature
extraction, and body hashing to the canonical
``analysis.ast_extractor.AtomFunctionExtractor``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.analysis.ast_extractor import (
    AtomFunctionExtractor,
    ExtractionConfig,
)

from .layout import BranchLayout
from .types import AtomDescriptor, AtomKind

# Keywords that suggest architectural/infrastructure patterns
# (unique to collapse context -- not in the canonical extractor)
_ARCH_INDICATORS = frozenset(
    {
        "route",
        "router",
        "middleware",
        "handler",
        "endpoint",
        "retry",
        "circuit_breaker",
        "timeout",
        "rate_limit",
        "decorator",
        "wrapper",
        "proxy",
        "adapter",
        "factory",
        "dispatch",
        "subscribe",
        "publish",
        "emit",
        "on_event",
        "service",
        "controller",
        "view",
        "api",
        "http",
        "request",
        "response",
        "status_code",
        "header",
        "async",
        "await",
        "asyncio",
        "coroutine",
        "logging",
        "logger",
        "log",
    }
)

# Keywords that suggest a function interacts with stores/persistence
_STORE_INDICATORS = frozenset(
    {
        "database",
        "db",
        "sql",
        "query",
        "cursor",
        "session",
        "redis",
        "cache",
        "queue",
        "file",
        "write",
        "read",
        "save",
        "load",
        "persist",
        "store",
        "fetch",
        "insert",
        "update",
        "delete",
        "commit",
        "rollback",
        "transaction",
        "open",
        "close",
        "connect",
        "connection",
    }
)


@dataclass
class CollapseResult:
    """Result of collapsing a codebase to Layer 1."""

    extracted_atoms: list[AtomDescriptor]
    extracted_stores: list[AtomDescriptor]
    extracted_shapes: list[AtomDescriptor]
    architectural_remnants: list[str]  # Code identified as purely architectural
    ambiguous_code: list[str]  # Code that could be either layer
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "extracted_atoms": [a.to_dict() for a in self.extracted_atoms],
            "extracted_stores": [a.to_dict() for a in self.extracted_stores],
            "extracted_shapes": [a.to_dict() for a in self.extracted_shapes],
            "architectural_remnants": self.architectural_remnants,
            "ambiguous_code": self.ambiguous_code,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollapseResult:
        """Deserialize from dictionary."""
        return cls(
            extracted_atoms=[AtomDescriptor.from_dict(a) for a in data["extracted_atoms"]],
            extracted_stores=[AtomDescriptor.from_dict(a) for a in data["extracted_stores"]],
            extracted_shapes=[AtomDescriptor.from_dict(a) for a in data["extracted_shapes"]],
            architectural_remnants=data["architectural_remnants"],
            ambiguous_code=data["ambiguous_code"],
            warnings=data["warnings"],
        )


class CollapseEngine:
    """Collapses an existing codebase to Layer 1 (design doc Section 6).

    When ingesting an existing codebase with no layer separation:
    1. Parse all Python files for function definitions
    2. Classify each function: algorithm, store, shape, or architecture
    3. Extract algorithms/stores/shapes into atoms/
    4. Record architectural remnants for future projection
    5. Build initial atom registry

    Delegates shape detection, store reference detection, and body hashing
    to ``AtomFunctionExtractor`` from ``analysis.ast_extractor``.
    """

    def __init__(self, layout: BranchLayout) -> None:
        self._layout = layout
        self._extractor = AtomFunctionExtractor(
            ExtractionConfig(
                require_docstring=False,
                max_function_lines=999,
            )
        )

    def collapse(self, source_dir: Path) -> CollapseResult:
        """Collapse an existing codebase to Layer 1.

        Args:
            source_dir: Root directory of the source codebase.

        Returns:
            CollapseResult with classified functions.
        """
        extracted_atoms: list[AtomDescriptor] = []
        extracted_stores: list[AtomDescriptor] = []
        extracted_shapes: list[AtomDescriptor] = []
        architectural_remnants: list[str] = []
        ambiguous_code: list[str] = []
        warnings: list[str] = []

        if not source_dir.exists():
            warnings.append(f"Source directory does not exist: {source_dir}")
            return CollapseResult(
                extracted_atoms=extracted_atoms,
                extracted_stores=extracted_stores,
                extracted_shapes=extracted_shapes,
                architectural_remnants=architectural_remnants,
                ambiguous_code=ambiguous_code,
                warnings=warnings,
            )

        py_files = sorted(source_dir.rglob("*.py"))
        if not py_files:
            warnings.append(f"No Python files found in: {source_dir}")

        for py_file in py_files:
            if py_file.name == "__init__.py":
                continue
            # Skip __pycache__ directories
            if "__pycache__" in str(py_file):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"Failed to read {py_file}: {exc}")
                continue

            try:
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError as exc:
                warnings.append(f"Syntax error in {py_file}: {exc}")
                continue

            rel_path = py_file.relative_to(source_dir)

            for node in ast.iter_child_nodes(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Also check for functions inside classes
                    if isinstance(node, ast.ClassDef):
                        for class_node in ast.iter_child_nodes(node):
                            if isinstance(class_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                kind = self._classify_function(class_node, py_file, source)
                                qualified_name = f"{node.name}.{class_node.name}"
                                if kind is None:
                                    architectural_remnants.append(f"{rel_path}:{qualified_name}")
                                else:
                                    descriptor = self._extract_atom(
                                        class_node,
                                        py_file,
                                        source,
                                        source_dir,
                                        kind,
                                        qualified_name=qualified_name,
                                    )
                                    if kind == AtomKind.ALGORITHM:
                                        extracted_atoms.append(descriptor)
                                    elif kind == AtomKind.STORE:
                                        extracted_stores.append(descriptor)
                                    elif kind == AtomKind.SHAPE:
                                        extracted_shapes.append(descriptor)
                    continue

                kind = self._classify_function(node, py_file, source)
                if kind is None:
                    architectural_remnants.append(f"{rel_path}:{node.name}")
                else:
                    descriptor = self._extract_atom(node, py_file, source, source_dir, kind)
                    if kind == AtomKind.ALGORITHM:
                        extracted_atoms.append(descriptor)
                    elif kind == AtomKind.STORE:
                        extracted_stores.append(descriptor)
                    elif kind == AtomKind.SHAPE:
                        extracted_shapes.append(descriptor)

        return CollapseResult(
            extracted_atoms=extracted_atoms,
            extracted_stores=extracted_stores,
            extracted_shapes=extracted_shapes,
            architectural_remnants=architectural_remnants,
            ambiguous_code=ambiguous_code,
            warnings=warnings,
        )

    def _classify_function(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        module_path: Path,
        source: str = "",
    ) -> AtomKind | None:
        """Classify a function as algorithm, store, shape, or architectural.

        Uses the canonical ``AtomFunctionExtractor.is_shape()`` for shape
        detection and ``detect_store_references()`` for store detection,
        combined with the branches-specific ``_ARCH_INDICATORS`` check.

        Args:
            func_node: The AST node for the function definition.
            module_path: Path to the module file.
            source: Full source code of the file.

        Returns:
            AtomKind if the function is an atom, None if architectural.
        """
        func_name = func_node.name.lower()
        body_source = self._get_node_source(func_node, source)
        body_lower = body_source.lower()

        # Skip private/dunder methods
        if (
            func_name.startswith("__")
            and func_name.endswith("__")
            and func_name not in ("__init__",)
        ):
            return None

        # Check for architectural patterns first (they take priority)
        arch_score = 0
        for indicator in _ARCH_INDICATORS:
            if indicator in func_name or indicator in body_lower:
                arch_score += 1

        # Check for store patterns
        store_score = 0
        for indicator in _STORE_INDICATORS:
            if indicator in func_name or indicator in body_lower:
                store_score += 1

        # Delegate shape detection to canonical extractor
        is_shape = self._extractor.is_shape(func_node, module_path)

        # Also check store references via canonical extractor
        store_refs = self._extractor.detect_store_references(func_node)
        if store_refs:
            store_score += len(store_refs)

        # Async functions are typically architectural
        if isinstance(func_node, ast.AsyncFunctionDef):
            if store_score > arch_score:
                return AtomKind.STORE
            if arch_score >= 2 or arch_score > 0:
                return None

        # Classification logic
        if arch_score >= 2 and arch_score > store_score:
            return None  # Architectural

        if store_score >= 2:
            return AtomKind.STORE

        # Functions with multi-step logic are algorithms even if pure
        body = self._strip_docstring(func_node.body)
        if len(body) >= 2:
            return AtomKind.ALGORITHM

        if is_shape:
            return AtomKind.SHAPE

        # Single-statement functions with some logic default to algorithm
        if len(body) >= 1:
            return AtomKind.ALGORITHM

        return AtomKind.SHAPE

    def _extract_atom(
        self,
        func_node: ast.FunctionDef | ast.AsyncFunctionDef,
        module_path: Path,
        source: str,
        source_dir: Path,
        kind: AtomKind,
        qualified_name: str | None = None,
    ) -> AtomDescriptor:
        """Extract a function as an atom with metadata.

        Delegates signature extraction and body hashing to the canonical
        ``AtomFunctionExtractor``.

        Args:
            func_node: The AST node for the function.
            module_path: Path to the module file.
            source: Full source code of the file.
            source_dir: Root of the source tree.
            kind: Classification of the atom.
            qualified_name: Optional qualified name (e.g., Class.method).

        Returns:
            An AtomDescriptor for the extracted function.
        """
        func_name = qualified_name or func_node.name
        rel_path = module_path.relative_to(source_dir).as_posix()

        # Delegate signature extraction to canonical extractor
        signature = self._extractor.extract_signature(func_node)

        # Delegate body hashing to canonical extractor
        content_hash = self._extractor.compute_body_hash(func_node, source)

        return AtomDescriptor(
            atom_id=f"{rel_path}:{func_name}",
            kind=kind,
            file_path=rel_path,
            function_name=func_name,
            signature=signature,
            content_hash=content_hash,
            introduced_by="collapse",
        )

    # ---- Helpers ----

    @staticmethod
    def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
        """Remove a leading docstring from a function body."""
        if not body:
            return body
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            return body[1:]
        return body

    @staticmethod
    def _get_node_source(node: ast.AST, source: str) -> str:
        """Extract source code for an AST node."""
        try:
            return ast.get_source_segment(source, node) or ""
        except (TypeError, AttributeError):
            return ""
