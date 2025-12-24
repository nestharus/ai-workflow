"""Tests for sandbox server."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts.servers.sandbox.protocol import (
    ConflictResponse,
    RebaseRequest,
    StatusRequest,
    SuccessResponse,
)
from scripts.servers.sandbox.server import (
    MAX_HISTORY_SIZE,
    OperationStatus,
    SandboxServer,
)


class TestPruneHistory:
    """Tests for _prune_history method."""

    def test_no_pruning_when_under_limit(self) -> None:
        """Do not prune when history is under MAX_HISTORY_SIZE."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add entries under the limit
        for i in range(100):
            server.operation_history[f"op-{i}"] = OperationStatus(
                request_id=f"op-{i}",
                status="completed",
            )

        server._prune_history()

        assert len(server.operation_history) == 100

    def test_prunes_when_over_limit(self) -> None:
        """Prune completed entries when history exceeds MAX_HISTORY_SIZE."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add entries over the limit
        for i in range(MAX_HISTORY_SIZE + 100):
            server.operation_history[f"op-{i}"] = OperationStatus(
                request_id=f"op-{i}",
                status="completed",
            )

        server._prune_history()

        # Should keep MAX_HISTORY_SIZE // 2 completed entries
        assert len(server.operation_history) == MAX_HISTORY_SIZE // 2

    def test_preserves_pending_and_in_progress(self) -> None:
        """Do not prune pending or in_progress entries."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add completed entries over the limit
        for i in range(MAX_HISTORY_SIZE + 100):
            server.operation_history[f"completed-{i}"] = OperationStatus(
                request_id=f"completed-{i}",
                status="completed",
            )

        # Add pending and in_progress entries
        server.operation_history["pending-1"] = OperationStatus(
            request_id="pending-1",
            status="pending",
        )
        server.operation_history["in-progress-1"] = OperationStatus(
            request_id="in-progress-1",
            status="in_progress",
        )

        server._prune_history()

        # Pending and in_progress should still exist
        assert "pending-1" in server.operation_history
        assert "in-progress-1" in server.operation_history
        assert server.operation_history["pending-1"].status == "pending"
        assert server.operation_history["in-progress-1"].status == "in_progress"

    def test_prunes_failed_and_cancelled(self) -> None:
        """Prune failed and cancelled entries along with completed."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add mixed terminal states over the limit
        for i in range(MAX_HISTORY_SIZE // 3 + 50):
            server.operation_history[f"completed-{i}"] = OperationStatus(
                request_id=f"completed-{i}",
                status="completed",
            )
            server.operation_history[f"failed-{i}"] = OperationStatus(
                request_id=f"failed-{i}",
                status="failed",
            )
            server.operation_history[f"cancelled-{i}"] = OperationStatus(
                request_id=f"cancelled-{i}",
                status="cancelled",
            )

        initial_size = len(server.operation_history)
        assert initial_size > MAX_HISTORY_SIZE

        server._prune_history()

        # Should have pruned to roughly half the max size
        assert len(server.operation_history) <= MAX_HISTORY_SIZE // 2 + 10

    def test_prunes_oldest_first(self) -> None:
        """Prune oldest completed entries first (dict insertion order)."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add entries in order - oldest first
        for i in range(MAX_HISTORY_SIZE + 100):
            server.operation_history[f"op-{i:05d}"] = OperationStatus(
                request_id=f"op-{i:05d}",
                status="completed",
            )

        server._prune_history()

        # Oldest entries (lower numbers) should be removed
        # Newest entries (higher numbers) should remain
        remaining_keys = list(server.operation_history.keys())

        # The remaining keys should be the higher numbered ones
        # Since we keep MAX_HISTORY_SIZE // 2 entries
        expected_start = MAX_HISTORY_SIZE + 100 - MAX_HISTORY_SIZE // 2
        for i, key in enumerate(remaining_keys):
            expected_key = f"op-{expected_start + i:05d}"
            assert key == expected_key, f"Expected {expected_key}, got {key}"


