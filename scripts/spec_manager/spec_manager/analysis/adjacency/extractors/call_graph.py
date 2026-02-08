"""Call graph extractor using AST-based analysis of Python source files.

Walks the AST of each file, identifies function/method definitions,
and records call relationships between them.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


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
    """Build a call graph from Python source files.

    Walks AST of each file, identifies function/method definitions,
    and records call relationships between them.

    Args:
        source_paths: Python files to analyze
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
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        functions = _extract_functions(tree, path, root_dir)
        calls = _extract_calls(tree, path, root_dir)
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


def _extract_functions(tree: ast.Module, file_path: Path, root_dir: Path | None) -> list[NodeInfo]:
    """Extract all function/method definitions from an AST."""
    functions: list[NodeInfo] = []
    module = _module_prefix(file_path, root_dir)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Determine qualified name
            # Check if this function is inside a class
            qualified_name = _get_qualified_name(node, tree, module)
            functions.append(
                NodeInfo(
                    node_id=qualified_name,
                    node_type="async_function"
                    if isinstance(node, ast.AsyncFunctionDef)
                    else "function",
                    file_path=str(file_path),
                    line_number=node.lineno,
                    metadata={"module": module},
                )
            )

    return functions


def _get_qualified_name(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
    module: str,
) -> str:
    """Get a qualified name for a function node by walking the AST tree."""
    # Build a parent map
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node

    parts: list[str] = [func_node.name]
    current: ast.AST = func_node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            parts.insert(0, parent.name)
        current = parent

    return f"{module}.{'.'.join(parts)}"


def _extract_calls(tree: ast.Module, file_path: Path, root_dir: Path | None) -> list[CallSite]:
    """Extract all function call sites from an AST."""
    calls: list[CallSite] = []
    module = _module_prefix(file_path, root_dir)

    # Build a map: each Call node -> enclosing function name
    # Walk through the tree and track the current function scope
    _collect_calls_from_node(tree, tree, module, str(file_path), calls)

    return calls


def _collect_calls_from_node(
    node: ast.AST,
    tree: ast.Module,
    module: str,
    file_path: str,
    calls: list[CallSite],
    current_func: str | None = None,
) -> None:
    """Recursively collect call sites, tracking the enclosing function."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        func_name = _get_qualified_name(node, tree, module)
        for child in ast.iter_child_nodes(node):
            _collect_calls_from_node(child, tree, module, file_path, calls, func_name)
        return

    if isinstance(node, ast.Call) and current_func is not None:
        callee_name, is_method = _extract_callee_name(node)
        if callee_name is not None:
            calls.append(
                CallSite(
                    caller=current_func,
                    callee=callee_name,
                    file_path=file_path,
                    line_number=node.lineno,
                    is_method_call=is_method,
                )
            )

    for child in ast.iter_child_nodes(node):
        _collect_calls_from_node(child, tree, module, file_path, calls, current_func)


def _extract_callee_name(call_node: ast.Call) -> tuple[str | None, bool]:
    """Extract the callee name from a Call node.

    Returns (name, is_method_call).
    """
    func = call_node.func
    if isinstance(func, ast.Name):
        return func.id, False
    elif isinstance(func, ast.Attribute):
        # e.g., self.method(), obj.function(), module.func()
        attr_name = func.attr
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{attr_name}", True
        # Deeper chains like a.b.c() - just use the final attribute
        return attr_name, True
    return None, False


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
