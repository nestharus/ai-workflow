"""AST-based atom function extractor.

Scans Python source files to identify atom functions and extract their metadata.
Uses a combination of heuristics and optional annotations for atom identification.

Detection methods:
- Convention-based: Functions in designated directories (atoms/, shapes/)
- Size heuristic: Small functions with docstrings
- Annotation override: ``# @pin`` comment markers
- Shape detection: Pure functions (no side effects)
"""

from __future__ import annotations

import ast
import hashlib
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

# Known I/O function names that disqualify shape classification
_IO_FUNCTIONS = frozenset({
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
})

# Store-access patterns: attribute names that indicate database/queue/file access
_STORE_PATTERNS = frozenset({
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
})


@dataclass
class AtomCandidate:
    """A function identified as a potential pin-function atom."""

    function_name: str
    qualified_name: str  # module.class.function
    file_path: str
    module_path: str
    line_start: int
    line_end: int
    signature: str
    docstring: str
    body_source: str  # Raw source of function body
    is_shape: bool  # Pure function detection result
    detection_method: str  # "convention", "heuristic", "annotation"
    store_references: list[str] = field(default_factory=list)
    called_functions: list[str] = field(default_factory=list)


@dataclass
class ExtractionConfig:
    """Configuration for atom extraction."""

    atom_directories: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    max_function_lines: int = 30
    require_docstring: bool = True
    annotation_marker: str = "# @pin"
    exclude_patterns: list[str] = field(
        default_factory=lambda: ["test_", "_test", "conftest"]
    )


