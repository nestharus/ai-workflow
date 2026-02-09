"""Call graph extractor using language-agnostic source analysis.

Uses ``analyze_source`` from :mod:`spec_manager.core.code_analysis` to
discover function/method definitions, then applies regex-based call-site
detection on each function body to record call relationships.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spec_manager.core.code_analysis import RawFunctionInfo, analyze_source

from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType

# ---------------------------------------------------------------------------
# Regex patterns for call-site detection
# ---------------------------------------------------------------------------

# Matches function/method calls: word(...) or word.word(...)
# Captures the full dotted name before the opening parenthesis.
_CALL_RE = re.compile(r"\b(\w+(?:\.\w+)*)\s*\(")


@dataclass
class CallSite:
    """A detected function call site."""

    caller: str  # fully qualified caller name (module.class.method or module.function)
    callee: str  # name of the called function
    file_path: str
    line_number: int
    is_method_call: bool  # obj.method() vs function()


def extract_call_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
) -> AdjacencyGraph:
    """Build a call graph from source files.

    Analyzes each file to discover functions, then uses regex to detect
    call relationships between them.

    Args:
        source_paths: Source files to analyze
        root_dir: Project root for computing module-qualified names

    Returns:
        AdjacencyGraph with SignalType.CALL edges
    """
    graph = AdjacencyGraph()
    all_functions: list[NodeInfo] = []
    all_calls: list[CallSite] = []

    for path in source_paths:
        if not path.exists() or path.suffix != ".py":
            continue
        # Skip test files and __init__.py by default
        if path.name.startswith("test_") or path.name == "__init__.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        analysis = analyze_source(source, filepath=str(path))

        if not analysis.functions:
            continue

        source_lines = source.splitlines()
        module = _module_prefix(path, root_dir)

        functions = _extract_functions(analysis.functions, path, module)
        calls = _extract_calls(analysis.functions, source_lines, path, module)
        all_functions.extend(functions)
        all_calls.extend(calls)

    # Build set of known function names for resolution
    known_functions: set[str] = set()
    for info in all_functions:
        graph.add_node(info.node_id, info)
        known_functions.add(info.node_id)

    # Resolve calls and add edges
    for call_site in all_calls:
        resolved = _resolve_callee(call_site, known_functions)
        if resolved is not None and call_site.caller != resolved:
            graph.add_edge(
                call_site.caller,
                resolved,
                EdgeSignal(
                    signal_type=SignalType.CALL,
                    weight=1.0,
                    details={
                        "file_path": call_site.file_path,
                        "line_number": call_site.line_number,
                        "is_method_call": call_site.is_method_call,
                    },
                ),
            )

    return graph


def _module_prefix(file_path: Path, root_dir: Path | None) -> str:
    """Compute a module prefix from a file path relative to root_dir."""
    if root_dir is not None:
        try:
            rel = file_path.relative_to(root_dir)
            parts = list(rel.with_suffix("").parts)
            return ".".join(parts)
        except ValueError:
            pass
    return file_path.stem


def _qualified_node_id(func: RawFunctionInfo, module: str) -> str:
    """Build a fully-qualified node ID from a RawFunctionInfo.

    The ``qualified_name`` from the analysis already contains the
    class/nesting path (e.g. ``ClassName.method`` or ``outer.inner``).
    We prepend the module prefix to get something like
    ``module.ClassName.method``.
    """
    qname = func.qualified_name or func.name
    return f"{module}.{qname}"


def _extract_functions(
    raw_functions: list[RawFunctionInfo],
    file_path: Path,
    module: str,
) -> list[NodeInfo]:
    """Convert RawFunctionInfo list into NodeInfo list for the graph."""
    functions: list[NodeInfo] = []

    for func in raw_functions:
        qualified_name = _qualified_node_id(func, module)
        functions.append(
            NodeInfo(
                node_id=qualified_name,
                node_type="async_function" if func.is_async else "function",
                file_path=str(file_path),
                line_number=func.start_line,
                metadata={"module": module},
            )
        )

    return functions


def _extract_calls(
    raw_functions: list[RawFunctionInfo],
    source_lines: list[str],
    file_path: Path,
    module: str,
) -> list[CallSite]:
    """Extract call sites from each function body using regex."""
    calls: list[CallSite] = []

    for func in raw_functions:
        caller = _qualified_node_id(func, module)
        # Extract the body text from source lines
        # body_start_line is 1-indexed; body_line_count is the number of lines
        body_start = func.body_start_line
        body_count = func.body_line_count

        if body_start <= 0 or body_count <= 0:
            # Fallback: use the full function range (start_line to end_line)
            body_start = func.start_line
            body_count = max(func.end_line - func.start_line + 1, 0)

        if body_count <= 0:
            continue

        # Convert to 0-indexed for slicing
        start_idx = body_start - 1
        end_idx = start_idx + body_count
        body_lines = source_lines[start_idx:end_idx]

        for line_offset, line_text in enumerate(body_lines):
            line_number = body_start + line_offset
            # Skip comment-only lines and def/class lines
            stripped = line_text.strip()
            if (
                stripped.startswith("#")
                or stripped.startswith("def ")
                or stripped.startswith("async def ")
                or stripped.startswith("class ")
            ):
                continue

            for match in _CALL_RE.finditer(line_text):
                callee_name = match.group(1)
                # Skip language keywords and builtins that look like calls
                if callee_name in _SKIP_NAMES:
                    continue
                is_method = "." in callee_name
                calls.append(
                    CallSite(
                        caller=caller,
                        callee=callee_name,
                        file_path=str(file_path),
                        line_number=line_number,
                        is_method_call=is_method,
                    )
                )

    return calls


# Names to skip in regex call detection (keywords, builtins, control flow)
_SKIP_NAMES: frozenset[str] = frozenset(
    {
        "if",
        "elif",
        "while",
        "for",
        "with",
        "assert",
        "raise",
        "except",
        "print",
        "type",
        "isinstance",
        "issubclass",
        "len",
        "range",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "list",
        "dict",
        "set",
        "tuple",
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "bytearray",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "open",
        "input",
        "round",
        "abs",
        "min",
        "max",
        "sum",
        "any",
        "all",
        "next",
        "iter",
        "repr",
        "hash",
        "id",
        "vars",
        "dir",
        "help",
        "hex",
        "oct",
        "bin",
        "chr",
        "ord",
        "callable",
        "format",
        "object",
    }
)


def _resolve_callee(call_site: CallSite, known_functions: set[str]) -> str | None:
    """Attempt to resolve a callee name to a known function.

    Handles simple cases (direct calls) and common patterns
    (self.method, module.function). Does NOT resolve dynamic dispatch.
    """
    callee = call_site.callee

    # Direct match against known functions
    if callee in known_functions:
        return callee

    # Try module-qualified match
    # If callee is "func_name", try various qualified forms
    if "." not in callee:
        # Try caller.callee (for nested function calls like outer calling inner)
        candidate_nested = f"{call_site.caller}.{callee}"
        if candidate_nested in known_functions:
            return candidate_nested

        # Extract the module from the caller
        caller_parts = call_site.caller.rsplit(".", 1)
        if len(caller_parts) > 1:
            module = caller_parts[0]
            # Try sibling function: same module/class
            candidate = f"{module}.{callee}"
            if candidate in known_functions:
                return candidate
            # Try parent module
            module_parts = module.rsplit(".", 1)
            if len(module_parts) > 1:
                parent_candidate = f"{module_parts[0]}.{callee}"
                if parent_candidate in known_functions:
                    return parent_candidate

        # Try unique suffix match across all known functions
        # (cross-file resolution: compute_tax -> helpers.compute_tax)
        candidates = [f for f in known_functions if f.endswith(f".{callee}")]
        if len(candidates) == 1:
            return candidates[0]

    # Handle self.method() pattern - resolve within same class
    if call_site.is_method_call and callee.startswith("self."):
        method_name = callee[5:]  # strip "self."
        # The caller is like "module.ClassName.caller_method"
        caller_parts = call_site.caller.rsplit(".", 1)
        if len(caller_parts) > 1:
            class_prefix = caller_parts[0]
            candidate = f"{class_prefix}.{method_name}"
            if candidate in known_functions:
                return candidate

    # Try matching just the last segment against known function suffixes
    if "." in callee:
        # e.g., callee = "processor.validate" - try all known functions ending in ".validate"
        _, method = callee.rsplit(".", 1)
        candidates = [f for f in known_functions if f.endswith(f".{method}")]
        if len(candidates) == 1:
            return candidates[0]

    return None
