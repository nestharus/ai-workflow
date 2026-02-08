"""Event graph extractor for detecting publish/subscribe coupling patterns.

Detects event publish and subscribe endpoints in Python source code
via AST analysis of method calls, decorators, and class inheritance.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..graph import AdjacencyGraph, EdgeSignal, NodeInfo, SignalType

# Configurable patterns for event detection
DEFAULT_PUBLISH_PATTERNS: list[str] = [
    "publish",
    "emit",
    "dispatch",
    "send_event",
    "fire",
    "bus.publish",
    "bus.emit",
    "event_bus.publish",
]

DEFAULT_SUBSCRIBE_PATTERNS: list[str] = [
    "subscribe",
    "on_event",
    "handle",
    "listen",
    "bus.subscribe",
    "bus.on",
    "event_bus.subscribe",
]

DEFAULT_DECORATOR_PATTERNS: list[str] = [
    "event_handler",
    "subscribe",
    "on",
    "handles",
]


@dataclass
class EventEndpoint:
    """A detected event publish or subscribe point."""

    function_name: str  # function/method containing the event interaction
    event_topic: str  # topic string if detectable, else "unknown"
    direction: str  # "publish" or "subscribe"
    file_path: str
    line_number: int


def extract_event_graph(
    source_paths: list[Path],
    root_dir: Path | None = None,
    publish_patterns: list[str] | None = None,
    subscribe_patterns: list[str] | None = None,
    decorator_patterns: list[str] | None = None,
) -> AdjacencyGraph:
    """Build an event graph from Python source files.

    Detects publish/subscribe patterns and creates edges between
    publishers and subscribers of the same topic.

    Args:
        source_paths: Python files to analyze
        root_dir: Project root for computing module-qualified names
        publish_patterns: Override default publish method name patterns
        subscribe_patterns: Override default subscribe method name patterns
        decorator_patterns: Override default decorator patterns

    Returns:
        AdjacencyGraph with SignalType.EVENT edges
    """
    pub_patterns = publish_patterns or DEFAULT_PUBLISH_PATTERNS
    sub_patterns = subscribe_patterns or DEFAULT_SUBSCRIBE_PATTERNS
    dec_patterns = decorator_patterns or DEFAULT_DECORATOR_PATTERNS

    all_endpoints: list[EventEndpoint] = []

    for path in source_paths:
        if not path.exists() or path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        endpoints = _detect_event_endpoints(
            tree, path, root_dir, pub_patterns, sub_patterns, dec_patterns
        )
        all_endpoints.extend(endpoints)

    # Match publishers to subscribers
    pairs = _match_publishers_to_subscribers(all_endpoints)

    # Build graph
    graph = AdjacencyGraph()

    # Add all endpoint functions as nodes
    for ep in all_endpoints:
        graph.add_node(
            ep.function_name,
            NodeInfo(
                node_id=ep.function_name,
                node_type="event_publisher" if ep.direction == "publish" else "event_subscriber",
                file_path=ep.file_path,
                line_number=ep.line_number,
                metadata={"event_topic": ep.event_topic, "direction": ep.direction},
            ),
        )

    # Add edges from publishers to subscribers
    for publisher, subscriber in pairs:
        weight = 0.8 if publisher.event_topic != "unknown" else 0.4
        graph.add_edge(
            publisher.function_name,
            subscriber.function_name,
            EdgeSignal(
                signal_type=SignalType.EVENT,
                weight=weight,
                details={
                    "event_topic": publisher.event_topic,
                    "publisher_file": publisher.file_path,
                    "subscriber_file": subscriber.file_path,
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


def _get_enclosing_function(
    node: ast.AST, parent_map: dict[int, ast.AST], module: str
) -> str | None:
    """Walk up the parent map to find the enclosing function/method name."""
    parts: list[str] = []
    current = node
    while id(current) in parent_map:
        parent = parent_map[id(current)]
        if isinstance(parent, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            parts.insert(0, parent.name)
        current = parent

    if parts:
        return f"{module}.{'.'.join(parts)}"
    return None


def _build_parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    """Build a mapping from child node id to parent node."""
    parent_map: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[id(child)] = node
    return parent_map


def _detect_event_endpoints(
    tree: ast.Module,
    file_path: Path,
    root_dir: Path | None,
    publish_patterns: list[str],
    subscribe_patterns: list[str],
    decorator_patterns: list[str],
) -> list[EventEndpoint]:
    """Detect publish/subscribe endpoints in an AST."""
    endpoints: list[EventEndpoint] = []
    module = _module_prefix(file_path, root_dir)
    parent_map = _build_parent_map(tree)

    # Detect method call patterns (publish/subscribe)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name is None:
                continue

            direction = None
            if _matches_pattern(call_name, publish_patterns):
                direction = "publish"
            elif _matches_pattern(call_name, subscribe_patterns):
                direction = "subscribe"

            if direction is not None:
                topic = _extract_topic_from_call(node) or "unknown"
                func_name = _get_enclosing_function(node, parent_map, module)
                if func_name is not None:
                    endpoints.append(
                        EventEndpoint(
                            function_name=func_name,
                            event_topic=topic,
                            direction=direction,
                            file_path=str(file_path),
                            line_number=node.lineno,
                        )
                    )

    # Detect decorator patterns (@event_handler("topic"), @subscribe("topic"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                dec_name = None
                topic = "unknown"

                if isinstance(decorator, ast.Call):
                    dec_name = _get_call_name_from_func(decorator.func)
                    topic = _extract_topic_from_call(decorator) or "unknown"
                elif isinstance(decorator, ast.Name):
                    dec_name = decorator.id
                elif isinstance(decorator, ast.Attribute):
                    dec_name = decorator.attr

                if dec_name is not None and _matches_pattern(dec_name, decorator_patterns):
                    # Get the qualified function name
                    qualified = _get_qualified_func_name(node, tree, module)
                    endpoints.append(
                        EventEndpoint(
                            function_name=qualified,
                            event_topic=topic,
                            direction="subscribe",
                            file_path=str(file_path),
                            line_number=node.lineno,
                        )
                    )

    return endpoints


def _get_call_name(call_node: ast.Call) -> str | None:
    """Extract the call name from a Call node."""
    return _get_call_name_from_func(call_node.func)


def _get_call_name_from_func(func: ast.expr) -> str | None:
    """Extract a name from a function expression (Name or Attribute)."""
    if isinstance(func, ast.Name):
        return func.id
    elif isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return f"{func.value.id}.{func.attr}"
        return func.attr
    return None


def _matches_pattern(name: str, patterns: list[str]) -> bool:
    """Check if a call name matches any of the given patterns.

    Handles both exact matches and suffix matches to avoid false positives
    on unrelated methods like book.publish().
    """
    name_lower = name.lower()
    for pattern in patterns:
        pattern_lower = pattern.lower()
        if name_lower == pattern_lower:
            return True
        # For dotted patterns like "bus.publish", match exactly
        if "." in pattern_lower and name_lower == pattern_lower:
            return True
        # For simple patterns like "publish", only match if it is a standalone
        # name or the method part of a dotted name where the object hints at events
        if "." not in pattern_lower:
            if name_lower == pattern_lower:
                return True
            # Match obj.publish only if obj looks event-related
            if "." in name_lower:
                obj, method = name_lower.rsplit(".", 1)
                if method == pattern_lower:
                    event_hints = {"bus", "event_bus", "events", "emitter", "dispatcher", "self"}
                    if obj in event_hints:
                        return True
    return False


def _extract_topic_from_call(call_node: ast.Call) -> str | None:
    """Extract topic string from the first argument of a publish/subscribe call.

    Handles string literals and simple string constants.
    Returns None if topic cannot be statically determined.
    """
    if not call_node.args:
        return None

    first_arg = call_node.args[0]

    # String literal
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value

    # Name reference to a constant (best-effort, return the name)
    if isinstance(first_arg, ast.Name):
        return f"${first_arg.id}"  # Mark as variable reference

    return None


def _get_qualified_func_name(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    tree: ast.Module,
    module: str,
) -> str:
    """Get a qualified name for a function node."""
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


def _match_publishers_to_subscribers(
    endpoints: list[EventEndpoint],
) -> list[tuple[EventEndpoint, EventEndpoint]]:
    """Match publisher endpoints to subscriber endpoints by topic.

    Returns pairs of (publisher, subscriber) that share the same topic.
    Endpoints with "unknown" topic are matched to ALL endpoints of the
    opposite direction as low-confidence edges.
    """
    publishers: list[EventEndpoint] = [e for e in endpoints if e.direction == "publish"]
    subscribers: list[EventEndpoint] = [e for e in endpoints if e.direction == "subscribe"]

    pairs: list[tuple[EventEndpoint, EventEndpoint]] = []

    # Group by topic
    pub_by_topic: dict[str, list[EventEndpoint]] = {}
    sub_by_topic: dict[str, list[EventEndpoint]] = {}

    for pub in publishers:
        pub_by_topic.setdefault(pub.event_topic, []).append(pub)
    for sub in subscribers:
        sub_by_topic.setdefault(sub.event_topic, []).append(sub)

    # Match known topics
    for topic, pubs in pub_by_topic.items():
        if topic == "unknown":
            continue
        subs = sub_by_topic.get(topic, [])
        for pub in pubs:
            for sub in subs:
                if pub.function_name != sub.function_name:
                    pairs.append((pub, sub))

    # Handle unknown topics: match to all opposite-direction endpoints
    unknown_pubs = pub_by_topic.get("unknown", [])
    unknown_subs = sub_by_topic.get("unknown", [])

    for pub in unknown_pubs:
        for sub in subscribers:
            if pub.function_name != sub.function_name:
                pairs.append((pub, sub))

    for sub in unknown_subs:
        for pub in publishers:
            if pub.function_name != sub.function_name and pub.event_topic != "unknown":
                # Avoid double-counting unknown-unknown pairs
                pairs.append((pub, sub))

    return pairs
