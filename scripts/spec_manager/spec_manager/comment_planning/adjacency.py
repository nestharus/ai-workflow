"""Adjacent-detail discovery from canonical relationship evidence.

After adding new pseudocode comments, this module reveals functions that
interact with the modified function via call relationships, shared stores,
or shared events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from spec_manager.comment_planning.models import AdjacentDetail, CodeFile

logger = logging.getLogger(__name__)

# Heuristic patterns for store-touch detection
_DB_PATTERNS = frozenset(
    {
        "execute",
        "executemany",
        "fetchone",
        "fetchall",
        "fetchmany",
        "commit",
        "rollback",
        "query",
        "add",
        "delete",
        "merge",
        "flush",
        "bulk_save_objects",
        "bulk_insert_mappings",
        "bulk_update_mappings",
    }
)

_FILE_PATTERNS = frozenset(
    {
        "open",
        "read",
        "write",
        "read_text",
        "write_text",
        "read_bytes",
        "write_bytes",
        "readlines",
        "writelines",
    }
)

_QUEUE_PATTERNS = frozenset(
    {
        "put",
        "get",
        "put_nowait",
        "get_nowait",
        "send",
        "receive",
        "publish",
        "subscribe",
        "enqueue",
        "dequeue",
        "push",
        "pop",
        "lpush",
        "rpush",
        "lpop",
        "rpop",
    }
)

_EVENT_PATTERNS = frozenset(
    {
        "emit",
        "dispatch",
        "fire",
        "trigger",
        "on",
        "listen",
        "subscribe",
        "notify",
        "signal",
    }
)


@dataclass
class StoreTouchEdge:
    """A function's access to a shared store."""

    function_name: str
    store_name: str  # Inferred store identifier
    access_type: str | None  # "read", "write", "read_write" (None = unknown)
    line_no: int | None
    file_path: str


@dataclass
class CallGraph:
    """Directed graph of function calls."""

    nodes: set[str] = field(default_factory=set)  # Qualified function names
    edges: list[tuple[str, str]] = field(default_factory=list)  # (caller, callee)
    reverse_edges: dict[str, set[str]] = field(default_factory=dict)  # callee -> set of callers

    def callees(self, function: str) -> set[str]:
        """Get direct callees of a function.

        Args:
            function: Qualified function name.

        Returns:
            Set of functions called by the given function.
        """
        return {callee for caller, callee in self.edges if caller == function}

    def callers(self, function: str) -> set[str]:
        """Get direct callers of a function.

        Args:
            function: Qualified function name.

        Returns:
            Set of functions that call the given function.
        """
        return self.reverse_edges.get(function, set())

    def transitive_callees(self, function: str, depth: int = 3) -> set[str]:
        """Get transitive callees up to a depth limit.

        Args:
            function: Starting function.
            depth: Maximum traversal depth.

        Returns:
            Set of all transitively called functions within depth.
        """
        result: set[str] = set()
        frontier = {function}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for f in frontier:
                callees = self.callees(f)
                new_callees = callees - result - {function}
                result.update(new_callees)
                next_frontier.update(new_callees)
            frontier = next_frontier
            if not frontier:
                break
        return result

    def transitive_callers(self, function: str, depth: int = 3) -> set[str]:
        """Get transitive callers up to a depth limit.

        Args:
            function: Starting function.
            depth: Maximum traversal depth.

        Returns:
            Set of all functions that transitively call the given function.
        """
        result: set[str] = set()
        frontier = {function}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for f in frontier:
                callers = self.callers(f)
                new_callers = callers - result - {function}
                result.update(new_callers)
                next_frontier.update(new_callers)
            frontier = next_frontier
            if not frontier:
                break
        return result


