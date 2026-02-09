"""Import graph builder for pin-function tracing.

Builds the import graph that maps which architectural files import which
pin-functions. Scans source files for import statements using regex,
matches them against registered pin-function names, and classifies each
usage site's projection type.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import ImportEdge, PinFunction, ProjectionType

# ---------------------------------------------------------------------------
# Regex patterns for import and structure detection
# ---------------------------------------------------------------------------

_IMPORT_RE = re.compile(r"^\s*import\s+(.+)", re.MULTILINE)
_FROM_IMPORT_RE = re.compile(r"^\s*from\s+(\S+)\s+import\s+(.+)", re.MULTILINE)
_FUNC_DEF_RE = re.compile(r"^(\s*)(async\s+)?def\s+(\w+)\s*\(", re.MULTILINE)
_CLASS_DEF_RE = re.compile(r"^(\s*)class\s+(\w+)\s*[:\(]", re.MULTILINE)
_DECORATOR_RE = re.compile(r"^\s*@", re.MULTILINE)


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

    algorithmic_roots: list[str] = field(default_factory=lambda: ["atoms", "shapes"])
    architectural_roots: list[str] = field(default_factory=lambda: ["services", "handlers"])
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
                            arch_location=self._build_arch_location(str(py_file), usage),
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

        Uses regex-based import detection instead of Python AST parsing.

        Args:
            file_path: Path to the Python source file.

        Returns:
            List of ImportReference objects detected in the file.
        """
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return []

        references: list[ImportReference] = []

        # Collect all imports from algorithmic roots
        imported_names: dict[str, ImportReference] = {}

        lines = source.split("\n")

        # Scan for 'from X import Y' statements
        for match in _FROM_IMPORT_RE.finditer(source):
            module = match.group(1)
            if not self._is_algorithmic_module(module):
                continue
            names_str = match.group(2).strip()
            # Compute line number from match position
            line_no = source[: match.start()].count("\n") + 1
            # Parse comma-separated names, handling "name as alias" syntax
            for name_part in self._parse_import_names(names_str):
                orig_name, alias = name_part
                if not orig_name.isidentifier():
                    continue
                local_name = alias or orig_name
                ref = ImportReference(
                    pin_func_name=orig_name,
                    import_module=module,
                    file_path=str(file_path),
                    import_line=line_no,
                    alias=alias,
                )
                imported_names[local_name] = ref
                references.append(ref)

        # Scan for 'import X' statements
        for match in _IMPORT_RE.finditer(source):
            # Skip 'from ... import ...' lines (already handled above)
            full_line = match.group(0).strip()
            if full_line.startswith("from "):
                continue
            names_str = match.group(1).strip()
            line_no = source[: match.start()].count("\n") + 1
            for name_part in self._parse_import_names(names_str):
                orig_name, alias = name_part
                if not self._is_algorithmic_module(orig_name):
                    continue
                local_name = alias or orig_name
                ref = ImportReference(
                    pin_func_name=orig_name,
                    import_module=orig_name,
                    file_path=str(file_path),
                    import_line=line_no,
                    alias=alias,
                )
                imported_names[local_name] = ref
                references.append(ref)

        # Find usage sites for imported names
        if imported_names:
            self._find_usage_sites(lines, imported_names)

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
        return [(func, names) for func, names in by_enclosing.items() if len(names) >= 2]

    # --- Private helpers ---

    def _is_algorithmic_module(self, module_name: str) -> bool:
        """Check if a module name belongs to an algorithmic root."""
        module_parts = module_name.split(".")
        return any(root in module_parts for root in self.config.algorithmic_roots)

    @staticmethod
    def _parse_import_names(names_str: str) -> list[tuple[str, str | None]]:
        """Parse a comma-separated import names string.

        Handles 'name', 'name as alias', parenthesised lists, and trailing
        comments.  Returns a list of (original_name, alias_or_None) tuples.
        """
        # Strip parentheses and inline comments
        cleaned = names_str.strip().strip("()")
        # Remove trailing comment
        if "#" in cleaned:
            cleaned = cleaned[: cleaned.index("#")]

        result: list[tuple[str, str | None]] = []
        for part in cleaned.split(","):
            part = part.strip()
            if not part:
                continue
            # Handle 'name as alias'
            as_match = re.match(r"(\S+)\s+as\s+(\S+)", part)
            if as_match:
                result.append((as_match.group(1), as_match.group(2)))
            else:
                # Just a plain name — strip any trailing whitespace/continuation
                name = part.strip()
                if name.isidentifier() or "." in name:
                    result.append((name, None))
        return result

    def _find_usage_sites(
        self,
        lines: list[str],
        imported_names: dict[str, ImportReference],
    ) -> None:
        """Find all call sites for imported pin-functions using regex.

        Mutates the ImportReference objects to add usage sites.

        Args:
            lines: Source code split into lines.
            imported_names: Map of local names to their ImportReference.
        """
        # Build function/class structure from source lines
        func_ranges = self._extract_function_ranges(lines)

        # Build call-detection patterns for each imported name
        call_patterns: dict[str, re.Pattern[str]] = {}
        for local_name in imported_names:
            # Match 'name(' as a function call (word boundary on the left)
            call_patterns[local_name] = re.compile(r"\b" + re.escape(local_name) + r"\s*\(")

        # Scan each function body for calls to imported names
        for func_info in func_ranges:
            func_name = func_info["name"]
            enclosing_class = func_info.get("class")
            is_decorated = func_info.get("decorated", False)
            body_start = func_info["body_start"]  # 0-indexed line index
            body_end = func_info["body_end"]  # 0-indexed exclusive

            for line_idx in range(body_start, min(body_end, len(lines))):
                line = lines[line_idx]
                # Skip comment-only lines
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue
                # Skip string-only lines (rough heuristic)
                if stripped.startswith(('"""', "'''", '"', "'")):
                    continue

                for local_name, pattern in call_patterns.items():
                    if pattern.search(line):
                        call_pattern = "direct"
                        if is_decorated:
                            call_pattern = "wrapped"

                        usage = UsageSite(
                            line=line_idx + 1,  # 1-based line number
                            enclosing_function=func_name,
                            enclosing_class=enclosing_class,
                            call_pattern=call_pattern,
                        )
                        imported_names[local_name].usage_sites.append(usage)

    def _extract_function_ranges(
        self,
        lines: list[str],
    ) -> list[dict]:
        """Extract function definitions with their line ranges from source lines.

        Returns a list of dicts with keys:
            name: function name
            class: enclosing class name or None
            decorated: whether the function has decorators
            body_start: 0-indexed start line of function body
            body_end: 0-indexed exclusive end line of function body
        """
        source = "\n".join(lines)
        functions: list[dict] = []

        # First, find all class definitions and their indentation
        class_ranges: list[dict] = []
        for match in _CLASS_DEF_RE.finditer(source):
            indent = len(match.group(1))
            name = match.group(2)
            start_line_idx = source[: match.start()].count("\n")
            class_ranges.append(
                {
                    "name": name,
                    "indent": indent,
                    "start_line": start_line_idx,
                }
            )

        # Find all function definitions
        for match in _FUNC_DEF_RE.finditer(source):
            indent = len(match.group(1))
            func_name = match.group(3)
            def_line_idx = source[: match.start()].count("\n")

            # Determine body start (line after the def line, accounting for
            # multi-line signatures by finding the colon)
            body_start = def_line_idx + 1
            # Scan forward to find the colon ending the signature
            for i in range(def_line_idx, len(lines)):
                if ":" in lines[i]:
                    # Check if the colon is part of the def line (not in a string)
                    # Simple heuristic: the last colon on the line that isn't inside
                    # a string marks the end of the signature
                    body_start = i + 1
                    break

            # Determine body end: next line at same or lower indentation level
            body_end = len(lines)
            for i in range(body_start, len(lines)):
                line = lines[i]
                if not line.strip():
                    continue  # Skip blank lines
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= indent:
                    body_end = i
                    break

            # Check if this function is inside a class
            enclosing_class = self._find_enclosing_class_regex(class_ranges, def_line_idx, indent)

            # Check for decorators (lines before def that start with @)
            is_decorated = False
            check_line = def_line_idx - 1
            while check_line >= 0:
                stripped = lines[check_line].strip()
                if stripped.startswith("@"):
                    is_decorated = True
                    break
                if stripped == "" or stripped.startswith("#"):
                    check_line -= 1
                    continue
                break  # Non-decorator, non-blank line
                check_line -= 1

            functions.append(
                {
                    "name": func_name,
                    "class": enclosing_class,
                    "decorated": is_decorated,
                    "body_start": body_start,
                    "body_end": body_end,
                }
            )

        return functions

    @staticmethod
    def _find_enclosing_class_regex(
        class_ranges: list[dict],
        func_line_idx: int,
        func_indent: int,
    ) -> str | None:
        """Find the class that encloses a function based on indentation."""
        best: dict | None = None
        for cr in class_ranges:
            # Class must start before the function and have lower indentation
            if (
                cr["start_line"] < func_line_idx
                and cr["indent"] < func_indent
                and (best is None or cr["start_line"] > best["start_line"])
            ):
                best = cr
        return best["name"] if best else None

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

        for _location, loc_edges in by_location.items():
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
