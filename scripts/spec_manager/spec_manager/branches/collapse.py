"""Codebase collapse to Layer 1 (design doc Section 6).

Ingests an existing codebase that has no layer separation and collapses
it to Layer 1 (algorithmic representation) by extracting algorithmic
intent from the source files.

The collapse engine:
1. Analyzes all source files for function definitions
2. Classifies each function: algorithm, store, shape, or architecture
3. Extracts algorithms/stores/shapes into atoms/
4. Records architectural remnants for future projection
5. Builds initial atom registry
"""

from __future__ import annotations

import hashlib
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source

from .layout import BranchLayout
from .types import AtomDescriptor, AtomKind

# Known I/O function names that disqualify shape classification
_IO_FUNCTIONS = frozenset(
    {
        "print",
        "open",
        "input",
        "write",
        "read",
        "send",
        "recv",
        "connect",
        "execute",
        "commit",
        "rollback",
        "close",
        "flush",
    }
)

# Store-access patterns: attribute names that indicate database/queue/file access
_STORE_PATTERNS = frozenset(
    {
        "session",
        "cursor",
        "connection",
        "db",
        "database",
        "cache",
        "queue",
        "redis",
        "store",
        "repository",
        "repo",
    }
)

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

# Regex: match function calls like ``func_name(`` or ``obj.method(``
_CALL_RE = re.compile(r"\b(\w+)\s*\(")

# Regex: match attribute access like ``obj.attr``
_ATTR_ACCESS_RE = re.compile(r"\b(\w+)\.(\w+)")

# Regex: match ``global <names>`` or ``nonlocal <names>``
_GLOBAL_NONLOCAL_RE = re.compile(r"^\s*(?:global|nonlocal)\s+", re.MULTILINE)

# Regex: match ``yield`` or ``yield from``
_YIELD_RE = re.compile(r"\byield\b")

# Regex: match non-self attribute assignment like ``obj.attr =`` (but not ``self.attr =``)
_ATTR_ASSIGN_RE = re.compile(r"(\w+)\.(\w+)\s*(?:\+|-)?\s*=")