def _normalize_signal_type(edge: dict[str, object]) -> str:
    """Normalize relationship signal labels."""
    signal = str(edge.get("signal_type") or edge.get("type") or "").strip().upper()
    if signal in {"CALL", "CALLS"}:
        return "CALL"
    if signal in {"STORE_TOUCH", "AGGREGATION"}:
        return "STORE_TOUCH"
    if signal in {"EVENT", "EVENT_PUBLISH", "EVENT_SUBSCRIBE"}:
        return "EVENT"
    return ""


def _relationship_endpoints(edge: dict[str, object]) -> tuple[str, str]:
    """Return canonical (src, dst) identifiers from relationship payload."""
    src = str(edge.get("src") or edge.get("src_id") or edge.get("pin_func_id") or "").strip()
    dst = str(
        edge.get("dst")
        or edge.get("dst_id")
        or edge.get("store_id")
        or edge.get("arch_location")
        or ""
    ).strip()
    return src, dst


def build_call_graph_from_relationship_edges(
    relationship_edges: list[dict[str, object]],
) -> CallGraph:
    """Build call graph from canonical relationship edges."""
    graph = CallGraph()
    for edge in relationship_edges:
        if not isinstance(edge, dict):
            continue
        if _normalize_signal_type(edge) != "CALL":
            continue
        src, dst = _relationship_endpoints(edge)
        if not src or not dst or src == dst:
            continue
        graph.nodes.add(src)
        graph.nodes.add(dst)
        graph.edges.append((src, dst))
        graph.reverse_edges.setdefault(dst, set()).add(src)
    return graph


def find_store_touches_from_relationship_edges(
    relationship_edges: list[dict[str, object]],
) -> list[StoreTouchEdge]:
    """Build store-touch edges from canonical relationship edges."""
    touches: list[StoreTouchEdge] = []
    for edge in relationship_edges:
        if not isinstance(edge, dict):
            continue
        if _normalize_signal_type(edge) != "STORE_TOUCH":
            continue
        src, dst = _relationship_endpoints(edge)
        if not src or not dst:
            continue
        operation = str(edge.get("operation") or "").strip().lower()
        access_type: str | None
        if operation in {"read", "write", "read_write"}:
            access_type = operation
        else:
            access_type = None
            logger.warning(
                "STORE_TOUCH edge for %s -> %s has unknown operation: %r",
                src,
                dst,
                edge.get("operation"),
            )

        line_no_raw = edge.get("line") or edge.get("line_no") or edge.get("arch_line")
        line_no: int | None = None
        if line_no_raw not in (None, ""):
            try:
                parsed_line = int(line_no_raw)
                if parsed_line > 0:
                    line_no = parsed_line
                else:
                    logger.warning(
                        "STORE_TOUCH edge for %s -> %s has non-positive line metadata: %r",
                        src,
                        dst,
                        line_no_raw,
                    )
            except (TypeError, ValueError):
                logger.warning(
                    "STORE_TOUCH edge for %s -> %s has invalid line metadata: %r",
                    src,
                    dst,
                    line_no_raw,
                )
        touches.append(
            StoreTouchEdge(
                function_name=src,
                store_name=dst,
                access_type=access_type,
                line_no=line_no,
                file_path=str(edge.get("file_path") or edge.get("arch_file_path") or ""),
            )
        )
    return touches


def discover_adjacent_details_from_relationship_edges(
    modified_function: str,
    relationship_edges: list[dict[str, object]],
    test_coverage: dict[str, bool | None] | None = None,
) -> list[AdjacentDetail]:
    """Discover adjacencies by consuming canonical relationship evidence."""
    call_graph = build_call_graph_from_relationship_edges(relationship_edges)
    store_touches = find_store_touches_from_relationship_edges(relationship_edges)
    return discover_adjacent_details(modified_function, call_graph, store_touches, test_coverage)


