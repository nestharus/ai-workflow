"""Component tests for orchestration.intake_queue module.

Tests IntakeQueue file-based queue operations (enqueue, peek, drain, count,
is_empty, needs_phase0), DemotionTicket-based enqueue, and route_items().
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.orchestration.demotion import DemotionTicket, RoutingItem
from spec_manager.orchestration.intake_queue import (
    QUEUE_DIR_NAME,
    IntakeQueue,
    route_items,
)


# ======================================================================
# IntakeQueue: empty state
# ======================================================================


class TestIntakeQueueEmpty:
    """Test IntakeQueue behavior when empty."""

    def test_starts_empty(self, tmp_path: Path) -> None:
        """IntakeQueue starts empty when queue directory does not exist."""
        queue = IntakeQueue(workspace_root=tmp_path)
        assert queue.is_empty() is True

    def test_count_is_zero(self, tmp_path: Path) -> None:
        """count() returns 0 for an empty queue."""
        queue = IntakeQueue(workspace_root=tmp_path)
        assert queue.count() == 0

    def test_peek_returns_empty_list(self, tmp_path: Path) -> None:
        """peek() returns empty list for an empty queue."""
        queue = IntakeQueue(workspace_root=tmp_path)
        assert queue.peek() == []

    def test_drain_returns_empty_list(self, tmp_path: Path) -> None:
        """drain() returns empty list for an empty queue."""
        queue = IntakeQueue(workspace_root=tmp_path)
        assert queue.drain() == []


# ======================================================================
# IntakeQueue: enqueue
# ======================================================================


class TestIntakeQueueEnqueue:
    """Test IntakeQueue.enqueue() behavior."""

    def test_enqueue_creates_json_file(self, tmp_path: Path) -> None:
        """enqueue() creates a JSON file in the queue directory."""
        queue = IntakeQueue(workspace_root=tmp_path)
        item = RoutingItem(
            item_id="item-001",
            text="New requirement text",
            source_path="/specs/req.md",
            desired_slice_hint="auth",
            tags=["security"],
        )

        path = queue.enqueue(item)

        assert path.exists()
        assert path.name == "item-001.json"
        assert path.parent == tmp_path / QUEUE_DIR_NAME

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["item_id"] == "item-001"
        assert data["text"] == "New requirement text"
        assert data["source_path"] == "/specs/req.md"
        assert data["desired_slice_hint"] == "auth"
        assert data["tags"] == ["security"]

    def test_enqueue_creates_directory(self, tmp_path: Path) -> None:
        """enqueue() creates the queue directory if it doesn't exist."""
        queue = IntakeQueue(workspace_root=tmp_path)
        item = RoutingItem(item_id="item-002", text="Some text")

        queue.enqueue(item)

        assert (tmp_path / QUEUE_DIR_NAME).exists()

    def test_enqueue_multiple_items(self, tmp_path: Path) -> None:
        """enqueue() supports multiple items."""
        queue = IntakeQueue(workspace_root=tmp_path)

        queue.enqueue(RoutingItem(item_id="a", text="First"))
        queue.enqueue(RoutingItem(item_id="b", text="Second"))
        queue.enqueue(RoutingItem(item_id="c", text="Third"))

        assert queue.count() == 3


# ======================================================================
# IntakeQueue: peek
# ======================================================================


class TestIntakeQueuePeek:
    """Test IntakeQueue.peek() behavior."""

    def test_peek_reads_items_without_removing(self, tmp_path: Path) -> None:
        """peek() reads items without removing them from the queue."""
        queue = IntakeQueue(workspace_root=tmp_path)
        queue.enqueue(RoutingItem(item_id="p1", text="Peek text", tags=["tag1"]))
        queue.enqueue(RoutingItem(item_id="p2", text="Peek text 2"))

        items = queue.peek()

        assert len(items) == 2
        assert items[0].item_id == "p1"
        assert items[0].text == "Peek text"
        assert items[0].tags == ["tag1"]
        assert items[1].item_id == "p2"

        # Items should still be in the queue
        assert queue.count() == 2


# ======================================================================
# IntakeQueue: drain
# ======================================================================


class TestIntakeQueueDrain:
    """Test IntakeQueue.drain() behavior."""

    def test_drain_reads_and_removes_items(self, tmp_path: Path) -> None:
        """drain() reads items and removes them from the queue."""
        queue = IntakeQueue(workspace_root=tmp_path)
        queue.enqueue(RoutingItem(item_id="d1", text="Drain text"))
        queue.enqueue(RoutingItem(item_id="d2", text="Drain text 2"))

        items = queue.drain()

        assert len(items) == 2
        assert items[0].item_id == "d1"
        assert items[1].item_id == "d2"

        # Queue should be empty after drain
        assert queue.is_empty() is True
        assert queue.count() == 0


# ======================================================================
# IntakeQueue: count and is_empty
# ======================================================================


class TestIntakeQueueCountAndIsEmpty:
    """Test IntakeQueue.count() and is_empty() consistency."""

    def test_count_reflects_queue_size(self, tmp_path: Path) -> None:
        """count() accurately reflects the number of items in the queue."""
        queue = IntakeQueue(workspace_root=tmp_path)

        assert queue.count() == 0
        queue.enqueue(RoutingItem(item_id="x1", text="T"))
        assert queue.count() == 1
        queue.enqueue(RoutingItem(item_id="x2", text="T"))
        assert queue.count() == 2

    def test_is_empty_correct_on_non_empty(self, tmp_path: Path) -> None:
        """is_empty() returns False when queue has items."""
        queue = IntakeQueue(workspace_root=tmp_path)
        queue.enqueue(RoutingItem(item_id="x1", text="T"))

        assert queue.is_empty() is False

    def test_is_empty_after_drain(self, tmp_path: Path) -> None:
        """is_empty() returns True after drain()."""
        queue = IntakeQueue(workspace_root=tmp_path)
        queue.enqueue(RoutingItem(item_id="x1", text="T"))
        queue.drain()

        assert queue.is_empty() is True


