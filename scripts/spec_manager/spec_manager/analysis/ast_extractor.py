"""Atom function extractor using language-agnostic code analysis.

Scans source files to identify atom functions and extract their metadata.
Uses ``spec_manager.core.code_analysis.analyze_source`` for structural
analysis, combined with convention-based heuristics and optional annotations
for atom identification.

Detection methods:
- Convention-based: Functions in designated directories (atoms/, shapes/)
- Size heuristic: Small functions with docstrings
- Annotation override: ``# @pin`` comment markers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source


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
    exclude_patterns: list[str] = field(default_factory=lambda: ["test_", "_test", "conftest"])


class AtomFunctionExtractor:
    """Extracts atom function candidates from source files using code analysis."""

    def __init__(self, config: ExtractionConfig | None = None) -> None:
        self.config = config or ExtractionConfig()

    def extract_from_file(self, file_path: Path) -> list[AtomCandidate]:
        """Extract atom candidates from a single source file.

        Args:
            file_path: Path to the source file.

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

        # Use language-agnostic code analysis
        analysis = analyze_source(source, str(file_path))
        if not analysis.functions:
            return []

        # Determine module path from file path
        module_path = self._file_to_module(file_path)

        # Check if file is in a convention directory
        is_convention = self._is_convention_directory(file_path)

        # Check for annotation markers in source
        source_lines = source.splitlines()
        annotated_functions = self._find_annotated_functions(source_lines)

        # Check if file is in a shapes/ directory (convention-based shape detection)
        is_shapes_dir = self._is_shapes_directory(file_path)

        candidates: list[AtomCandidate] = []

        for raw_func in analysis.functions:
            # Determine detection method
            detection_method = self._classify_detection(
                raw_func.name, file_path, is_convention, annotated_functions
            )
            if detection_method is None:
                continue

            # Build qualified name with module path prefix
            qualified_name = f"{module_path}.{raw_func.qualified_name}"

            # Get docstring (first line only)
            docstring = ""
            if raw_func.docstring:
                docstring = raw_func.docstring.split("\n")[0].strip()

            # Check heuristic: require docstring if configured
            if detection_method == "heuristic" and self.config.require_docstring and not docstring:
                continue

            # Extract line range
            line_start = raw_func.start_line
            line_end = raw_func.end_line

            # Check heuristic: max function lines
            body_lines = line_end - line_start + 1
            if detection_method == "heuristic" and body_lines > self.config.max_function_lines:
                continue

            # Extract body source from line range
            body_source = self._extract_body_source(source_lines, line_start, line_end)

            # Reconstruct signature from args + return_annotation
            signature = _reconstruct_signature(raw_func)

            # Shape detection: convention-based for shapes/ directory, else False
            # Shape detection moved to LLM-based analysis
            is_shape = is_shapes_dir

            # Store references: moved to evidence-based system
            store_refs: list[str] = []

            # Called functions: moved to evidence-based system
            called: list[str] = []

            candidates.append(
                AtomCandidate(
                    function_name=raw_func.name,
                    qualified_name=qualified_name,
                    file_path=str(file_path),
                    module_path=module_path,
                    line_start=line_start,
                    line_end=line_end,
                    signature=signature,
                    docstring=docstring,
                    body_source=body_source,
                    is_shape=is_shape,
                    detection_method=detection_method,
                    store_references=store_refs,
                    called_functions=called,
                )
            )

        return candidates

    def extract_from_directory(self, dir_path: Path, recursive: bool = True) -> list[AtomCandidate]:
        """Extract atom candidates from all source files in a directory.

        Args:
            dir_path: Directory to scan.
            recursive: Whether to scan subdirectories.

        Returns:
            List of AtomCandidate objects found in all files.
        """
        candidates: list[AtomCandidate] = []
        # TODO(multi-language): Expand to scan for all source files, not just *.py
        pattern = "**/*.py" if recursive else "*.py"
        for py_file in sorted(dir_path.glob(pattern)):
            if py_file.is_file():
                candidates.extend(self.extract_from_file(py_file))
        return candidates

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
        return any(atom_dir.lower() in path_parts for atom_dir in self.config.atom_directories)

    def _is_shapes_directory(self, file_path: Path) -> bool:
        """Check if a file is in a shapes/ directory.

        Convention: files in a ``shapes/`` directory are treated as shape
        functions (pure, no side effects).

        Args:
            file_path: Path to check.

        Returns:
            True if any parent directory is named ``shapes``.
        """
        return "shapes" in [p.lower() for p in file_path.parts]

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
        func_name: str,
        file_path: Path,
        is_convention: bool,
        annotated_functions: set[str],
    ) -> str | None:
        """Classify the detection method for a function.

        Args:
            func_name: The function name.
            file_path: Source file path.
            is_convention: Whether the file is in a convention directory.
            annotated_functions: Set of explicitly annotated function names.

        Returns:
            Detection method string ("convention", "annotation", "heuristic")
            or None if the function should not be extracted.
        """
        # Skip private/dunder methods
        if func_name.startswith("_"):
            # But allow annotated private functions
            if func_name in annotated_functions:
                return "annotation"
            return None

        if func_name in annotated_functions:
            return "annotation"

        if is_convention:
            return "convention"

        # Heuristic: small function with docstring
        return "heuristic"

    def _extract_body_source(self, source_lines: list[str], line_start: int, line_end: int) -> str:
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


def _reconstruct_signature(func: RawFunctionInfo) -> str:
    """Reconstruct a function signature from RawFunctionInfo.

    Builds a signature string like ``(arg1, arg2, ...) -> ReturnType``
    from the function's args tuple and return annotation.

    Args:
        func: The raw function info from code analysis.

    Returns:
        Signature string.
    """
    sig = f"({', '.join(func.args)})"
    if func.return_annotation:
        sig += f" -> {func.return_annotation}"
    return sig


__all__ = [
    "AtomCandidate",
    "AtomFunctionExtractor",
    "ExtractionConfig",
]