def build_call_graph(code_files: list[CodeFile]) -> CallGraph:
    """Build a call graph from parsed code files.

    Legacy fallback path for local standalone tooling. Workflow orchestration
    should prefer ``build_call_graph_from_relationship_edges``.

    Nodes are function names (qualified: module.class.function or module.function).
    Edges are call relationships extracted from AST.

    Args:
        code_files: List of parsed CodeFile objects.

    Returns:
        CallGraph with nodes, edges, and reverse_edges.
    """
    graph = CallGraph()

    # Build a map of simple name -> qualified name for resolution
    name_map: dict[str, list[str]] = {}

    for code_file in code_files:
        module = module_name_from_path(code_file.file_path)
        for func in code_file.functions:
            if func.class_name:
                qualified = f"{module}.{func.class_name}.{func.name}"
            else:
                qualified = f"{module}.{func.name}"
            graph.nodes.add(qualified)
            name_map.setdefault(func.name, []).append(qualified)

    # Build edges
    for code_file in code_files:
        module = module_name_from_path(code_file.file_path)
        for func in code_file.functions:
            if func.class_name:
                caller = f"{module}.{func.class_name}.{func.name}"
            else:
                caller = f"{module}.{func.name}"

            for call_name in func.calls or []:
                # Try to resolve to qualified name
                candidates = name_map.get(call_name, [])
                if len(candidates) == 1:
                    callee = candidates[0]
                elif candidates:
                    # Prefer same module
                    same_module = [c for c in candidates if c.startswith(module + ".")]
                    callee = same_module[0] if same_module else candidates[0]
                else:
                    # External call - use simple name
                    callee = call_name

                if caller != callee:  # No self-loops
                    graph.edges.append((caller, callee))
                    graph.reverse_edges.setdefault(callee, set()).add(caller)

    return graph


def find_store_touches(code_files: list[CodeFile]) -> list[StoreTouchEdge]:
    """Detect store access patterns (database calls, file I/O, queue operations).

    Legacy fallback path for local standalone tooling. Workflow orchestration
    should prefer ``find_store_touches_from_relationship_edges``.

    Identifies functions that read/write shared state.
    Two functions touching the same store are adjacent even if they never call each other.

    Args:
        code_files: List of parsed CodeFile objects.

    Returns:
        List of StoreTouchEdge objects.
    """
    touches: list[StoreTouchEdge] = []

    for code_file in code_files:
        module = module_name_from_path(code_file.file_path)
        for func in code_file.functions:
            if func.class_name:
                qualified = f"{module}.{func.class_name}.{func.name}"
            else:
                qualified = f"{module}.{func.name}"

            for call_name in func.calls or []:
                touch = _classify_store_touch(call_name)
                if touch is not None:
                    store_name, access_type = touch
                    touches.append(
                        StoreTouchEdge(
                            function_name=qualified,
                            store_name=store_name,
                            access_type=access_type,
                            line_no=func.start_line,
                            file_path=code_file.file_path,
                        )
                    )

    return touches


def _classify_store_touch(call_name: str) -> tuple[str, str] | None:
    """Classify a function call as a store touch.

    Args:
        call_name: The function/method name being called.

    Returns:
        (store_name, access_type) tuple, or None if not a store touch.
    """
    lower = call_name.lower()

    # Database operations
    if lower in _DB_PATTERNS:
        if lower in {"fetchone", "fetchall", "fetchmany", "query"}:
            return ("database", "read")
        if lower in {"commit", "flush"}:
            return ("database", "write")
        return ("database", "read_write")

    # File operations
    if lower in _FILE_PATTERNS:
        if lower in {"read", "read_text", "read_bytes", "readlines"}:
            return ("filesystem", "read")
        if lower in {"write", "write_text", "write_bytes", "writelines"}:
            return ("filesystem", "write")
        if lower == "open":
            return ("filesystem", "read_write")
        return ("filesystem", "read_write")

    # Queue operations
    if lower in _QUEUE_PATTERNS:
        if lower in {"get", "get_nowait", "receive", "dequeue", "pop", "lpop", "rpop"}:
            return ("queue", "read")
        if lower in {"put", "put_nowait", "send", "publish", "enqueue", "push", "lpush", "rpush"}:
            return ("queue", "write")
        return ("queue", "read_write")

    # Event operations
    if lower in _EVENT_PATTERNS:
        if lower in {"on", "listen", "subscribe"}:
            return ("event_bus", "read")
        if lower in {"emit", "dispatch", "fire", "trigger", "notify", "signal"}:
            return ("event_bus", "write")
        return ("event_bus", "read_write")

    return None