# ======================================================================
# IntakeQueue: needs_phase0
# ======================================================================


class TestIntakeQueueNeedsPhase0:
    """Test IntakeQueue.needs_phase0() logic."""

    def test_needs_phase0_when_queue_has_items(self, tmp_path: Path) -> None:
        """needs_phase0() returns True when queue is non-empty."""
        queue = IntakeQueue(workspace_root=tmp_path)
        queue.enqueue(RoutingItem(item_id="x1", text="T"))

        assert queue.needs_phase0() is True

    def test_no_phase0_when_empty_no_tickets(self, tmp_path: Path) -> None:
        """needs_phase0() returns False when queue is empty and no tickets."""
        queue = IntakeQueue(workspace_root=tmp_path)
        assert queue.needs_phase0() is False
        assert queue.needs_phase0(pending_tickets=[]) is False

    def test_needs_phase0_with_routing_required_ticket(self, tmp_path: Path) -> None:
        """needs_phase0() returns True when a ticket has routing_required=True."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(routing_required=True)

        assert queue.needs_phase0(pending_tickets=[ticket]) is True

    def test_no_phase0_with_non_routing_ticket(self, tmp_path: Path) -> None:
        """needs_phase0() returns False when no ticket has routing_required."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(routing_required=False)

        assert queue.needs_phase0(pending_tickets=[ticket]) is False


# ======================================================================
# IntakeQueue: enqueue_from_ticket
# ======================================================================


class TestIntakeQueueEnqueueFromTicket:
    """Test IntakeQueue.enqueue_from_ticket() behavior."""

    def test_enqueue_from_ticket_with_routing_required(self, tmp_path: Path) -> None:
        """enqueue_from_ticket() creates a queue item when routing_required=True."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(
            ticket_id="t-001",
            slice_id="auth",
            routing_required=True,
            routing_payload={
                "text": "Route this requirement",
                "source_path": "/specs/new.md",
                "desired_slice_hint": "auth",
                "tags": ["security", "routing"],
            },
            diagnosis="Test diagnosis",
        )

        path = queue.enqueue_from_ticket(ticket)

        assert path is not None
        assert path.exists()
        assert queue.count() == 1

        items = queue.peek()
        assert len(items) == 1
        assert items[0].text == "Route this requirement"

    def test_enqueue_from_ticket_without_routing_returns_none(
        self, tmp_path: Path
    ) -> None:
        """enqueue_from_ticket() returns None when routing_required=False."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(routing_required=False)

        result = queue.enqueue_from_ticket(ticket)

        assert result is None
        assert queue.is_empty() is True

    def test_enqueue_from_ticket_uses_diagnosis_as_fallback(
        self, tmp_path: Path
    ) -> None:
        """enqueue_from_ticket() uses ticket.diagnosis when payload has no text."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(
            routing_required=True,
            routing_payload={},
            diagnosis="Fallback diagnosis text",
        )

        queue.enqueue_from_ticket(ticket)
        items = queue.peek()
        assert items[0].text == "Fallback diagnosis text"

    def test_enqueue_from_ticket_uses_slice_id_as_hint(self, tmp_path: Path) -> None:
        """enqueue_from_ticket() uses ticket.slice_id as desired_slice_hint fallback."""
        queue = IntakeQueue(workspace_root=tmp_path)
        ticket = DemotionTicket(
            slice_id="payment",
            routing_required=True,
            routing_payload={},
            source="TEST_FAILURE",
        )

        queue.enqueue_from_ticket(ticket)
        items = queue.peek()
        assert items[0].desired_slice_hint == "payment"


# ======================================================================
# route_items()
# ======================================================================


class TestRouteItems:
    """Test route_items() function."""

    def test_empty_list_returns_empty(self, tmp_path: Path) -> None:
        """route_items() with empty list returns empty result."""
        result = route_items([], tmp_path)
        assert result == []

    def test_creates_staging_files(self, tmp_path: Path) -> None:
        """route_items() creates staging files for each item."""
        items = [
            RoutingItem(
                item_id="r1",
                text="Implement settlement processing",
                desired_slice_hint="settlement",
                tags=["finance"],
            ),
            RoutingItem(
                item_id="r2",
                text="Add auth middleware",
                desired_slice_hint="auth",
                tags=["security"],
            ),
        ]

        patches = route_items(items, tmp_path)

        assert len(patches) == 2

        # Check first patch
        assert patches[0].target_slice_id == "settlement"
        item_path = Path(patches[0].unified_diff_path)
        assert item_path.exists()
        assert "settlement processing" in item_path.read_text(encoding="utf-8")

        notes_path = Path(patches[0].notes_path)
        assert notes_path.exists()
        notes_content = notes_path.read_text(encoding="utf-8")
        assert "settlement" in notes_content
        assert "finance" in notes_content

    def test_uses_default_slice_when_no_hint(self, tmp_path: Path) -> None:
        """route_items() uses 'default' when no desired_slice_hint."""
        items = [
            RoutingItem(item_id="r3", text="Unrouted item"),
        ]

        patches = route_items(items, tmp_path)

        assert len(patches) == 1
        assert patches[0].target_slice_id == "default"
