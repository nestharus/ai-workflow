"""Tests for labyrinth core modules."""

import asyncio

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog
from spec_manager.labyrinth.core.record import InputRecord, OutputRecord
from spec_manager.labyrinth.core.worker_pool import WorkerPool


class TestInputRecord:
    def test_create_with_data(self):
        record = InputRecord(record_id="r1", data={"amount": 100, "type": "INVOICE"})
        assert record.record_id == "r1"
        assert record.get("amount") == 100
        assert record.get("type") == "INVOICE"
        assert record.get("missing") is None
        assert record.get("missing", "default") == "default"

    def test_empty_record(self):
        record = InputRecord(record_id="r2")
        assert record.data == {}
        assert record.metadata == {}


class TestOutputRecord:
    def test_create_with_data(self):
        record = OutputRecord(
            record_id="r1",
            source_rule_id="RULE-001",
            data={"tax_rate": 0.23},
            applied_rules=["RULE-001"],
        )
        assert record.record_id == "r1"
        assert record.source_rule_id == "RULE-001"
        assert record.get("tax_rate") == 0.23


class TestEventLog:
    def test_append_and_retrieve(self):
        log = EventLog()
        log.append("test_event", "test_source", "test_topic", {"key": "value"})
        assert len(log) == 1
        assert log.entries[0].event_type == "test_event"
        assert log.entries[0].source == "test_source"

    def test_filter_by_type(self):
        log = EventLog()
        log.append("type_a", "src1")
        log.append("type_b", "src2")
        log.append("type_a", "src3")
        assert len(log.filter_by_type("type_a")) == 2
        assert len(log.filter_by_type("type_b")) == 1

    def test_filter_by_source(self):
        log = EventLog()
        log.append("evt", "src1")
        log.append("evt", "src2")
        log.append("evt", "src1")
        assert len(log.filter_by_source("src1")) == 2

    def test_filter_by_topic(self):
        log = EventLog()
        log.append("evt", "src", "topic.a")
        log.append("evt", "src", "topic.b")
        assert len(log.filter_by_topic("topic.a")) == 1

    def test_get_sources_in_order(self):
        log = EventLog()
        log.append("evt", "src_b")
        log.append("evt", "src_a")
        log.append("evt", "src_b")
        assert log.get_sources_in_order() == ["src_b", "src_a"]

    def test_clear(self):
        log = EventLog()
        log.append("evt", "src")
        log.clear()
        assert len(log) == 0

    def test_thread_safety(self):
        """Test that concurrent appends don't corrupt the log."""
        import threading

        log = EventLog()

        def append_entries(n):
            for i in range(n):
                log.append("evt", f"thread_{threading.current_thread().name}", data={"i": i})

        threads = [threading.Thread(target=append_entries, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(log) == 200


class TestAsyncMessageBus:
    def test_subscribe_and_publish(self):
        bus = AsyncMessageBus()
        received = []

        async def handler(topic, payload):
            received.append((topic, payload))

        bus.subscribe("test.topic", handler, "sub1")
        asyncio.run(bus.publish("test.topic", {"key": "value"}))
        assert len(received) == 1
        assert received[0][0] == "test.topic"
        assert received[0][1] == {"key": "value"}

    def test_multiple_subscribers(self):
        bus = AsyncMessageBus()
        received = []

        async def handler1(topic, payload):
            received.append(("h1", topic))

        async def handler2(topic, payload):
            received.append(("h2", topic))

        bus.subscribe("topic", handler1, "sub1")
        bus.subscribe("topic", handler2, "sub2")
        asyncio.run(bus.publish("topic", {}))
        assert len(received) == 2

    def test_unsubscribe(self):
        bus = AsyncMessageBus()
        received = []

        async def handler(topic, payload):
            received.append(topic)

        bus.subscribe("topic", handler, "sub1")
        bus.unsubscribe("topic", "sub1")
        asyncio.run(bus.publish("topic", {}))
        assert len(received) == 0

    def test_no_subscribers(self):
        bus = AsyncMessageBus()
        # Should not raise
        asyncio.run(bus.publish("nonexistent", {}))

    def test_get_topics(self):
        bus = AsyncMessageBus()

        async def handler(t, p):
            pass

        bus.subscribe("a", handler, "s1")
        bus.subscribe("b", handler, "s2")
        topics = bus.get_topics()
        assert "a" in topics
        assert "b" in topics

    def test_get_subscriber_count(self):
        bus = AsyncMessageBus()

        async def handler(t, p):
            pass

        bus.subscribe("t", handler, "s1")
        bus.subscribe("t", handler, "s2")
        assert bus.get_subscriber_count("t") == 2
        assert bus.get_subscriber_count("other") == 0


class TestWorkerPool:
    def test_submit_sync_function(self):
        pool = WorkerPool(max_workers=2)

        def add(a, b):
            return a + b

        result = asyncio.run(pool.submit(add, 3, 4))
        assert result == 7
        pool.shutdown()

    def test_max_workers(self):
        pool = WorkerPool(max_workers=3)
        assert pool.max_workers == 3
        pool.shutdown()