def discover_adjacent_details(
    modified_function: str,
    call_graph: CallGraph,
    store_touches: list[StoreTouchEdge],
    test_coverage: dict[str, bool | None] | None = None,
) -> list[AdjacentDetail]:
    """Discover adjacent details that interact with the modified function.

    After adding new comments, this reveals:
    1. Functions called by the modified function (downstream impact)
    2. Functions that call the modified function (upstream impact)
    3. Functions sharing stores with the modified function (hidden coupling)
    4. Functions sharing events with the modified function (event coupling)

    For each adjacent detail, checks test coverage. Anything touched
    that lacks test coverage is flagged as needing its own plan.

    Args:
        modified_function: Qualified name of the modified function.
        call_graph: Built call graph.
        store_touches: List of store touch edges.
        test_coverage: Optional dict of function_name -> has_tests.
            When missing, has_test_coverage is None (unknown).

    Returns:
        List of AdjacentDetail objects.
    """
    adjacencies: list[AdjacentDetail] = []
    seen: set[str] = set()

    # 1. Downstream: functions called by the modified function
    for callee in call_graph.callees(modified_function):
        if callee not in seen:
            seen.add(callee)
            has_tests = _coverage_state(test_coverage, callee)
            adjacencies.append(
                AdjacentDetail(
                    source_function=modified_function,
                    related_function=callee,
                    relationship="calls",
                    store_or_event=None,
                    has_test_coverage=has_tests,
                    needs_plan=has_tests is not True,
                )
            )

    # 2. Upstream: functions that call the modified function
    for caller in call_graph.callers(modified_function):
        if caller not in seen:
            seen.add(caller)
            has_tests = _coverage_state(test_coverage, caller)
            adjacencies.append(
                AdjacentDetail(
                    source_function=modified_function,
                    related_function=caller,
                    relationship="called_by",
                    store_or_event=None,
                    has_test_coverage=has_tests,
                    needs_plan=has_tests is not True,
                )
            )

    # 3. Shared stores and events
    # Find stores the modified function touches
    modified_stores: set[str] = set()
    for touch in store_touches:
        if touch.function_name == modified_function:
            modified_stores.add(touch.store_name)

    # Find other functions touching the same stores
    for touch in store_touches:
        if touch.function_name == modified_function:
            continue
        if touch.store_name in modified_stores and touch.function_name not in seen:
            seen.add(touch.function_name)
            has_tests = _coverage_state(test_coverage, touch.function_name)
            relationship = "shared_event" if touch.store_name == "event_bus" else "shared_store"
            adjacencies.append(
                AdjacentDetail(
                    source_function=modified_function,
                    related_function=touch.function_name,
                    relationship=relationship,
                    store_or_event=touch.store_name,
                    has_test_coverage=has_tests,
                    needs_plan=has_tests is not True,
                )
            )

    return adjacencies


def _coverage_state(
    test_coverage: dict[str, bool | None] | None,
    function_name: str,
) -> bool | None:
    """Return tri-state coverage (True/False/None)."""
    if test_coverage is None or function_name not in test_coverage:
        return None
    value = test_coverage.get(function_name)
    if isinstance(value, bool):
        return value
    return None


def module_name_from_path(file_path: str) -> str:
    """Extract a module-like name from a file path.

    Args:
        file_path: Path to a Python file.

    Returns:
        A dot-separated module-like name.
    """
    from pathlib import Path as P

    p = P(file_path)
    name = p.stem
    # Use parent directory name if it looks like a package
    parent = p.parent.name
    if parent and parent != ".":
        return f"{parent}.{name}"
    return name
