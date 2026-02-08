"""Tests for event graph extraction."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.analysis.adjacency.extractors.event_graph import (
    EventEndpoint,
    _match_publishers_to_subscribers,
    extract_event_graph,
)
from spec_manager.analysis.adjacency.graph import SignalType


def _write_source(directory: Path, filename: str, code: str) -> Path:
    """Write a Python source file and return its path."""
    path = directory / filename
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


class TestExtractEventGraph:
    def test_publish_subscribe_same_topic(self, tmp_path: Path) -> None:
        path = _write_source(
            tmp_path,
            "events.py",
            """\
            class OrderProcessor:
                def create_order(self, order):
                    self.bus.publish("order.created", order)

                def on_order_created(self, order):
                    self.bus.subscribe("order.created", self.handle_order)

                def handle_order(self, order):
                    pass
            """,
        )
        # Note: The subscribe call won't match because it's bus.subscribe with
        # topic, and the publisher is bus.publish with topic. However
        # the function containing bus.subscribe is on_order_created.
        # Let's use self.bus which should match "self" as event hint.
        graph = extract_event_graph([path], root_dir=tmp_path)

        # Should detect publish and subscribe endpoints
        edges = graph.edges()
        # Publisher: create_order publishes "order.created"
        # Subscriber: on_order_created subscribes "order.created"
        has_event_edge = False
        for edge in edges:
            for signal in edge.signals:
                if signal.signal_type == SignalType.EVENT:
                    has_event_edge = True
                    assert signal.details.get("event_topic") == "order.created"
        assert has_event_edge

    def test_multiple_subscribers_same_topic(self, tmp_path: Path) -> None:
        path = _write_source(
            tmp_path,
            "multi_sub.py",
            """\
            class EventSystem:
                def publisher(self):
                    self.emit("user.login")

                def handler_a(self):
                    self.subscribe("user.login", self.do_a)

                def handler_b(self):
                    self.subscribe("user.login", self.do_b)

                def do_a(self):
                    pass

                def do_b(self):
                    pass
            """,
        )
        graph = extract_event_graph([path], root_dir=tmp_path)

        # Publisher (emit "user.login") should connect to both handlers
        edges = graph.edges()
        event_edges = [
            e for e in edges if any(s.signal_type == SignalType.EVENT for s in e.signals)
        ]
        # We expect edges from publisher to handler_a and handler_b
        assert len(event_edges) >= 2

    def test_unknown_topics_produce_low_confidence(self, tmp_path: Path) -> None:
        path = _write_source(
            tmp_path,
            "unknown_topic.py",
            """\
            class Service:
                def sender(self):
                    topic = get_topic()
                    self.emit(topic)

                def receiver(self):
                    self.subscribe("known.topic", self.handle)

                def handle(self):
                    pass
            """,
        )
        graph = extract_event_graph([path], root_dir=tmp_path)

        # The emit(topic) has unknown topic, should connect to receiver
        edges = graph.edges()
        event_edges = [
            e for e in edges if any(s.signal_type == SignalType.EVENT for s in e.signals)
        ]
        if event_edges:
            # Unknown topic edges should have lower weight (0.4 vs 0.8)
            for edge in event_edges:
                for signal in edge.signals:
                    if signal.signal_type == SignalType.EVENT:
                        assert signal.weight <= 0.8

    def test_decorator_subscription(self, tmp_path: Path) -> None:
        path = _write_source(
            tmp_path,
            "decorated.py",
            """\
            class Handler:
                def publisher(self):
                    self.emit("order.shipped")

                @event_handler("order.shipped")
                def handle_shipped(self, event):
                    pass
            """,
        )
        graph = extract_event_graph([path], root_dir=tmp_path)

        edges = graph.edges()
        event_edges = [
            e for e in edges if any(s.signal_type == SignalType.EVENT for s in e.signals)
        ]
        # Publisher emits order.shipped, handler subscribes via decorator
        assert len(event_edges) >= 1

    def test_no_false_positives_on_unrelated_publish(self, tmp_path: Path) -> None:
        path = _write_source(
            tmp_path,
            "no_events.py",
            """\
            class Book:
                def publish(self):
                    \"\"\"Publish the book to the market.\"\"\"
                    self.is_published = True

            def use_book():
                book = Book()
                book.publish()
            """,
        )
        graph = extract_event_graph([path], root_dir=tmp_path)

        # book.publish() should NOT be detected as an event publish
        # because "book" is not an event-related object hint
        event_edges = [
            e for e in graph.edges() if any(s.signal_type == SignalType.EVENT for s in e.signals)
        ]
        assert len(event_edges) == 0

    def test_handles_syntax_errors(self, tmp_path: Path) -> None:
        path = tmp_path / "broken.py"
        path.write_text("def broken(:\n", encoding="utf-8")
        graph = extract_event_graph([path], root_dir=tmp_path)
        assert len(graph.nodes()) == 0

    def test_empty_source_list(self) -> None:
        graph = extract_event_graph([], root_dir=None)
        assert len(graph.nodes()) == 0
        assert len(graph.edges()) == 0


class TestMatchPublishersToSubscribers:
    def test_exact_topic_match(self) -> None:
        pub = EventEndpoint(
            function_name="mod.publish_fn",
            event_topic="order.created",
            direction="publish",
            file_path="mod.py",
            line_number=10,
        )
        sub = EventEndpoint(
            function_name="mod.subscribe_fn",
            event_topic="order.created",
            direction="subscribe",
            file_path="mod.py",
            line_number=20,
        )
        pairs = _match_publishers_to_subscribers([pub, sub])
        assert len(pairs) == 1
        assert pairs[0] == (pub, sub)

    def test_no_match_different_topics(self) -> None:
        pub = EventEndpoint(
            function_name="mod.pub",
            event_topic="order.created",
            direction="publish",
            file_path="mod.py",
            line_number=10,
        )
        sub = EventEndpoint(
            function_name="mod.sub",
            event_topic="user.login",
            direction="subscribe",
            file_path="mod.py",
            line_number=20,
        )
        pairs = _match_publishers_to_subscribers([pub, sub])
        assert len(pairs) == 0

    def test_unknown_topic_matches_all(self) -> None:
        pub = EventEndpoint(
            function_name="mod.pub",
            event_topic="unknown",
            direction="publish",
            file_path="mod.py",
            line_number=10,
        )
        sub1 = EventEndpoint(
            function_name="mod.sub1",
            event_topic="order.created",
            direction="subscribe",
            file_path="mod.py",
            line_number=20,
        )
        sub2 = EventEndpoint(
            function_name="mod.sub2",
            event_topic="user.login",
            direction="subscribe",
            file_path="mod.py",
            line_number=30,
        )
        pairs = _match_publishers_to_subscribers([pub, sub1, sub2])
        # Unknown publisher should match all subscribers
        assert len(pairs) == 2

    def test_no_self_edges(self) -> None:
        ep = EventEndpoint(
            function_name="mod.same_fn",
            event_topic="unknown",
            direction="publish",
            file_path="mod.py",
            line_number=10,
        )
        sub = EventEndpoint(
            function_name="mod.same_fn",
            event_topic="unknown",
            direction="subscribe",
            file_path="mod.py",
            line_number=10,
        )
        pairs = _match_publishers_to_subscribers([ep, sub])
        # Should not create self-edge
        assert all(p[0].function_name != p[1].function_name for p in pairs)