class TestDuplicateRequestId:
    """Tests for duplicate request_id rejection."""

    @pytest.mark.asyncio
    async def test_rejects_duplicate_request_id(self) -> None:
        """Reject operation with duplicate request_id."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()
        server._shutdown_event = asyncio.Event()

        # Pre-populate history with an existing request_id
        server.operation_history["existing-id"] = OperationStatus(
            request_id="existing-id",
            status="pending",
        )

        # Create a request with the same ID
        request = RebaseRequest(
            request_id="existing-id",
            branch="feature",
            target="main",
        )

        # Mock reader/writer - use mock writer for robustness against implementation changes
        reader = asyncio.StreamReader()
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()

        # Call _handle_operation - should return error immediately
        response = await server._handle_operation(request, reader, writer)

        # Parse response
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "existing-id"
        assert parsed["message"] == "Duplicate request_id"

        # History should not be modified
        assert server.operation_history["existing-id"].status == "pending"

    @pytest.mark.asyncio
    async def test_allows_unique_request_id(self) -> None:
        """Allow operation with unique request_id and add it to history."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()
        server._shutdown_event = asyncio.Event()

        # Pre-populate history with a different request_id
        server.operation_history["other-id"] = OperationStatus(
            request_id="other-id",
            status="completed",
        )

        # Create a request with a new unique ID
        request = RebaseRequest(
            request_id="new-id",
            branch="feature",
            target="main",
        )

        # Mock reader/writer
        reader = asyncio.StreamReader()
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()

        # Verify the request_id is not in history before calling
        assert "new-id" not in server.operation_history

        # Run _handle_operation but trigger shutdown to avoid waiting forever
        async def trigger_shutdown() -> None:
            # Wait briefly for the operation to be queued and history updated
            await asyncio.sleep(0.01)
            server._shutdown_event.set()

        # Run both concurrently
        shutdown_task = asyncio.create_task(trigger_shutdown())
        response = await server._handle_operation(request, reader, writer)
        await shutdown_task

        # The unique ID should now be in history (added before waiting for completion)
        assert "new-id" in server.operation_history
        # Status will be "failed" due to shutdown, but the key point is it was added
        assert server.operation_history["new-id"].status in ("pending", "failed")

        # The shutdown response indicates the operation was accepted (not duplicate error)
        parsed = json.loads(response)
        assert parsed["request_id"] == "new-id"
        # Should be shutdown error, not duplicate error
        assert "Duplicate" not in parsed.get("message", "")


class TestHandleStatus:
    """Tests for _handle_status method."""

    def test_empty_string_request_id_returns_aggregate(self) -> None:
        """Empty string request_id should be normalized to None and return aggregate."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Request status for empty string request_id
        request = StatusRequest(request_id="")

        response = server._handle_status(request)

        # Should return aggregate status (empty string normalized to None)
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert parsed["request_id"] == "status"
        assert "current" in parsed["result"]
        assert "queue_size" in parsed["result"]
        assert "history" in parsed["result"]

    def test_none_request_id_returns_aggregate(self) -> None:
        """None request_id should return aggregate status."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Request status with None request_id
        request = StatusRequest(request_id=None)

        response = server._handle_status(request)

        # Should return aggregate status
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert parsed["request_id"] == "status"
        assert "current" in parsed["result"]
        assert "queue_size" in parsed["result"]
        assert "history" in parsed["result"]

    def test_specific_request_id_returns_operation_status(self) -> None:
        """Specific request_id should return that operation's status."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an operation to history
        server.operation_history["test-op-123"] = OperationStatus(
            request_id="test-op-123",
            status="completed",
            result={"message": "Done"},
        )

        # Request status for that operation
        request = StatusRequest(request_id="test-op-123")

        response = server._handle_status(request)

        # Should return success with the operation result
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert parsed["request_id"] == "test-op-123"
        assert parsed["result"]["message"] == "Done"

    def test_conflict_status_returns_conflict_response(self) -> None:
        """Conflict status should return ConflictResponse, not SuccessResponse."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an operation with conflict status to history
        server.operation_history["conflict-op"] = OperationStatus(
            request_id="conflict-op",
            status="conflict",
            result={"conflicts": ["file1.txt", "file2.txt"]},
        )

        # Request status for that operation
        request = StatusRequest(request_id="conflict-op")

        response = server._handle_status(request)

        # Should return conflict response, not success
        parsed = json.loads(response)
        assert parsed["status"] == "conflict"
        assert parsed["request_id"] == "conflict-op"
        assert parsed["files"] == ["file1.txt", "file2.txt"]

    def test_conflict_status_handles_empty_conflicts(self) -> None:
        """Conflict status with empty conflicts list should return empty files."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an operation with conflict status but empty conflicts
        server.operation_history["conflict-op-empty"] = OperationStatus(
            request_id="conflict-op-empty",
            status="conflict",
            result={"conflicts": []},
        )

        request = StatusRequest(request_id="conflict-op-empty")
        response = server._handle_status(request)

        parsed = json.loads(response)
        assert parsed["status"] == "conflict"
        assert parsed["files"] == []

    def test_conflict_status_handles_missing_result(self) -> None:
        """Conflict status with None result should return empty files."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an operation with conflict status but None result
        server.operation_history["conflict-op-none"] = OperationStatus(
            request_id="conflict-op-none",
            status="conflict",
            result=None,
        )

        request = StatusRequest(request_id="conflict-op-none")
        response = server._handle_status(request)

        parsed = json.loads(response)
        assert parsed["status"] == "conflict"
        assert parsed["files"] == []


