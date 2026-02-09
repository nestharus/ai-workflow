"""Event graph extractor for detecting publish/subscribe coupling patterns.

Detects event publish and subscribe endpoints in source code
via regex analysis of method calls, decorators, and class inheritance.
Language-agnostic: uses analyze_source for structural info and regex for
call-site detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from spec_manager.core.code_analysis import RawFunctionInfo, SourceAnalysis, analyze_source

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

# Regex to match a method/function call: captures `obj.method(` or `func(`
# Group 1 = full call name (e.g. "self.bus.publish" or "emit")
_CALL_RE = re.compile(r"(?<![.\w])(\w+(?:\.\w+)*)\s*\(")

# Regex to extract the first string argument from a call:
#   name(  "topic"  or  name(  'topic'
_TOPIC_RE = re.compile(
    r"(?<![.\w])(\w+(?:\.\w+)*)\s*\(\s*"
    r"""(?:["']([^"']+)["']|(\w+))"""
)

# Regex to detect decorator lines with optional call syntax:
#   @event_handler("topic")  or  @subscribe  or  @bus.on("topic")
_DECORATOR_RE = re.compile(
    r"@(\w+(?:\.\w+)*)"
    r"(?:\s*\(\s*"
    r"""(?:["']([^"']+)["']|(\w+))"""
    r"\s*\))?"
)


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
    """Build an event graph from source files.

    Detects publish/subscribe patterns and creates edges between
    publishers and subscribers of the same topic.

    Args:
        source_paths: Source files to analyze
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
        except (OSError, UnicodeDecodeError):
            continue

        analysis = analyze_source(source, filepath=str(path))

        # If analysis returned no functions, skip (likely a parse error or empty file)
        if not analysis.functions and not source.strip():
            continue

        endpoints = _detect_event_endpoints(
            source, analysis, path, root_dir, pub_patterns, sub_patterns, dec_patterns
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


def _find_enclosing_function(
    line_number: int,
    functions: list[RawFunctionInfo],
    module: str,
) -> str | None:
    """Find the innermost function enclosing a given line number.

    Uses function start_line/end_line ranges from SourceAnalysis.
    Returns the qualified_name prefixed with the module, or None if the
    line is not inside any function.
    """
    best: RawFunctionInfo | None = None
    for func in functions:
        if func.start_line <= line_number <= func.end_line and (
            best is None or (func.end_line - func.start_line) < (best.end_line - best.start_line)
        ):
            best = func
    if best is not None:
        return f"{module}.{best.qualified_name}"
    return None


def _call_name_candidates(call_name: str) -> list[str]:
    """Generate candidate call names for pattern matching.

    For multi-segment dotted names (e.g. ``self.bus.publish``), returns
    the full name plus progressively shorter suffixes so that pattern
    matching works the same way as the old AST extractor which only saw
    at most two segments (``obj.method`` or just ``method``).

    Returns candidates from most-specific to least-specific:
        "self.bus.publish" -> ["self.bus.publish", "bus.publish", "publish"]
        "bus.publish"      -> ["bus.publish"]
        "publish"          -> ["publish"]
    """
    parts = call_name.split(".")
    if len(parts) <= 2:
        return [call_name]
    # For 3+ segment names, produce all 2-segment and 1-segment suffixes
    candidates: list[str] = [call_name]
    for i in range(1, len(parts)):
        candidates.append(".".join(parts[i:]))
    return candidates


def _detect_event_endpoints(
    source: str,
    analysis: SourceAnalysis,
    file_path: Path,
    root_dir: Path | None,
    publish_patterns: list[str],
    subscribe_patterns: list[str],
    decorator_patterns: list[str],
) -> list[EventEndpoint]:
    """Detect publish/subscribe endpoints in source text using regex."""
    endpoints: list[EventEndpoint] = []
    module = _module_prefix(file_path, root_dir)
    lines = source.splitlines()

    # Detect method call patterns (publish/subscribe) line by line
    for line_idx, line_text in enumerate(lines, start=1):
        # Skip comment-only lines
        stripped = line_text.lstrip()
        if stripped.startswith("#"):
            continue

        for match in _CALL_RE.finditer(line_text):
            full_call_name = match.group(1)

            # Normalize multi-segment names to mimic AST behaviour:
            # self.bus.publish -> try "self.bus.publish", "bus.publish", "publish"
            candidates = _call_name_candidates(full_call_name)

            direction = None
            for candidate in candidates:
                if _matches_pattern(candidate, publish_patterns):
                    direction = "publish"
                    break
                if _matches_pattern(candidate, subscribe_patterns):
                    direction = "subscribe"
                    break

            if direction is not None:
                # Always use the full call name for topic extraction since
                # that is what appears in the source text
                topic = _extract_topic_from_line(line_text, full_call_name) or "unknown"
                func_name = _find_enclosing_function(line_idx, analysis.functions, module)
                if func_name is not None:
                    endpoints.append(
                        EventEndpoint(
                            function_name=func_name,
                            event_topic=topic,
                            direction=direction,
                            file_path=str(file_path),
                            line_number=line_idx,
                        )
                    )

    # Detect decorator patterns (@event_handler("topic"), @subscribe("topic"))
    for func in analysis.functions:
        for decorator in func.decorators:
            # The decorator string from analysis is just the name
            # (e.g. "event_handler"), without call arguments.
            # We need to check if it matches a pattern, then scan the
            # source lines near the function to extract the topic.
            dec_name = decorator

            if not _matches_pattern(dec_name, decorator_patterns):
                continue

            # Scan source lines near start_line to find decorator with topic
            topic = "unknown"
            # Look up to 5 lines before start_line for the @decorator line
            search_start = max(0, func.start_line - 6)  # 0-indexed
            search_end = func.start_line  # exclusive, 0-indexed
            for src_line in lines[search_start:search_end]:
                dec_match = _DECORATOR_RE.search(src_line)
                if dec_match and dec_match.group(1) == dec_name:
                    if dec_match.group(2):
                        topic = dec_match.group(2)
                    elif dec_match.group(3):
                        topic = f"${dec_match.group(3)}"
                    break

            qualified = f"{module}.{func.qualified_name}"
            endpoints.append(
                EventEndpoint(
                    function_name=qualified,
                    event_topic=topic,
                    direction="subscribe",
                    file_path=str(file_path),
                    line_number=func.start_line,
                )
            )

    return endpoints


def _extract_topic_from_line(line_text: str, call_name: str) -> str | None:
    """Extract topic string from the first argument of a call on a line.

    Looks for the call_name followed by a parenthesized string or variable.
    Returns None if topic cannot be statically determined.
    """
    # Build a regex specific to this call_name
    # Escape dots in the call_name for regex
    escaped = re.escape(call_name)
    pattern = r"(?<![.\w])" + escaped + r"\s*\(\s*" + r"""(?:["']([^"']+)["']|(\w+))"""
    match = re.search(pattern, line_text)
    if match:
        # String literal topic
        if match.group(1):
            return match.group(1)
        # Variable reference
        if match.group(2):
            return f"${match.group(2)}"
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
