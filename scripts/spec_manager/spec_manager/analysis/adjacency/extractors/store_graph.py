"""Store touch graph extractor for detecting shared-store coupling.

Identifies which functions read/write which stores using language-agnostic
analysis of type hints and naming conventions. Two functions that touch the same
store receive an edge between them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import RawFunctionInfo, SourceAnalysis, analyze_source

from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType


class StoreType(Enum):
    """Store lifecycle classification per ALGORITHM.md 2.6."""

    PERSISTED = "type_a"  # DB, files -- survives restart
    LONG_LIVED = "type_b"  # In-memory across steps -- HIGH RISK
    EPHEMERAL = "type_c"  # Local/temporary within single step


class AccessMode(Enum):
    """How a function accesses a store."""

    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


@dataclass
class StoreTouch:
    """A detected store access by a function."""

    function_name: str
    store_name: str
    store_type: StoreType
    access_mode: AccessMode
    file_path: str
    line_number: int
    detection_method: str  # "type_hint", "naming_convention", "pin_annotation"


# Naming convention patterns for store access detection
READ_PATTERNS: list[str] = [
    "read_",
    "load_",
    "fetch_",
    "query_",
    "get_from_",
    "find_",
    "lookup_",
    "retrieve_",
    "dequeue_",
]

WRITE_PATTERNS: list[str] = [
    "write_",
    "save_",
    "persist_",
    "store_",
    "put_",
    "insert_",
    "update_",
    "delete_",
    "enqueue_",
    "push_",
]

STORE_TYPE_HINTS: list[str] = [
    "Store",
    "Repository",
    "Queue",
    "DB",
    "Session",
    "Connection",
    "Cache",
    "Registry",
    "Journal",
]

# Regex to extract parameter annotations from a signature line.
# Matches patterns like ``param_name: TypeName`` or ``param_name: Optional[TypeName]``
_PARAM_ANNOTATION_RE = re.compile(
    r"(\w+)\s*:\s*([A-Za-z_][\w\.\[\], |]*)",
)

# Regex to extract the "inner" type from generics like Optional[Store], list[Store]
_INNER_TYPE_RE = re.compile(r"\[([A-Za-z_]\w*)\]")


def extract_store_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
    pin_annotations: dict[str, str] | None = None,
) -> AdjacencyGraph:
    """Build a store touch graph from source files.

    Two functions that touch the same store get an edge between them.
    Store nodes are included in the graph as intermediate nodes.

    Args:
        source_paths: Source files to analyze
        root_dir: Project root for module-qualified names
        pin_annotations: Optional map of function_name -> store file path
            from (@pin path:symbol) annotations in spec content

    Returns:
        AdjacencyGraph with SignalType.STORE_TOUCH edges.
        Edges connect function pairs that share a store.
        Edge details include store_name, store_type, access_modes.
    """
    all_touches: list[StoreTouch] = []

    for path in source_paths:
        if not path.exists() or path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        try:
            analysis = analyze_source(source, filepath=str(path))
        except Exception:  # noqa: S112 — best-effort scan; unparseable files are skipped
            continue

        touches = _detect_store_touches(analysis, source, path, root_dir)
        all_touches.extend(touches)

    # Add pin annotation touches
    if pin_annotations:
        for func_name, store_path in pin_annotations.items():
            store_name = Path(store_path).stem
            all_touches.append(
                StoreTouch(
                    function_name=func_name,
                    store_name=store_name,
                    store_type=_classify_store_type(store_name),
                    access_mode=AccessMode.READ_WRITE,
                    file_path="",
                    line_number=0,
                    detection_method="pin_annotation",
                )
            )

    return _build_store_adjacency(all_touches)


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


def _qualified_func_name(
    func: RawFunctionInfo,
    module: str,
) -> str:
    """Compute a fully qualified name: module.qualified_name.

    The ``qualified_name`` from ``RawFunctionInfo`` already includes
    class nesting (e.g. ``ClassName.method``).  We prepend the module
    prefix to match the behaviour of the previous AST-based implementation.
    """
    return f"{module}.{func.qualified_name}"


def _extract_signature_text(
    func: RawFunctionInfo,
    source_lines: list[str],
) -> str:
    """Extract the full def-signature text for a function (up to the colon).

    Handles multi-line signatures by collecting lines from start_line until
    we find the closing parenthesis.
    """
    sig_parts: list[str] = []
    for i in range(func.start_line - 1, min(func.end_line, len(source_lines))):
        sig_parts.append(source_lines[i])
        if ")" in source_lines[i]:
            break
    return " ".join(sig_parts)


def _extract_param_annotations(sig_text: str) -> list[tuple[str, str]]:
    """Extract (param_name, type_annotation) pairs from a signature string.

    Returns a list of (param_name, annotation_text) tuples.
    Skips ``self`` and ``cls``.
    """
    # Isolate the parameters portion between the first '(' and matching ')'
    paren_match = re.search(r"\(([^)]*)\)", sig_text)
    if not paren_match:
        return []

    params_text = paren_match.group(1)
    results: list[tuple[str, str]] = []
    for match in _PARAM_ANNOTATION_RE.finditer(params_text):
        param_name = match.group(1)
        annotation = match.group(2).strip().rstrip(",")
        if param_name in ("self", "cls"):
            continue
        results.append((param_name, annotation))
    return results


def _extract_type_name_from_annotation(annotation: str) -> str | None:
    """Extract the core type name from an annotation string.

    Handles simple types (``Store``), qualified (``db.Store``),
    and generic wrappers (``Optional[Store]``, ``list[Store]``).
    """
    annotation = annotation.strip()
    if not annotation:
        return None

    # Check for generic wrappers: Optional[Store], list[Store], etc.
    inner = _INNER_TYPE_RE.search(annotation)
    if inner:
        return inner.group(1)

    # Check for dotted access: db.Store -> Store
    if "." in annotation:
        return annotation.rsplit(".", 1)[-1]

    # Simple type name
    # Strip any remaining brackets or whitespace
    clean = annotation.split("[")[0].split("|")[0].strip()
    if clean and clean[0].isalpha():
        return clean
    return None


def _detect_store_touches(
    analysis: SourceAnalysis,
    source: str,
    file_path: Path,
    root_dir: Path | None,
) -> list[StoreTouch]:
    """Detect store accesses via type hints and naming conventions."""
    touches: list[StoreTouch] = []
    module = _module_prefix(file_path, root_dir)
    source_lines = source.splitlines()

    for func in analysis.functions:
        func_name = _qualified_func_name(func, module)

        # Detection method 1: Type hints in parameters
        sig_text = _extract_signature_text(func, source_lines)
        param_annotations = _extract_param_annotations(sig_text)
        for param_name, annotation_text in param_annotations:
            type_name = _extract_type_name_from_annotation(annotation_text)
            if type_name and _is_store_type(type_name):
                store_name = _derive_store_name_from_type(type_name, param_name)
                touches.append(
                    StoreTouch(
                        function_name=func_name,
                        store_name=store_name,
                        store_type=_classify_store_type(store_name),
                        access_mode=AccessMode.READ_WRITE,
                        file_path=str(file_path),
                        line_number=func.start_line,
                        detection_method="type_hint",
                    )
                )

        # Detection method 2: Return type annotation containing store types
        if func.return_annotation:
            type_name = _extract_type_name_from_annotation(func.return_annotation)
            if type_name and _is_store_type(type_name):
                store_name = _derive_store_name_from_type(type_name, "return")
                touches.append(
                    StoreTouch(
                        function_name=func_name,
                        store_name=store_name,
                        store_type=_classify_store_type(store_name),
                        access_mode=AccessMode.READ,
                        file_path=str(file_path),
                        line_number=func.start_line,
                        detection_method="type_hint",
                    )
                )

        # Detection method 3: Function naming conventions
        bare_name = func.name
        access_mode = None
        store_name_from_naming = None

        for pattern in READ_PATTERNS:
            if bare_name.startswith(pattern):
                access_mode = AccessMode.READ
                store_name_from_naming = bare_name[len(pattern) :]
                break

        if access_mode is None:
            for pattern in WRITE_PATTERNS:
                if bare_name.startswith(pattern):
                    access_mode = AccessMode.WRITE
                    store_name_from_naming = bare_name[len(pattern) :]
                    break

        if access_mode is not None and store_name_from_naming:
            # Normalize the store name (strip trailing underscores, plurals)
            store_name_from_naming = store_name_from_naming.rstrip("_")
            if store_name_from_naming:
                touches.append(
                    StoreTouch(
                        function_name=func_name,
                        store_name=store_name_from_naming,
                        store_type=_classify_store_type(store_name_from_naming),
                        access_mode=access_mode,
                        file_path=str(file_path),
                        line_number=func.start_line,
                        detection_method="naming_convention",
                    )
                )

    return touches


def _is_store_type(type_name: str) -> bool:
    """Check if a type name indicates a store."""
    return any(hint.lower() in type_name.lower() for hint in STORE_TYPE_HINTS)


def _derive_store_name_from_type(type_name: str, param_name: str) -> str:
    """Derive a canonical store name from type and parameter name."""
    # Use the parameter name if it is descriptive, otherwise the type name
    if param_name not in ("self", "cls", "return", "db", "session", "conn"):
        return param_name
    return type_name.lower()


def _classify_store_type(store_name: str, context_hints: dict[str, Any] | None = None) -> StoreType:
    """Classify a store into Type A/B/C based on naming and context.

    Heuristic:
    - Names containing 'db', 'sql', 'file', 'disk', 'persist' -> PERSISTED
    - Names containing 'cache', 'session', 'state' -> LONG_LIVED
    - Names containing 'temp', 'local', 'buffer' -> EPHEMERAL
    - Default: PERSISTED (conservative -- assume worst case)
    """
    name_lower = store_name.lower()

    ephemeral_hints = ["temp", "local", "buffer", "tmp", "scratch"]
    for hint in ephemeral_hints:
        if hint in name_lower:
            return StoreType.EPHEMERAL

    long_lived_hints = ["cache", "session", "state", "memory", "memo"]
    for hint in long_lived_hints:
        if hint in name_lower:
            return StoreType.LONG_LIVED

    # Default: PERSISTED (conservative)
    return StoreType.PERSISTED


def _build_store_adjacency(
    touches: list[StoreTouch],
) -> AdjacencyGraph:
    """Convert store touches into function-to-function edges.

    For each store S:
      For each pair (f1, f2) that both touch S:
        Add edge f1 <-> f2 with SignalType.STORE_TOUCH
        Edge details include store_name, store_type, access modes
    """
    graph = AdjacencyGraph()

    # Group touches by store name
    by_store: dict[str, list[StoreTouch]] = {}
    for touch in touches:
        by_store.setdefault(touch.store_name, []).append(touch)

    # Add store nodes
    for store_name, store_touches in by_store.items():
        store_type = store_touches[0].store_type
        graph.add_node(
            f"store:{store_name}",
            NodeInfo(
                node_id=f"store:{store_name}",
                node_type="store",
                metadata={"store_type": store_type.value},
            ),
        )

    # For each store, create edges between all function pairs that touch it
    for store_name, store_touches in by_store.items():
        # Get unique functions touching this store
        functions = list({t.function_name for t in store_touches})

        # Also add function nodes
        for touch in store_touches:
            graph.add_node(
                touch.function_name,
                NodeInfo(
                    node_id=touch.function_name,
                    node_type="function",
                    file_path=touch.file_path,
                    line_number=touch.line_number,
                ),
            )

        # Create edges between all pairs
        for i, f1 in enumerate(functions):
            for f2 in functions[i + 1 :]:
                # Get access modes for both functions
                f1_modes = {t.access_mode.value for t in store_touches if t.function_name == f1}
                f2_modes = {t.access_mode.value for t in store_touches if t.function_name == f2}

                store_type = store_touches[0].store_type

                graph.add_edge(
                    f1,
                    f2,
                    EdgeSignal(
                        signal_type=SignalType.STORE_TOUCH,
                        weight=0.5,
                        details={
                            "store_name": store_name,
                            "store_type": store_type.value,
                            "f1_access": sorted(f1_modes),
                            "f2_access": sorted(f2_modes),
                        },
                    ),
                )
                # Add reverse edge for undirected semantics
                graph.add_edge(
                    f2,
                    f1,
                    EdgeSignal(
                        signal_type=SignalType.STORE_TOUCH,
                        weight=0.5,
                        details={
                            "store_name": store_name,
                            "store_type": store_type.value,
                            "f1_access": sorted(f2_modes),
                            "f2_access": sorted(f1_modes),
                        },
                    ),
                )

    return graph