class TestHandleCancel:
    """Tests for _handle_cancel method."""

    def test_successfully_cancel_pending_operation(self) -> None:
        """Successfully cancel a pending operation."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add a pending operation
        server.operation_history["pending-op"] = OperationStatus(
            request_id="pending-op",
            status="pending",
        )

        from scripts.servers.sandbox.protocol import CancelRequest

        request = CancelRequest(request_id="pending-op")
        response = server._handle_cancel(request)

        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert parsed["request_id"] == "pending-op"
        assert parsed["result"]["message"] == "Operation cancelled"

        # Verify the status was updated to cancelled
        assert server.operation_history["pending-op"].status == "cancelled"

    def test_successfully_cancel_in_progress_operation(self) -> None:
        """Successfully cancel an in_progress operation."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an in_progress operation
        server.operation_history["in-progress-op"] = OperationStatus(
            request_id="in-progress-op",
            status="in_progress",
        )

        from scripts.servers.sandbox.protocol import CancelRequest

        request = CancelRequest(request_id="in-progress-op")
        response = server._handle_cancel(request)

        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert parsed["request_id"] == "in-progress-op"
        assert parsed["result"]["message"] == "Operation cancelled"

        # Verify the status was updated to cancelled
        assert server.operation_history["in-progress-op"].status == "cancelled"

    def test_cannot_cancel_completed_operation(self) -> None:
        """Cannot cancel an operation with completed status."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add a completed operation
        server.operation_history["completed-op"] = OperationStatus(
            request_id="completed-op",
            status="completed",
            result={"message": "Done"},
        )

        from scripts.servers.sandbox.protocol import CancelRequest

        request = CancelRequest(request_id="completed-op")
        response = server._handle_cancel(request)

        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert "Cannot cancel operation with status: completed" in parsed["message"]

        # Verify the status was NOT changed
        assert server.operation_history["completed-op"].status == "completed"

    def test_cannot_cancel_conflict_status(self) -> None:
        """Cannot cancel an operation with conflict status."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Add an operation with conflict status
        server.operation_history["conflict-op"] = OperationStatus(
            request_id="conflict-op",
            status="conflict",
            result={"conflicts": ["file.txt"]},
        )

        from scripts.servers.sandbox.protocol import CancelRequest

        request = CancelRequest(request_id="conflict-op")
        response = server._handle_cancel(request)

        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert "Cannot cancel operation with status: conflict" in parsed["message"]

    def test_cannot_cancel_nonexistent_operation(self) -> None:
        """Cannot cancel an operation that does not exist."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()

        # Do not add any operation - history is empty

        from scripts.servers.sandbox.protocol import CancelRequest

        request = CancelRequest(request_id="nonexistent-op")
        response = server._handle_cancel(request)

        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "nonexistent-op"
        assert parsed["message"] == "Operation not found"


class TestPruneHistoryWithConflict:
    """Tests for _prune_history with conflict status."""

    def test_prunes_conflict_entries(self) -> None:
        """Prune conflict entries along with other terminal states."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Add entries over the limit including conflict status
        for i in range(MAX_HISTORY_SIZE // 4 + 50):
            server.operation_history[f"completed-{i}"] = OperationStatus(
                request_id=f"completed-{i}",
                status="completed",
            )
            server.operation_history[f"conflict-{i}"] = OperationStatus(
                request_id=f"conflict-{i}",
                status="conflict",
                result={"conflicts": ["file.txt"]},
            )
            server.operation_history[f"failed-{i}"] = OperationStatus(
                request_id=f"failed-{i}",
                status="failed",
            )
            server.operation_history[f"cancelled-{i}"] = OperationStatus(
                request_id=f"cancelled-{i}",
                status="cancelled",
            )

        initial_size = len(server.operation_history)
        assert initial_size > MAX_HISTORY_SIZE

        server._prune_history()

        # Should have pruned to roughly half the max size
        assert len(server.operation_history) <= MAX_HISTORY_SIZE // 2 + 10


class TestEarlyShutdown:
    """Tests for early shutdown signal handling."""

    def test_shutdown_before_start_sets_flag(self) -> None:
        """Calling shutdown() before start() sets _shutdown_requested flag."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Event should not exist yet
        assert server._shutdown_event is None
        assert server._shutdown_requested is False

        # Call shutdown before start
        server.shutdown()

        # Flag should be set, event still None (no running event loop)
        assert server._shutdown_requested is True
        # Event may or may not be set depending on whether there's a running loop

    @pytest.mark.asyncio
    async def test_early_shutdown_is_honored_by_start(self) -> None:
        """start() should honor shutdown requested before it was called."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Request shutdown before start
        server.shutdown()
        assert server._shutdown_requested is True

        # Now start - it should create the event and immediately set it
        # We need to mock ensure_sandbox_exists and the socket server
        from unittest.mock import patch

        mock_server = MagicMock()
        mock_server.close = MagicMock()
        mock_server.wait_closed = AsyncMock()

        with (
            patch(
                "scripts.servers.sandbox.server.ensure_sandbox_exists",
                return_value=Path("/tmp/sandbox"),
            ),
            patch(
                "asyncio.start_unix_server",
                new=AsyncMock(return_value=mock_server),
            ),
            patch(
                "scripts.servers.sandbox.server.os.chmod",
            ),
            patch(
                "scripts.servers.sandbox.server.os.unlink",
            ),
        ):
            # start() should return quickly because shutdown was already requested
            # The event should be set immediately
            await asyncio.wait_for(server.start(), timeout=2.0)

        # Verify the event was set (this allowed start to exit)
        assert server._shutdown_event is not None
        assert server._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_shutdown_after_start_sets_event(self) -> None:
        """Calling shutdown() after start() has created the event sets it."""
        server = SandboxServer(repo_path=Path("/tmp"))

        # Manually initialize like start() does
        server._shutdown_event = asyncio.Event()

        # Event should not be set yet
        assert not server._shutdown_event.is_set()

        # Call shutdown
        server.shutdown()

        # Both flag and event should be set
        assert server._shutdown_requested is True
        assert server._shutdown_event.is_set()


class TestProcessQueuePrunesOnCancel:
    """Tests for _process_queue pruning on early cancellation."""

    @pytest.mark.asyncio
    async def test_prunes_history_on_pre_execution_cancel(self) -> None:
        """Prune history when operation is cancelled before execution."""
        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()
        server._shutdown_event = asyncio.Event()
        server._conflict_resolved_event = asyncio.Event()
        server._conflict_resolved_event.set()  # Not blocked

        # Fill history to trigger pruning
        for i in range(MAX_HISTORY_SIZE + 100):
            server.operation_history[f"old-{i}"] = OperationStatus(
                request_id=f"old-{i}",
                status="completed",
            )

        # Create a cancelled operation
        from scripts.servers.sandbox.server import QueuedOperation

        response_queue: asyncio.Queue[str] = asyncio.Queue()
        queued_op = QueuedOperation(
            request_id="cancel-test",
            request=RebaseRequest(request_id="cancel-test", branch="feature", target="main"),
            response_queue=response_queue,
        )
        await server.operation_queue.put(queued_op)

        # Mark as cancelled in history before processing
        server.operation_history["cancel-test"] = OperationStatus(
            request_id="cancel-test",
            status="cancelled",
        )

        # Process one iteration by running _process_queue briefly
        process_task = asyncio.create_task(server._process_queue())

        # Wait for the cancelled operation to be processed
        response = await asyncio.wait_for(response_queue.get(), timeout=1.0)

        # Stop the processor
        process_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await process_task

        # Verify response indicates cancellation
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert "cancelled" in parsed["message"]

        # Verify history was pruned - should be down to MAX_HISTORY_SIZE // 2 + 1
        # (the +1 is for the cancel-test entry)
        assert len(server.operation_history) <= MAX_HISTORY_SIZE // 2 + 10


class TestCancellationBeforePush:
    """Tests for cancellation check before push side effect."""

    def test_format_rebase_result_skips_push_when_cancelled(self) -> None:
        """_format_rebase_result should skip push if operation was cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as cancelled in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="cancelled",
        )

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it's NOT called
        with patch("scripts.servers.sandbox.server.push_from_sandbox") as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should NOT have been called
        mock_push.assert_not_called()

        # Response should indicate cancellation
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "test-op"
        assert "cancelled" in parsed["message"]

    def test_format_merge_result_skips_push_when_cancelled(self) -> None:
        """_format_merge_result should skip push if operation was cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as cancelled in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="cancelled",
        )

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it's NOT called
        with patch("scripts.servers.sandbox.server.push_from_sandbox") as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should NOT have been called
        mock_push.assert_not_called()

        # Response should indicate cancellation
        parsed = json.loads(response)
        assert parsed["status"] == "error"
        assert parsed["request_id"] == "test-op"
        assert "cancelled" in parsed["message"]

    def test_format_rebase_result_pushes_when_not_cancelled(self) -> None:
        """_format_rebase_result should push when operation is not cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as in_progress (not cancelled) in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="in_progress",
        )

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should have been called
        mock_push.assert_called_once_with(Path("/tmp/sandbox"), "feature-branch", force=True)

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert "pushed" in parsed["result"]["message"]

    def test_format_merge_result_pushes_when_not_cancelled(self) -> None:
        """_format_merge_result should push when operation is not cancelled."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # Mark operation as in_progress (not cancelled) in history
        server.operation_history["test-op"] = OperationStatus(
            request_id="test-op",
            status="in_progress",
        )

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should have been called
        mock_push.assert_called_once_with(Path("/tmp/sandbox"), "feature-branch", force=False)

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"
        assert "pushed" in parsed["result"]["message"]

    def test_format_rebase_result_pushes_when_no_history_entry(self) -> None:
        """_format_rebase_result should push when there's no history entry (edge case)."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import RebaseResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # No history entry for this operation
        assert "test-op" not in server.operation_history

        # Create a successful rebase result
        result = RebaseResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called (fail-safe behavior)
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_rebase_result("test-op", result, "feature-branch")

        # Push should have been called (no history means not cancelled)
        mock_push.assert_called_once()

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"

    def test_format_merge_result_pushes_when_no_history_entry(self) -> None:
        """_format_merge_result should push when there's no history entry (edge case)."""
        from unittest.mock import patch

        from scripts.servers.sandbox.operations import MergeResult

        server = SandboxServer(repo_path=Path("/tmp"))
        server.sandbox_path = Path("/tmp/sandbox")

        # No history entry for this operation
        assert "test-op" not in server.operation_history

        # Create a successful merge result
        result = MergeResult(success=True, has_conflicts=False, conflicts=[], error="")

        # Mock push_from_sandbox to verify it IS called (fail-safe behavior)
        with patch(
            "scripts.servers.sandbox.server.push_from_sandbox", return_value=(True, None)
        ) as mock_push:
            response = server._format_merge_result("test-op", result, "feature-branch")

        # Push should have been called (no history means not cancelled)
        mock_push.assert_called_once()

        # Response should indicate success
        parsed = json.loads(response)
        assert parsed["status"] == "success"