# Regex: match identifier usage as a standalone name (not attribute access)
_IDENT_RE = re.compile(r"(?<![.\w])(\w+)(?!\w)")


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
    1. Analyze all source files for function definitions
    2. Classify each function: algorithm, store, shape, or architecture
    3. Extract algorithms/stores/shapes into atoms/
    4. Record architectural remnants for future projection
    5. Build initial atom registry

    Uses language-agnostic ``analyze_source`` for function discovery, with
    regex-based helpers for shape detection, store reference detection,
    signature extraction, and body hashing.
    """

    def __init__(self, layout: BranchLayout) -> None:
        self._layout = layout

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

            source_lines = source.splitlines()

            # Use language-agnostic analysis for function discovery
            analysis = analyze_source(source, filepath=str(py_file))

            # If the file has content but no functions were discovered and
            # it looks like it has syntax issues, report a warning.
            if (
                not analysis.functions
                and source.strip()
                and re.search(r"^\s*def\s+", source, re.MULTILINE)
            ):
                warnings.append(f"Syntax error in {py_file}: no functions parsed")
                continue

            rel_path = py_file.relative_to(source_dir)

            for func_info in analysis.functions:
                # Determine the qualified name and whether this is a class method
                qualified_name = func_info.qualified_name

                kind = self._classify_function(func_info, source_lines)
                if kind is None:
                    architectural_remnants.append(f"{rel_path}:{qualified_name}")
                else:
                    descriptor = self._extract_atom(
                        func_info,
                        py_file,
                        source,
                        source_dir,
                        kind,
                    )
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
        func_info: RawFunctionInfo,
        source_lines: list[str],
    ) -> AtomKind | None:
        """Classify a function as algorithm, store, shape, or architectural.

        Uses regex-based helpers for shape detection and store reference
        detection, combined with the branches-specific ``_ARCH_INDICATORS``
        check.

        Args:
            func_info: The function info from code analysis.
            source_lines: Lines of source for body extraction.

        Returns:
            AtomKind if the function is an atom, None if architectural.
        """
        func_name = func_info.name.lower()
        body_source = self._get_body_source(func_info, source_lines)
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

        # Shape detection via regex-based analysis
        is_shape = self._is_shape(func_info, source_lines)

        # Store reference detection via regex-based analysis
        store_refs = self._detect_store_references(func_info, source_lines)
        if store_refs:
            store_score += len(store_refs)

        # Async functions are typically architectural
        if func_info.is_async:
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
        body_stmt_count = self._estimate_body_statements(func_info, source_lines)
        if body_stmt_count >= 2:
            return AtomKind.ALGORITHM

        if is_shape:
            return AtomKind.SHAPE

        # Single-statement functions with some logic default to algorithm
        if body_stmt_count >= 1:
            return AtomKind.ALGORITHM

        return AtomKind.SHAPE

    def _extract_atom(
        self,
        func_info: RawFunctionInfo,
        module_path: Path,
        source: str,
        source_dir: Path,
        kind: AtomKind,
    ) -> AtomDescriptor:
        """Extract a function as an atom with metadata.

        Args:
            func_info: The function info from code analysis.
            module_path: Path to the module file.
            source: Full source code of the file.
            source_dir: Root of the source tree.
            kind: Classification of the atom.

        Returns:
            An AtomDescriptor for the extracted function.
        """
        func_name = func_info.qualified_name
        rel_path = module_path.relative_to(source_dir).as_posix()

        # Signature from RawFunctionInfo args and return annotation
        signature = _reconstruct_signature(func_info)

        # Body hashing from line range
        content_hash = self._compute_body_hash(func_info, source)

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
    def _get_body_source(
        func_info: RawFunctionInfo,
        source_lines: list[str],
    ) -> str:
        """Extract function body source from line range."""
        start = func_info.start_line - 1
        end = func_info.end_line
        if start < 0 or end > len(source_lines):
            return ""
        return "\n".join(source_lines[start:end])

    @staticmethod
    def _estimate_body_statements(
        func_info: RawFunctionInfo,
        source_lines: list[str],
    ) -> int:
        """Estimate the number of top-level body statements (excluding docstring).

        Uses the body_start_line from RawFunctionInfo (which points past the
        ``def`` line) and counts non-blank, non-comment, non-decorator lines
        at the body indentation level.  Subtracts 1 if the function has a
        docstring.
        """
        body_start = func_info.body_start_line
        body_end = func_info.end_line
        if body_start <= 0 or body_end <= 0 or body_start > len(source_lines):
            # Fallback: use body_line_count directly
            count = func_info.body_line_count
            if func_info.has_docstring:
                count = max(0, count - 1)
            return count

        # Find the indentation level of the body
        body_indent: int | None = None
        for i in range(body_start - 1, min(body_end, len(source_lines))):
            line = source_lines[i]
            stripped = line.lstrip()
            if stripped and not stripped.startswith("#"):
                body_indent = len(line) - len(stripped)
                break

        if body_indent is None:
            return 0

        # Count lines at body indentation level (top-level statements)
        stmt_count = 0
        in_docstring = False
        docstring_skipped = False

        for i in range(body_start - 1, min(body_end, len(source_lines))):
            line = source_lines[i]
            stripped = line.lstrip()
            indent = len(line) - len(stripped) if stripped else -1

            # Skip blank lines and comments
            if not stripped or stripped.startswith("#"):
                continue

            # Track triple-quoted strings (docstrings)
            if not docstring_skipped and (stripped.startswith('"""') or stripped.startswith("'''")):
                quote = stripped[:3]
                if stripped.count(quote) >= 2 and len(stripped) > 3:
                    # Single-line docstring
                    docstring_skipped = True
                    continue
                else:
                    in_docstring = not in_docstring
                    if not in_docstring:
                        docstring_skipped = True
                    continue

            if in_docstring:
                continue

            # Only count lines at the body indentation level
            if indent == body_indent:
                stmt_count += 1

        return stmt_count

    @staticmethod
    def _is_shape(
        func_info: RawFunctionInfo,
        source_lines: list[str],
    ) -> bool:
        """Determine if a function is a pure shape (no side effects) via regex.

        A shape function has:
        - No global/nonlocal statements
        - No attribute assignment on non-self objects
        - No calls to known I/O functions
        - No yield/yield from (generators)
        """
        start = func_info.start_line - 1
        end = func_info.end_line
        if start < 0 or end > len(source_lines):
            return True

        body_text = "\n".join(source_lines[start:end])

        # Check for global/nonlocal
        if _GLOBAL_NONLOCAL_RE.search(body_text):
            return False

        # Check for yield/yield from
        if _YIELD_RE.search(body_text):
            return False

        # Check for non-self attribute assignment
        for match in _ATTR_ASSIGN_RE.finditer(body_text):
            obj_name = match.group(1)
            if obj_name != "self":
                return False

        # Check for calls to known I/O functions
        for match in _CALL_RE.finditer(body_text):
            called_name = match.group(1)
            if called_name in _IO_FUNCTIONS:
                return False
            # Also check attribute-style calls like obj.write(...)
        for match in _ATTR_ACCESS_RE.finditer(body_text):
            attr_name = match.group(2)
            # Check if this is a call: attr followed by ``(``
            end_pos = match.end()
            rest = body_text[end_pos:].lstrip()
            if rest.startswith("(") and attr_name in _IO_FUNCTIONS:
                return False

        return True

    @staticmethod
    def _detect_store_references(
        func_info: RawFunctionInfo,
        source_lines: list[str],
    ) -> list[str]:
        """Detect store/database access patterns in a function via regex."""
        start = func_info.start_line - 1
        end = func_info.end_line
        if start < 0 or end > len(source_lines):
            return []

        body_text = "\n".join(source_lines[start:end])

        store_refs: list[str] = []
        seen: set[str] = set()

        # Check attribute access: ``obj.attr`` where obj matches store patterns
        for match in _ATTR_ACCESS_RE.finditer(body_text):
            obj_name = match.group(1)
            if obj_name.lower() in _STORE_PATTERNS and obj_name not in seen:
                seen.add(obj_name)
                store_refs.append(obj_name)

        # Check standalone identifiers matching store patterns
        for match in _IDENT_RE.finditer(body_text):
            name = match.group(1)
            if name.lower() in _STORE_PATTERNS and name not in seen:
                seen.add(name)
                store_refs.append(name)

        return store_refs

    @staticmethod
    def _compute_body_hash(
        func_info: RawFunctionInfo,
        source: str,
    ) -> str:
        """Compute SHA-256 hash of the function body source."""
        lines = source.splitlines()
        body_start = func_info.start_line
        body_end = func_info.end_line
        body_lines = lines[body_start - 1 : body_end]
        body_text = "\n".join(body_lines)
        body_text = textwrap.dedent(body_text).strip()
        return hashlib.sha256(body_text.encode("utf-8")).hexdigest()


def _reconstruct_signature(func_info: RawFunctionInfo) -> str:
    """Reconstruct a function signature from RawFunctionInfo.

    Builds a signature string like ``(arg1, arg2, ...) -> ReturnType``
    from the function's args tuple and return annotation.

    Args:
        func_info: The raw function info from code analysis.

    Returns:
        Signature string.
    """
    sig = f"({', '.join(func_info.args)})"
    if func_info.return_annotation:
        sig += f" -> {func_info.return_annotation}"
    return sig
