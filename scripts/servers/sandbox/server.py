"""Sandbox socket server for queue-based rebase/merge operations.

Provides an async socket server that processes rebase and merge operations
sequentially, ensuring only one operation runs at a time in the sandbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from scripts.servers.sandbox.constants import DEFAULT_SOCKET_PATH
from scripts.servers.sandbox.operations import (
    MergeResult,
    RebaseResult,
    ensure_sandbox_exists,
    is_sandbox_clean,
    merge_in_sandbox,
    push_from_sandbox,
    rebase_in_sandbox,
)
from scripts.servers.sandbox.protocol import (
    CancelRequest,
    ConflictResponse,
    ErrorResponse,
    MergeRequest,
    ProgressResponse,
    QueuedResponse,
    RebaseRequest,
    StatusRequest,
    SuccessResponse,
    parse_request,
)

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configure logging for the server.

    Deferred to avoid interfering with application/test logging when imported.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# Default repo path (can be overridden via environment)
DEFAULT_REPO_PATH = "/repo"


@dataclass
class QueuedOperation:
    """An operation waiting in the queue."""

    request_id: str
    request: RebaseRequest | MergeRequest
    response_queue: asyncio.Queue[str]


@dataclass
class OperationStatus:
    """Status of a completed or in-progress operation."""

    request_id: str
    status: str  # "pending", "in_progress", "completed", "conflict", "failed", "cancelled"
    result: dict[str, object] | None = None
    error: str | None = None
    # Store operation details for resuming after conflict resolution
    branch: str | None = None
    target: str | None = None


MAX_HISTORY_SIZE = 1000


# Interval between polls when waiting for sandbox to become clean
SANDBOX_POLL_INTERVAL = 1.0  # seconds


@dataclass
class SandboxServer:
    """Server that processes sandbox operations sequentially."""

    repo_path: Path
    socket_path: str = DEFAULT_SOCKET_PATH
    sandbox_path: Path | None = None
    operation_queue: asyncio.Queue[QueuedOperation] | None = None
    operation_history: dict[str, OperationStatus] = field(default_factory=dict)
    _history_lock: threading.Lock = field(default_factory=threading.Lock)
    current_operation: str | None = None
    _shutdown_event: asyncio.Event | None = None
    _shutdown_requested: bool = False  # Track early shutdown requests before event loop
    _server: asyncio.Server | None = None
    _git_executor: ThreadPoolExecutor | None = None  # Single-threaded executor for git operations
    # Track conflict state for polling
    _conflict_branch: str | None = None  # Branch being worked on during conflict resolution

    async def start(self) -> None:
        """Start the server."""
        # Initialize asyncio primitives in async context
        self.operation_queue = asyncio.Queue()
        self._shutdown_event = asyncio.Event()
        # Create a single-threaded executor for git operations to prevent concurrency
        self._git_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="git-op")

        # Check if shutdown was requested before the event loop started
        if self._shutdown_requested:
            self._shutdown_event.set()

        # Ensure sandbox exists
        logger.info(f"Initializing sandbox for repo at {self.repo_path}")
        try:
            self.sandbox_path = ensure_sandbox_exists(self.repo_path)
            logger.info(f"Sandbox initialized at {self.sandbox_path}")
        except RuntimeError:
            logger.exception("Failed to initialize sandbox")
            raise

        # Remove existing socket file if present
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.socket_path)

        # Start the Unix socket server first (before the processor task)
        # to avoid leaking the task if server startup fails
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )

        # Make socket world-writable so host CLI can connect regardless of user
        # This is required when running the server as root in Docker while the
        # CLI runs as a non-root user on the host
        os.chmod(self.socket_path, 0o777)

        logger.info(f"Server listening on {self.socket_path}")

        # Start the operation processor after server is ready
        processor_task = asyncio.create_task(self._process_queue())

        try:
            # Wait for shutdown signal
            await self._shutdown_event.wait()
        finally:
            # Cleanup - always runs even if cancelled during wait
            self._server.close()
            await self._server.wait_closed()
            processor_task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await processor_task

            # Shutdown the git executor
            if self._git_executor is not None:
                self._git_executor.shutdown(wait=True)

            # Remove socket file
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.socket_path)

            logger.info("Server shutdown complete")

    def shutdown(self) -> None:
        """Signal the server to shut down.

        Safe to call before start() - sets a flag that start() will check,
        ensuring early signals are not dropped.
        """
        self._shutdown_requested = True
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection."""
        try:
            while True:
                # Read until newline (JSON message)
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=300.0)
                except TimeoutError:
                    logger.warning("Client connection timed out")
                    break
                if not data:
                    break

                try:
                    request = parse_request(data.decode().strip())
                except ValueError as e:
                    error_response = ErrorResponse(
                        request_id="unknown",
                        message=str(e),
                    )
                    writer.write(error_response.to_json().encode() + b"\n")
                    await writer.drain()
                    continue

                # Handle the request
                response = await self._handle_request(request, reader, writer)
                writer.write(response.encode() + b"\n")
                await writer.drain()

        except Exception:
            logger.exception("Error handling client")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_request(
        self,
        request: RebaseRequest | MergeRequest | StatusRequest | CancelRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> str:
        """Handle a parsed request and return JSON response."""
        if isinstance(request, StatusRequest):
            return self._handle_status(request)
        elif isinstance(request, CancelRequest):
            return self._handle_cancel(request)
        elif isinstance(request, (RebaseRequest, MergeRequest)):
            return await self._handle_operation(request, reader, writer)
        else:
            return ErrorResponse(
                request_id=getattr(request, "request_id", "unknown"),
                message="Unknown request type",
            ).to_json()

    def _handle_status(self, request: StatusRequest) -> str:
        """Handle a status request."""
        # Normalize empty string to None for aggregate semantics
        request_id = request.request_id if request.request_id else None
        if request_id is not None:
            # Get status for specific operation
            with self._history_lock:
                status = self.operation_history.get(request_id)
                if status:
                    # Copy values under lock to avoid races
                    status_value = status.status
                    result_value = status.result
                    error_value = status.error
                else:
                    status_value = None
                    result_value = None
                    error_value = None
            if status_value is not None:
                if status_value == "completed":
                    return SuccessResponse(
                        request_id=request_id,
                        result=result_value or {},
                    ).to_json()
                elif status_value == "conflict":
                    files: list[str] = []
                    if isinstance(result_value, dict):
                        conflicts_value = result_value.get("conflicts", [])
                        if isinstance(conflicts_value, list):
                            files = [str(f) for f in conflicts_value]
                    return ConflictResponse(
                        request_id=request_id,
                        files=files,
                    ).to_json()
                elif status_value == "failed":
                    return ErrorResponse(
                        request_id=request_id,
                        message=error_value or "Unknown error",
                    ).to_json()
                elif status_value == "in_progress":
                    return ProgressResponse(
                        request_id=request_id,
                        message="Operation in progress",
                    ).to_json()
                elif status_value == "pending":
                    # Find position in queue
                    position = self._get_queue_position(request_id)
                    return QueuedResponse(
                        request_id=request_id,
                        position=position,
                    ).to_json()
                elif status_value == "cancelled":
                    return ErrorResponse(
                        request_id=request_id,
                        message="Operation was cancelled",
                    ).to_json()
            return ErrorResponse(
                request_id=request_id,
                message="Operation not found",
            ).to_json()
        else:
            # Get all statuses
            assert self.operation_queue is not None
            with self._history_lock:
                history_copy = {
                    k: {"status": v.status, "error": v.error}
                    for k, v in self.operation_history.items()
                }
            result = {
                "current": self.current_operation,
                "queue_size": self.operation_queue.qsize(),
                "history": history_copy,
            }
            return SuccessResponse(
                request_id="status",
                result=result,
            ).to_json()

    def _handle_cancel(self, request: CancelRequest) -> str:
        """Handle a cancel request."""
        with self._history_lock:
            status = self.operation_history.get(request.request_id)
            if not status:
                return ErrorResponse(
                    request_id=request.request_id,
                    message="Operation not found",
                ).to_json()

            if status.status in ("completed", "conflict", "failed", "cancelled"):
                return ErrorResponse(
                    request_id=request.request_id,
                    message=f"Cannot cancel operation with status: {status.status}",
                ).to_json()

            # Mark as cancelled
            status.status = "cancelled"
        return SuccessResponse(
            request_id=request.request_id,
            result={"message": "Operation cancelled"},
        ).to_json()

    async def _handle_operation(
        self,
        request: RebaseRequest | MergeRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> str:
        """Handle a rebase or merge operation request.

        Queues the operation and waits for completion.
        """
        assert self.operation_queue is not None
        assert self._shutdown_event is not None

        op_type = "rebase" if isinstance(request, RebaseRequest) else "merge"
        logger.info(
            "Received %s operation: request_id=%s, branch=%s, target=%s",
            op_type,
            request.request_id,
            request.branch,
            request.target,
        )

        # Reject duplicate request_id to prevent overwriting operation_history
        # and confusing cancel/status for concurrent operations
        with self._history_lock:
            if request.request_id in self.operation_history:
                logger.warning("Rejected duplicate request_id=%s", request.request_id)
                return ErrorResponse(
                    request_id=request.request_id,
                    message="Duplicate request_id",
                ).to_json()

            # Create response queue for this operation
            response_queue: asyncio.Queue[str] = asyncio.Queue()

            # Add to history as pending, storing branch/target for resume support
            self.operation_history[request.request_id] = OperationStatus(
                request_id=request.request_id,
                status="pending",
                branch=request.branch,
                target=request.target,
            )

        # Queue the operation
        queued_op = QueuedOperation(
            request_id=request.request_id,
            request=request,
            response_queue=response_queue,
        )
        await self.operation_queue.put(queued_op)
        logger.debug(
            "Enqueued operation: request_id=%s, queue_size=%d",
            request.request_id,
            self.operation_queue.qsize(),
        )

        # Send queued response immediately
        position = self._get_queue_position(request.request_id)
        queued_response = QueuedResponse(
            request_id=request.request_id,
            position=position,
        )
        writer.write(queued_response.to_json().encode() + b"\n")
        await writer.drain()

        # Wait for operation to complete or shutdown
        wait_task = asyncio.create_task(response_queue.get())
        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        done, _ = await asyncio.wait(
            {wait_task, shutdown_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if wait_task in done:
            shutdown_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await shutdown_task
            return wait_task.result()
        else:
            wait_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await wait_task
            with self._history_lock:
                status = self.operation_history.get(request.request_id)
                if status:
                    status.status = "failed"
                    status.error = "Server shutting down"
            return ErrorResponse(
                request_id=request.request_id,
                message="Server shutting down",
            ).to_json()

    def _get_queue_position(self, request_id: str) -> int:
        """Get the position of an operation in the queue."""
        assert self.operation_queue is not None
        # This is approximate since we can't easily iterate asyncio.Queue
        if self.current_operation == request_id:
            return 0
        return self.operation_queue.qsize()

    def _prune_history(self) -> None:
        """Remove oldest completed entries if history exceeds limit.

        Keeps completed/failed/cancelled entries up to MAX_HISTORY_SIZE // 2
        when the total history size exceeds MAX_HISTORY_SIZE.
        """
        with self._history_lock:
            if len(self.operation_history) <= MAX_HISTORY_SIZE:
                return

            # Find completed entries (not pending or in_progress)
            completed = [
                k
                for k, v in self.operation_history.items()
                if v.status in ("completed", "conflict", "failed", "cancelled")
            ]

            # Remove oldest completed entries, keeping half the max size
            entries_to_remove = len(completed) - MAX_HISTORY_SIZE // 2
            if entries_to_remove > 0:
                for key in completed[:entries_to_remove]:
                    del self.operation_history[key]

    async def _wait_for_sandbox_clean(self, branch: str) -> None:
        """Poll until the sandbox is clean (no rebase, uncommitted changes, or unpushed commits).

        Args:
            branch: Branch name to check for unpushed commits.
        """
        if not self.sandbox_path:
            return
        while not is_sandbox_clean(self.sandbox_path, branch):
            logger.debug("Waiting for sandbox to become clean (branch=%s)", branch)
            await asyncio.sleep(SANDBOX_POLL_INTERVAL)
        logger.info("Sandbox is clean, ready for next operation")

    async def _process_queue(self) -> None:
        """Process operations from the queue sequentially."""
        assert self.operation_queue is not None
        while True:
            try:
                # If there's a pending conflict, poll until sandbox is clean
                if self._conflict_branch:
                    await self._wait_for_sandbox_clean(self._conflict_branch)
                    self._conflict_branch = None

                # Get next operation
                queued_op = await self.operation_queue.get()

                # Check if cancelled
                with self._history_lock:
                    status = self.operation_history.get(queued_op.request_id)
                    is_cancelled = status and status.status == "cancelled"
                if is_cancelled:
                    logger.info(
                        "Skipping cancelled operation: request_id=%s",
                        queued_op.request_id,
                    )
                    await queued_op.response_queue.put(
                        ErrorResponse(
                            request_id=queued_op.request_id,
                            message="Operation was cancelled",
                        ).to_json()
                    )
                    self._prune_history()
                    continue

                # Execute the operation (blocking operations offloaded to thread pool)
                # The try/finally ensures current_operation and status are reset on any exit path,
                # including task cancellation during shutdown.
                try:
                    # Mark as in progress inside try so finally cleanup always runs
                    self.current_operation = queued_op.request_id
                    with self._history_lock:
                        status = self.operation_history.get(queued_op.request_id)
                        if status:
                            status.status = "in_progress"

                    op_type = "rebase" if isinstance(queued_op.request, RebaseRequest) else "merge"
                    logger.info(
                        "Starting %s operation: request_id=%s, branch=%s",
                        op_type,
                        queued_op.request_id,
                        queued_op.request.branch,
                    )
                    # Use single-threaded executor to prevent concurrent git operations
                    assert self._git_executor is not None
                    response = await asyncio.get_running_loop().run_in_executor(
                        self._git_executor,
                        self._execute_operation,
                        queued_op.request,
                    )

                    # Check if cancelled during execution - send cancel response instead
                    with self._history_lock:
                        status = self.operation_history.get(queued_op.request_id)
                        is_cancelled = status and status.status == "cancelled"
                    if is_cancelled:
                        await queued_op.response_queue.put(
                            ErrorResponse(
                                request_id=queued_op.request_id,
                                message="Operation was cancelled",
                            ).to_json()
                        )
                        self.current_operation = None
                        self._prune_history()
                        continue

                    await queued_op.response_queue.put(response)

                    # Update history
                    with self._history_lock:
                        status = self.operation_history.get(queued_op.request_id)
                        if status:
                            try:
                                parsed = (
                                    json.loads(response)
                                    if isinstance(response, (str, bytes, bytearray))
                                    else response
                                )
                                parsed_status = parsed.get("status")
                                if parsed_status == "success":
                                    status.status = "completed"
                                    status.result = parsed.get("result")
                                    logger.info(
                                        (
                                            "Operation completed successfully: "
                                            "request_id=%s, branch=%s"
                                        ),
                                        queued_op.request_id,
                                        queued_op.request.branch,
                                    )
                                elif parsed_status == "conflict":
                                    status.status = "conflict"
                                    status.result = {"conflicts": parsed.get("files", [])}
                                    # Track branch for polling - queue will block until clean
                                    self._conflict_branch = queued_op.request.branch
                                    logger.info(
                                        (
                                            "Operation has conflicts, will poll for clean state: "
                                            "request_id=%s, branch=%s, files=%s"
                                        ),
                                        queued_op.request_id,
                                        queued_op.request.branch,
                                        parsed.get("files", []),
                                    )
                                else:
                                    status.status = "failed"
                                    status.error = parsed.get("message")
                                    logger.error(
                                        "Operation failed: request_id=%s, branch=%s, error=%s",
                                        queued_op.request_id,
                                        queued_op.request.branch,
                                        parsed.get("message"),
                                    )
                            except Exception as e:
                                # Treat parse errors as failures in history
                                status.status = "failed"
                                status.error = str(e)

                except Exception as e:
                    logger.exception("Error executing operation")
                    error_response = ErrorResponse(
                        request_id=queued_op.request_id,
                        message=str(e),
                    )
                    await queued_op.response_queue.put(error_response.to_json())
                    with self._history_lock:
                        status = self.operation_history.get(queued_op.request_id)
                        if status:
                            status.status = "failed"
                            status.error = str(e)

                finally:
                    self.current_operation = None
                    self._prune_history()

            except asyncio.CancelledError:
                break

    def _execute_operation(
        self,
        request: RebaseRequest | MergeRequest,
    ) -> str:
        """Execute a rebase or merge operation (blocking).

        This method is synchronous and performs blocking subprocess calls.
        It should be called via run_in_executor to avoid blocking the event loop.
        """
        if self.sandbox_path is None:
            return ErrorResponse(
                request_id=request.request_id,
                message="Sandbox not initialized",
            ).to_json()

        # Create a progress callback that logs messages
        def progress_callback(message: str) -> None:
            logger.info("Operation %s progress: %s", request.request_id, message)

        if isinstance(request, RebaseRequest):
            rebase_result = rebase_in_sandbox(
                self.sandbox_path,
                request.branch,
                request.target,
                progress_callback=progress_callback,
            )
            return self._format_rebase_result(request.request_id, rebase_result, request.branch)
        elif isinstance(request, MergeRequest):
            merge_result = merge_in_sandbox(
                self.sandbox_path,
                request.branch,
                request.target,
            )
            return self._format_merge_result(request.request_id, merge_result, request.branch)
        else:
            return ErrorResponse(
                request_id=request.request_id,
                message="Unknown operation type",
            ).to_json()

    def _format_rebase_result(self, request_id: str, result: RebaseResult, branch: str) -> str:
        """Format a rebase result as a response.

        Args:
            request_id: The request ID for the response.
            result: The rebase operation result.
            branch: The branch to push (from the original request).
        """
        if result.success:
            # Check if operation was cancelled before pushing (side effect)
            with self._history_lock:
                status = self.operation_history.get(request_id)
                is_cancelled = status and status.status == "cancelled"
            if is_cancelled:
                logger.info(
                    "Skipping push for cancelled rebase: request_id=%s, branch=%s",
                    request_id,
                    branch,
                )
                return ErrorResponse(
                    request_id=request_id,
                    message="Operation was cancelled",
                ).to_json()

            # Push the result using the branch from the request
            # (not _get_current_branch which could fail in detached HEAD state)
            pushed = False
            if self.sandbox_path:
                push_success, push_error = push_from_sandbox(self.sandbox_path, branch, force=True)
                if not push_success:
                    logger.error(
                        "Rebase push failed: request_id=%s, branch=%s, error=%s",
                        request_id,
                        branch,
                        push_error,
                    )
                    return ErrorResponse(
                        request_id=request_id,
                        message=f"Rebase succeeded but push failed: {push_error}",
                    ).to_json()
                pushed = True

            message = "Rebase completed and pushed" if pushed else "Rebase completed"
            return SuccessResponse(
                request_id=request_id,
                result={"message": message},
            ).to_json()
        elif result.has_conflicts:
            return ConflictResponse(
                request_id=request_id,
                files=result.conflicts,
            ).to_json()
        else:
            logger.error(
                "Rebase failed: request_id=%s, branch=%s, error=%s",
                request_id,
                branch,
                result.error,
            )
            return ErrorResponse(
                request_id=request_id,
                message=result.error,
            ).to_json()

    def _format_merge_result(self, request_id: str, result: MergeResult, branch: str) -> str:
        """Format a merge result as a response.

        Args:
            request_id: The request ID for the response.
            result: The merge operation result.
            branch: The branch to push (from the original request).
        """
        if result.success:
            # Check if operation was cancelled before pushing (side effect)
            with self._history_lock:
                status = self.operation_history.get(request_id)
                is_cancelled = status and status.status == "cancelled"
            if is_cancelled:
                logger.info(
                    "Skipping push for cancelled merge: request_id=%s, branch=%s",
                    request_id,
                    branch,
                )
                return ErrorResponse(
                    request_id=request_id,
                    message="Operation was cancelled",
                ).to_json()

            # Push the result using the branch from the request
            # (not _get_current_branch which could fail in detached HEAD state)
            pushed = False
            if self.sandbox_path:
                push_success, push_error = push_from_sandbox(self.sandbox_path, branch, force=False)
                if not push_success:
                    logger.error(
                        "Merge push failed: request_id=%s, branch=%s, error=%s",
                        request_id,
                        branch,
                        push_error,
                    )
                    return ErrorResponse(
                        request_id=request_id,
                        message=f"Merge succeeded but push failed: {push_error}",
                    ).to_json()
                pushed = True

            message = "Merge completed and pushed" if pushed else "Merge completed"
            return SuccessResponse(
                request_id=request_id,
                result={"message": message},
            ).to_json()
        elif result.has_conflicts:
            return ConflictResponse(
                request_id=request_id,
                files=result.conflicts,
            ).to_json()
        else:
            logger.error(
                "Merge failed: request_id=%s, branch=%s, error=%s",
                request_id,
                branch,
                result.error,
            )
            return ErrorResponse(
                request_id=request_id,
                message=result.error,
            ).to_json()


async def run_server(
    socket_path: str = DEFAULT_SOCKET_PATH,
    repo_path: str = DEFAULT_REPO_PATH,
) -> None:
    """Run the sandbox server."""
    server = SandboxServer(
        repo_path=Path(repo_path),
        socket_path=socket_path,
    )

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()

    def handle_signal() -> None:
        logger.info("Received shutdown signal")
        server.shutdown()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except (NotImplementedError, RuntimeError):
            logger.warning("Signal handlers not supported; skipping registration for %s", sig)

    await server.start()


def main() -> None:
    """Entry point for the sandbox server."""
    _configure_logging()
    socket_path = os.environ.get("SANDBOX_SOCKET_PATH", DEFAULT_SOCKET_PATH)
    repo_path = os.environ.get("SANDBOX_REPO_PATH", DEFAULT_REPO_PATH)

    logger.info(f"Starting sandbox server with socket={socket_path}, repo={repo_path}")

    try:
        asyncio.run(run_server(socket_path, repo_path))
    except KeyboardInterrupt:
        logger.info("Server interrupted")
        sys.exit(0)


if __name__ == "__main__":
    main()