class TestStartSandboxInitializationError:
    """Tests for start() handling sandbox initialization errors."""

    @pytest.mark.asyncio
    async def test_start_raises_on_sandbox_initialization_error(self) -> None:
        """start() should raise RuntimeError if ensure_sandbox_exists fails."""
        from unittest.mock import patch

        server = SandboxServer(repo_path=Path("/tmp"))

        with (
            patch(
                "scripts.servers.sandbox.server.ensure_sandbox_exists",
                side_effect=RuntimeError("Sandbox initialization failed"),
            ),
            pytest.raises(RuntimeError, match="Sandbox initialization failed"),
        ):
            await server.start()


class TestRunServer:
    """Tests for run_server function."""

    @pytest.mark.asyncio
    async def test_run_server_creates_server_and_calls_start(self) -> None:
        """run_server should create SandboxServer and call start."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        with patch(
            "scripts.servers.sandbox.server.SandboxServer",
            return_value=mock_server_instance,
        ) as mock_server_class:
            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        mock_server_class.assert_called_once_with(
            repo_path=Path("/repo"),
            socket_path="/tmp/test.sock",
        )
        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_server_registers_signal_handlers(self) -> None:
        """run_server should register SIGTERM and SIGINT signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        registered_signals = []

        def mock_add_signal_handler(sig: int, handler: object) -> None:
            registered_signals.append(sig)

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        import signal as sig_module

        assert sig_module.SIGTERM in registered_signals
        assert sig_module.SIGINT in registered_signals

    @pytest.mark.asyncio
    async def test_run_server_handles_signal_handler_not_implemented(self) -> None:
        """run_server should handle NotImplementedError for signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        def mock_add_signal_handler_not_impl(sig: int, handler: object) -> None:
            raise NotImplementedError("Signal handlers not supported on this platform")

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler_not_impl
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            # Should not raise - NotImplementedError is caught and logged
            await run_server("/tmp/test.sock", "/repo")

        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_server_handles_signal_handler_runtime_error(self) -> None:
        """run_server should handle RuntimeError for signal handlers."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        def mock_add_signal_handler_runtime_err(sig: int, handler: object) -> None:
            raise RuntimeError("Signal handler error")

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler_runtime_err
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            # Should not raise - RuntimeError is caught and logged
            await run_server("/tmp/test.sock", "/repo")

        mock_server_instance.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_signal_calls_shutdown(self) -> None:
        """The handle_signal function should call server.shutdown()."""
        from unittest.mock import AsyncMock, patch

        mock_server_instance = MagicMock()
        mock_server_instance.start = AsyncMock()
        mock_server_instance.shutdown = MagicMock()

        captured_handler = None

        def mock_add_signal_handler(sig: int, handler: object) -> None:
            nonlocal captured_handler
            # Capture the first handler (SIGTERM)
            if captured_handler is None:
                captured_handler = handler

        with (
            patch(
                "scripts.servers.sandbox.server.SandboxServer",
                return_value=mock_server_instance,
            ),
            patch("asyncio.get_running_loop") as mock_get_loop,
        ):
            mock_loop = MagicMock()
            mock_loop.add_signal_handler = mock_add_signal_handler
            mock_get_loop.return_value = mock_loop

            from scripts.servers.sandbox.server import run_server

            await run_server("/tmp/test.sock", "/repo")

        # Now call the captured handler to test handle_signal
        assert captured_handler is not None
        captured_handler()

        mock_server_instance.shutdown.assert_called()


