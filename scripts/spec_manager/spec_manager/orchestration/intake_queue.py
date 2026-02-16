"""IntakeQueue: file-based queue for Phase 0 routing.

Phase 0 runs if and only if:
1. The intake queue is non-empty, OR
2. A DemotionTicket has ``routing_required=True``.

Items in the queue are JSON files in ``.pdd_intake_queue/`` within the
workspace.  Each file describes content that needs to be routed into
L1 code-as-spec.

Usage::

    queue = IntakeQueue(workspace_root=Path("."))

    # Add items
    queue.enqueue(RoutingItem(text="New requirement...", tags=["settlement"]))

    # Check if Phase 0 is needed
    if queue.needs_phase0():
        items = queue.drain()
        patches = route_items(items, workspace_root)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.orchestration.demotion import DemotionTicket, RoutedPatch, RoutingItem

logger = logging.getLogger(__name__)

QUEUE_DIR_NAME = ".pdd_intake_queue"
QUEUE_ERROR_DIR_NAME = ".pdd_intake_queue_errors"
ROUTING_FAILURE_DIR_NAME = ".pdd_intake_routing_failures"


class IntakeQueue:
    """File-based intake queue for Phase 0 routing.

    Items are stored as individual JSON files in the queue directory.
    Each file is a serialized RoutingItem.
    """

    def __init__(self, workspace_root: Path) -> None:
        self._root = workspace_root / QUEUE_DIR_NAME

    @property
    def queue_dir(self) -> Path:
        return self._root

    def enqueue(self, item: RoutingItem) -> Path:
        """Add an item to the queue.

        Returns:
            Path to the written queue file.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{item.item_id}.json"
        path.write_text(
            json.dumps(
                {
                    "item_id": item.item_id,
                    "text": item.text,
                    "source_path": item.source_path,
                    "desired_slice_hint": item.desired_slice_hint,
                    "tags": item.tags,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.debug("Enqueued routing item %s", item.item_id)
        return path

    def _deserialize_queue_item(self, path: Path) -> RoutingItem:
        data = json.loads(path.read_text(encoding="utf-8"))
        return RoutingItem(
            item_id=data.get("item_id", path.stem),
            text=data.get("text", ""),
            source_path=data.get("source_path"),
            desired_slice_hint=data.get("desired_slice_hint"),
            tags=data.get("tags", []),
        )

    def _quarantine_unreadable_item(self, path: Path, exc: Exception) -> None:
        """Move unreadable queue artifacts into an error directory for replay."""
        error_root = self._root.parent / QUEUE_ERROR_DIR_NAME
        error_root.mkdir(parents=True, exist_ok=True)
        target = error_root / path.name
        suffix = 1
        while target.exists():
            target = error_root / f"{path.stem}.{suffix}.json"
            suffix += 1
        path.replace(target)
        error_payload = {
            "source_path": str(path),
            "quarantined_path": str(target),
            "error": str(exc),
        }
        (target.with_suffix(".error.json")).write_text(
            json.dumps(error_payload, indent=2),
            encoding="utf-8",
        )

    def enqueue_from_ticket(self, ticket: DemotionTicket) -> Path | None:
        """Enqueue a routing item from a DemotionTicket.

        Only processes tickets with ``routing_required=True``.

        Returns:
            Path to the queue file, or None if not routing_required.
        """
        if not ticket.routing_required:
            return None

        payload = ticket.routing_payload or {}
        item = RoutingItem(
            text=payload.get("text", ticket.diagnosis),
            source_path=payload.get("source_path"),
            desired_slice_hint=payload.get("desired_slice_hint", ticket.slice_id),
            tags=payload.get("tags", [ticket.source]),
        )
        return self.enqueue(item)

    def is_empty(self) -> bool:
        """Check if the queue has no pending items."""
        if not self._root.exists():
            return True
        return not any(self._root.glob("*.json"))

    def count(self) -> int:
        """Count pending items in the queue."""
        if not self._root.exists():
            return 0
        return len(list(self._root.glob("*.json")))

    def peek(self) -> list[RoutingItem]:
        """Read all items without removing them."""
        if not self._root.exists():
            return []

        items = []
        for path in sorted(self._root.glob("*.json")):
            try:
                items.append(self._deserialize_queue_item(path))
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Failed to read queue item %s: %s", path, exc)
        return items

    def drain(self) -> list[RoutingItem]:
        """Read all items and remove them from the queue.

        Returns:
            List of RoutingItems that were in the queue.
        """
        items: list[RoutingItem] = []
        if not self._root.exists():
            return items
        for path in sorted(self._root.glob("*.json")):
            try:
                items.append(self._deserialize_queue_item(path))
                path.unlink()
            except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("Failed to drain queue item %s: %s", path, exc)
                self._quarantine_unreadable_item(path, exc)
        return items

    def needs_phase0(self, pending_tickets: list[DemotionTicket] | None = None) -> bool:
        """Check if Phase 0 should run.

        Phase 0 runs if:
        1. Queue is non-empty, OR
        2. Any pending ticket has routing_required=True.
        """
        if not self.is_empty():
            return True

        if pending_tickets:
            return any(t.routing_required for t in pending_tickets)

        return False


def route_items(
    items: list[RoutingItem],
    workspace_root: Path,
) -> list[RoutedPatch]:
    """Route items through Phase 0 intake pipeline.

    Each RoutingItem is converted into a RoutedPatch by the intake
    routing pipeline. Items that cannot be routed are logged and skipped.

    Args:
        items: Items to route.
        workspace_root: Workspace root path.

    Returns:
        List of RoutedPatch results.
    """
    if not items:
        return []

    patches: list[RoutedPatch] = []

    for item in items:
        try:
            patch = _route_single_item(item, workspace_root)
            if patch:
                patches.append(patch)
        except Exception as exc:
            logger.warning("Failed to route item %s: %s", item.item_id, exc)
            _persist_routing_failure(item, workspace_root, error=str(exc))

    logger.info(
        "Routed %d/%d items through Phase 0",
        len(patches),
        len(items),
    )
    return patches


def _route_single_item(
    item: RoutingItem,
    workspace_root: Path,
) -> RoutedPatch | None:
    """Route a single item through the intake pipeline.

    Writes the item text as a temporary spec file, then invokes
    the intake routing step to classify and assign it to a slice.
    """
    # Write item as a temp spec file
    intake_dir = workspace_root / ".pdd_intake_staging"
    intake_dir.mkdir(parents=True, exist_ok=True)
    item_path = intake_dir / f"{item.item_id}.md"
    item_path.write_text(item.text, encoding="utf-8")

    target_slice = str(item.desired_slice_hint or "").strip()
    if not target_slice:
        raise ValueError(f"Routing target is unresolved for intake item '{item.item_id}'")

    # Write the routed patch reference
    notes_path = intake_dir / f"{item.item_id}_notes.md"
    notes_path.write_text(
        f"# Routing Notes for {item.item_id}\n\n"
        f"- Source: {item.source_path or 'demotion'}\n"
        f"- Target slice: {target_slice}\n"
        f"- Tags: {', '.join(item.tags)}\n",
        encoding="utf-8",
    )

    return RoutedPatch(
        target_slice_id=target_slice,
        unified_diff_path=str(item_path),
        notes_path=str(notes_path),
    )


def _persist_routing_failure(item: RoutingItem, workspace_root: Path, *, error: str) -> None:
    """Persist failed routing inputs so they are diagnosable and replayable."""
    failure_dir = workspace_root / ROUTING_FAILURE_DIR_NAME
    failure_dir.mkdir(parents=True, exist_ok=True)
    failure_path = failure_dir / f"{item.item_id}.json"
    suffix = 1
    while failure_path.exists():
        failure_path = failure_dir / f"{item.item_id}.{suffix}.json"
        suffix += 1
    payload: dict[str, Any] = {
        "item": {
            "item_id": item.item_id,
            "text": item.text,
            "source_path": item.source_path,
            "desired_slice_hint": item.desired_slice_hint,
            "tags": item.tags,
        },
        "error": str(error).strip(),
    }
    failure_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