class AtomFunctionExtractor:
    """Extracts atom function candidates from Python source files using AST analysis."""

    def __init__(self, config: ExtractionConfig | None = None) -> None:
        self.config = config or ExtractionConfig()

    def extract_from_file(self, file_path: Path) -> list[AtomCandidate]:
        """Extract atom candidates from a single Python file.

        Args:
            file_path: Path to the Python source file.

        Returns:
            List of AtomCandidate objects found in the file.
        """
        # Check exclusion patterns
        file_name = file_path.stem
        for pattern in self.config.exclude_patterns:
            if pattern in file_name:
                return []

        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            return []

        # Determine module path from file path
        module_path = self._file_to_module(file_path)

        # Check if file is in a convention directory
        is_convention = self._is_convention_directory(file_path)

        # Check for annotation markers in source
        source_lines = source.splitlines()
        annotated_functions = self._find_annotated_functions(source_lines)

        candidates: list[AtomCandidate] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Determine detection method
            detection_method = self._classify_detection(
                node, file_path, is_convention, annotated_functions
            )
            if detection_method is None:
                continue

            # Build qualified name
            qualified_name = f"{module_path}.{node.name}"

            # Get docstring
            docstring = ast.get_docstring(node) or ""
            if docstring:
                # Take first line only
                docstring = docstring.split("\n")[0].strip()

            # Check heuristic: require docstring if configured
            if (
                detection_method == "heuristic"
                and self.config.require_docstring
                and not docstring
            ):
                continue

            # Extract line range
            line_start = node.lineno
            line_end = node.end_lineno or node.lineno

            # Check heuristic: max function lines
            body_lines = line_end - line_start + 1
            if detection_method == "heuristic" and body_lines > self.config.max_function_lines:
                continue

            # Extract body source
            body_source = self._extract_body_source(source_lines, line_start, line_end)

            # Extract signature
            signature = self.extract_signature(node)

            # Detect shape (pure function)
            shape = self.is_shape(node, file_path)

            # Detect store references
            store_refs = self.detect_store_references(node)

            # Detect called functions
            called = self._detect_called_functions(node)

            candidates.append(
                AtomCandidate(
                    function_name=node.name,
                    qualified_name=qualified_name,
                    file_path=str(file_path),
                    module_path=module_path,
                    line_start=line_start,
                    line_end=line_end,
                    signature=signature,
                    docstring=docstring,
                    body_source=body_source,
                    is_shape=shape,
                    detection_method=detection_method,
                    store_references=store_refs,
                    called_functions=called,
                )
            )

        return candidates

    def extract_from_directory(
        self, dir_path: Path, recursive: bool = True
    ) -> list[AtomCandidate]:
        """Extract atom candidates from all Python files in a directory.

        Args:
            dir_path: Directory to scan.
            recursive: Whether to scan subdirectories.

        Returns:
            List of AtomCandidate objects found in all files.
        """
        candidates: list[AtomCandidate] = []
        pattern = "**/*.py" if recursive else "*.py"
        for py_file in sorted(dir_path.glob(pattern)):
            if py_file.is_file():
                candidates.extend(self.extract_from_file(py_file))
        return candidates

    def is_shape(self, node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: Path) -> bool:
        """Determine if a function is a pure shape (no side effects).

        A shape function has:
        - No global/nonlocal statements
        - No attribute assignment on non-self objects
        - No calls to known I/O functions
        - No yield/yield from (generators)

        Args:
            node: The AST function definition node.
            file_path: Path to the source file (unused, kept for API compat).

        Returns:
            True if the function appears to be a pure shape.
        """
        for child in ast.walk(node):
            # Check for global/nonlocal
            if isinstance(child, (ast.Global, ast.Nonlocal)):
                return False

            # Check for yield (generator)
            if isinstance(child, (ast.Yield, ast.YieldFrom)):
                return False

            # Check for attribute assignment on non-self objects
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Attribute):
                        if not (
                            isinstance(target.value, ast.Name)
                            and target.value.id == "self"
                        ):
                            return False

            if isinstance(child, ast.AugAssign):
                if isinstance(child.target, ast.Attribute):
                    if not (
                        isinstance(child.target.value, ast.Name)
                        and child.target.value.id == "self"
                    ):
                        return False

            # Check for calls to known I/O functions
            if isinstance(child, ast.Call):
                func_name = self._get_call_name(child)
                if func_name and func_name in _IO_FUNCTIONS:
                    return False

        return True

    def detect_store_references(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
        """Detect store/database access patterns in a function.

        Args:
            node: The AST function definition node.

        Returns:
            List of detected store reference names.
        """
        store_refs: list[str] = []
        seen: set[str] = set()

        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                if isinstance(child.value, ast.Name):
                    name = child.value.id
                    if name.lower() in _STORE_PATTERNS and name not in seen:
                        seen.add(name)
                        store_refs.append(name)
            elif isinstance(child, ast.Name):
                if child.id.lower() in _STORE_PATTERNS and child.id not in seen:
                    seen.add(child.id)
                    store_refs.append(child.id)

        return store_refs

    def extract_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Extract the function signature as a string.

        Args:
            node: The AST function definition node.

        Returns:
            String representation of the function signature.
        """
        args = node.args
        parts: list[str] = []

        # Count how many positional args lack defaults
        # defaults are right-aligned to the positional args
        num_args = len(args.args)
        num_defaults = len(args.defaults)
        first_default_idx = num_args - num_defaults

        for i, arg in enumerate(args.args):
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            # Check if this arg has a default
            default_idx = i - first_default_idx
            if default_idx >= 0 and default_idx < len(args.defaults):
                arg_str += f" = {ast.unparse(args.defaults[default_idx])}"
            parts.append(arg_str)

        # Handle *args
        if args.vararg:
            vararg_str = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                vararg_str += f": {ast.unparse(args.vararg.annotation)}"
            parts.append(vararg_str)
        elif args.kwonlyargs:
            parts.append("*")

        # Handle keyword-only args
        for i, kwarg in enumerate(args.kwonlyargs):
            kw_str = kwarg.arg
            if kwarg.annotation:
                kw_str += f": {ast.unparse(kwarg.annotation)}"
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                kw_str += f" = {ast.unparse(args.kw_defaults[i])}"
            parts.append(kw_str)

        # Handle **kwargs
        if args.kwarg:
            kwarg_str = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                kwarg_str += f": {ast.unparse(args.kwarg.annotation)}"
            parts.append(kwarg_str)

        sig = f"({', '.join(parts)})"

        # Add return annotation
        if node.returns:
            sig += f" -> {ast.unparse(node.returns)}"

        return sig

    def compute_body_hash(self, node: ast.FunctionDef | ast.AsyncFunctionDef, source: str) -> str:
        """Compute SHA-256 hash of the function body source.

        Args:
            node: The AST function definition node.
            source: The full source code of the file.

        Returns:
            64-character hex SHA-256 hash of the function body.
        """
        lines = source.splitlines()
        body_start = node.lineno  # 1-based
        body_end = node.end_lineno or node.lineno
        body_lines = lines[body_start - 1 : body_end]
        body_text = "\n".join(body_lines)
        # Normalize whitespace for deterministic hashing
        body_text = textwrap.dedent(body_text).strip()
        return hashlib.sha256(body_text.encode("utf-8")).hexdigest()

    # --- Private helpers ---

    def _file_to_module(self, file_path: Path) -> str:
        """Convert a file path to a module path.

        Args:
            file_path: Path to the Python file.

        Returns:
            Dotted module path string.
        """
        parts = list(file_path.with_suffix("").parts)
        # Remove leading dots/current dir markers
        while parts and parts[0] in (".", ".."):
            parts.pop(0)
        return ".".join(parts)

    def _is_convention_directory(self, file_path: Path) -> bool:
        """Check if a file is in a convention-based atom directory.

        Args:
            file_path: Path to check.

        Returns:
            True if any parent directory matches an atom directory name.
        """
        path_parts = [p.lower() for p in file_path.parts]
        for atom_dir in self.config.atom_directories:
            if atom_dir.lower() in path_parts:
                return True
        return False

    def _find_annotated_functions(self, source_lines: list[str]) -> set[str]:
        """Find function names preceded by the annotation marker.

        Args:
            source_lines: Lines of source code.

        Returns:
            Set of function names that have the annotation marker.
        """
        annotated: set[str] = set()
        marker = self.config.annotation_marker

        for i, line in enumerate(source_lines):
            stripped = line.strip()
            if stripped == marker or stripped.startswith(marker + " "):
                # Look for the next function def
                for j in range(i + 1, len(source_lines)):
                    next_line = source_lines[j].strip()
                    if not next_line or next_line.startswith("#") or next_line.startswith("@"):
                        continue
                    if next_line.startswith("def ") or next_line.startswith("async def "):
                        func_name = next_line.split("(")[0].split()[-1]
                        annotated.add(func_name)
                    break

        return annotated

    def _classify_detection(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: Path,
        is_convention: bool,
        annotated_functions: set[str],
    ) -> str | None:
        """Classify the detection method for a function.

        Args:
            node: The function AST node.
            file_path: Source file path.
            is_convention: Whether the file is in a convention directory.
            annotated_functions: Set of explicitly annotated function names.

        Returns:
            Detection method string ("convention", "annotation", "heuristic")
            or None if the function should not be extracted.
        """
        # Skip private/dunder methods
        if node.name.startswith("_"):
            # But allow annotated private functions
            if node.name in annotated_functions:
                return "annotation"
            return None

        if node.name in annotated_functions:
            return "annotation"

        if is_convention:
            return "convention"

        # Heuristic: small function with docstring
        return "heuristic"

    def _extract_body_source(
        self, source_lines: list[str], line_start: int, line_end: int
    ) -> str:
        """Extract function body source from line range.

        Args:
            source_lines: All source lines.
            line_start: 1-based start line.
            line_end: 1-based end line.

        Returns:
            The function body source text.
        """
        body = source_lines[line_start - 1 : line_end]
        return "\n".join(body)

    def _detect_called_functions(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> list[str]:
        """Detect function names called within this function.

        Args:
            node: The function AST node.

        Returns:
            List of called function names.
        """
        called: list[str] = []
        seen: set[str] = set()

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                name = self._get_call_name(child)
                if name and name not in seen:
                    seen.add(name)
                    called.append(name)

        return called

    def _get_call_name(self, call_node: ast.Call) -> str | None:
        """Get the name of a called function from an ast.Call node.

        Args:
            call_node: The AST Call node.

        Returns:
            The function name if it can be determined, None otherwise.
        """
        func = call_node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None


__all__ = [
    "AtomCandidate",
    "AtomFunctionExtractor",
    "ExtractionConfig",
]