class TestQueueIsolationWithConflicts:
    """Tests for queue isolation when operations have conflicts."""

    @pytest.mark.asyncio
    async def test_operations_processed_sequentially(self) -> None:
        """Verify operations are processed sequentially, not concurrently."""
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch

        from scripts.servers.sandbox.server import QueuedOperation

        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()
        server._shutdown_event = asyncio.Event()
        server._conflict_resolved_event = asyncio.Event()
        server._conflict_resolved_event.set()  # Not blocked
        server._git_executor = ThreadPoolExecutor(max_workers=1)
        server.sandbox_path = Path("/tmp/sandbox")

        execution_order: list[str] = []

        def mock_execute_op(request):
            execution_order.append(request.request_id)
            response = SuccessResponse(
                request_id=request.request_id,
                result={"message": "Done"},
            )
            return response.to_json()

        with patch.object(server, "_execute_operation", side_effect=mock_execute_op):
            # Add two operations
            response_queue_1: asyncio.Queue[str] = asyncio.Queue()
            queued_op_1 = QueuedOperation(
                request_id="op-1",
                request=RebaseRequest(request_id="op-1", branch="feature-1", target="main"),
                response_queue=response_queue_1,
            )
            await server.operation_queue.put(queued_op_1)
            server.operation_history["op-1"] = OperationStatus(request_id="op-1", status="pending")

            response_queue_2: asyncio.Queue[str] = asyncio.Queue()
            queued_op_2 = QueuedOperation(
                request_id="op-2",
                request=RebaseRequest(request_id="op-2", branch="feature-2", target="main"),
                response_queue=response_queue_2,
            )
            await server.operation_queue.put(queued_op_2)
            server.operation_history["op-2"] = OperationStatus(request_id="op-2", status="pending")

            # Start processor
            process_task = asyncio.create_task(server._process_queue())

            # Wait for both to complete
            await asyncio.wait_for(response_queue_1.get(), timeout=1.0)
            await asyncio.wait_for(response_queue_2.get(), timeout=1.0)

            # Verify sequential execution
            assert len(execution_order) == 2
            assert execution_order[0] == "op-1"
            assert execution_order[1] == "op-2"

            process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await process_task

    @pytest.mark.asyncio
    async def test_queue_maintains_order(self) -> None:
        """Verify the queue maintains FIFO order."""
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import patch

        from scripts.servers.sandbox.server import QueuedOperation

        server = SandboxServer(repo_path=Path("/tmp"))
        server.operation_queue = asyncio.Queue()
        server._shutdown_event = asyncio.Event()
        server._conflict_resolved_event = asyncio.Event()
        server._conflict_resolved_event.set()  # Not blocked
        server._git_executor = ThreadPoolExecutor(max_workers=1)
        server.sandbox_path = Path("/tmp/sandbox")

        execution_order: list[str] = []

        def mock_execute_op(request):
            execution_order.append(request.request_id)
            response = SuccessResponse(
                request_id=request.request_id,
                result={"message": "Done"},
            )
            return response.to_json()

        with patch.object(server, "_execute_operation", side_effect=mock_execute_op):
            # Add multiple operations in order
            for i in range(3):
                response_queue: asyncio.Queue[str] = asyncio.Queue()
                queued_op = QueuedOperation(
                    request_id=f"op-{i}",
                    request=RebaseRequest(
                        request_id=f"op-{i}", branch=f"feature-{i}", target="main"
                    ),
                    response_queue=response_queue,
                )
                await server.operation_queue.put(queued_op)
                server.operation_history[f"op-{i}"] = OperationStatus(
                    request_id=f"op-{i}", status="pending"
                )

            # Start processor
            process_task = asyncio.create_task(server._process_queue())

            # Wait for all to complete
            for _i in range(3):
                response_queue = asyncio.Queue()
                # This won't actually get the responses, but we need to wait
                await asyncio.sleep(0.05)

            # Give time for all to process
            await asyncio.sleep(0.3)

            # Verify FIFO order
            assert len(execution_order) == 3
            assert execution_order == ["op-0", "op-1", "op-2"]

            process_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await process_task


class TestMainFunction:
    """Tests for main function."""

    def test_main_configures_logging_and_runs_server(self) -> None:
        """main should configure logging and run the server."""
        from unittest.mock import patch

        with (
            patch("scripts.servers.sandbox.server._configure_logging") as mock_config_logging,
            patch("scripts.servers.sandbox.server.asyncio.run") as mock_asyncio_run,
            patch.dict(
                "os.environ",
                {"SANDBOX_SOCKET_PATH": "/custom/socket.sock", "SANDBOX_REPO_PATH": "/custom/repo"},
            ),
        ):
            from scripts.servers.sandbox.server import main

            main()

        mock_config_logging.assert_called_once()
        mock_asyncio_run.assert_called_once()

    def test_main_uses_default_paths_when_env_not_set(self) -> None:
        """main should use default paths when environment variables are not set."""
        from unittest.mock import patch

        captured_args = []

        def capture_run_server(coro: object) -> None:
            # Extract args from coroutine if needed
            captured_args.append(coro)

        with (
            patch("scripts.servers.sandbox.server._configure_logging"),
            patch("scripts.servers.sandbox.server.asyncio.run", side_effect=capture_run_server),
            patch.dict("os.environ", {}, clear=True),
        ):
            # Remove env vars if present
            import os

            os.environ.pop("SANDBOX_SOCKET_PATH", None)
            os.environ.pop("SANDBOX_REPO_PATH", None)

            from scripts.servers.sandbox.server import main

            main()

        # Verify asyncio.run was called (the coroutine was created with default paths)
        assert len(captured_args) == 1

    def test_main_handles_keyboard_interrupt(self) -> None:
        """main should handle KeyboardInterrupt gracefully."""
        from unittest.mock import patch

        with (
            patch("scripts.servers.sandbox.server._configure_logging"),
            patch("scripts.servers.sandbox.server.asyncio.run", side_effect=KeyboardInterrupt()),
            pytest.raises(SystemExit) as exc_info,
        ):
            from scripts.servers.sandbox.server import main

            main()

        assert exc_info.value.code == 0
