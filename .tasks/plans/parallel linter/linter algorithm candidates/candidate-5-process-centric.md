# Candidate 5: Process-Centric Decomposition

## Overview

The parallel linter algorithm has significant process management complexity distributed across multiple concerns: process lifecycle, signal handling, snapshot management, result collection, and resource limiting. This analysis examines opportunities to isolate these cross-cutting process concerns into dedicated components.

## 1. Process Lifecycle Management

### Components Involved

**Startup (Lines 222-224)**
- `ProcessPoolExecutor` initialization with computed worker count
- Worker pool sizing: `min(len(phase_items), max_concurrency or max(1, available_cpus))`
- CPU count determination at startup: `_get_available_cpus()` using `sched_getaffinity` fallback to `cpu_count`

**Process Creation (Lines 224, 242)**
- Each linter task spawns as subprocess in isolated process tree
- POSIX: `setsid` for process group creation
- Windows: Job Object with kill-on-close semantics
- Parent process maintains tracking: `task -> process group/Job Object + snapshot_path`

**Monitoring (Lines 226-241)**
- `as_completed(futures)` for non-blocking collection
- Per-linter timeout enforcement with entire process tree termination
- Output capture with size limits or temp-file rollover
- Separate stdout/stderr streams with `errors='backslashreplace'` decoding

**Termination (Lines 237, 267)**
- Normal completion: subprocess exit collected via future
- Timeout: kill entire process tree (process group/Job Object)
- Fail-fast: hard-stop running tasks by terminating process groups
- SIGINT: terminate all running process groups

**Cleanup**
- Worker pool shutdown: `shutdown(wait=False, cancel_futures=True)`
- Process tree cleanup (automatic via process groups/Job Objects)
- No direct process object management exposed to caller

### Coordination Required

1. **Worker Pool <-> Task Submission**
   - Main process computes `max_workers` before creating pool
   - Submits `len(phase_items)` tasks, potentially exceeding worker count
   - Pool manages queueing automatically

2. **Parent <-> Child Processes**
   - Parent submits task with fileset, snapshot_path
   - Child runs subprocess, enforces timeout, captures output
   - Child returns `LinterResult` via future
   - Parent tracks process group/Job Object handle for kill capability

3. **Timeout Enforcer <-> Process Tree**
   - Worker process sets timeout on subprocess
   - On expiry, kills entire process tree (not just immediate child)
   - Returns `LinterResult{status=timeout}`

4. **Shutdown Coordinator <-> Multiple Process Groups**
   - On shutdown event, must terminate N concurrent process groups
   - Each group may contain multiple processes (linter + subprocesses)
   - Order-independent: terminate all in parallel

### Failure Modes

**Process Creation Failures**
- `OSError` if process limit reached: caught by `_run_linter_safe`, returned as `crashed`
- Fork failure on POSIX: propagates to future, caught in main loop
- Job Object creation failure on Windows: same propagation path

**Orphaned Processes**
- Timeout kill fails (process immune to signals): process group remains
- Parent crash before cleanup: process groups continue running
- Job Object not properly closed on Windows: processes survive parent

**Resource Exhaustion**
- Too many workers: system process/memory limits hit
- Worker process memory leak: affects all tasks on that worker
- File descriptor exhaustion: from output capture or temp files

**Zombie Processes**
- Child completes but parent hasn't read exit status
- Process group leader exits but members remain
- Mitigated by process group/Job Object cleanup

**Deadlock Scenarios**
- Output pipe buffer full, child blocked writing, parent blocked reading
- Mitigated by temp-file rollover for large outputs
- Worker thread blocked indefinitely on subprocess.wait()

### Isolation Opportunities

**Process Pool Manager Component**
```python
class ProcessPoolManager:
    """Manages worker pool lifecycle and sizing."""

    def __init__(self, available_cpus: int):
        self.available_cpus = available_cpus
        self.executor = None

    def create_pool(self, task_count: int, max_concurrency: Optional[int]) -> ProcessPoolExecutor:
        """Create sized pool for task count."""
        workers = min(task_count, max_concurrency or max(1, self.available_cpus))
        self.executor = ProcessPoolExecutor(max_workers=workers)
        return self.executor

    def shutdown(self, wait: bool = False, cancel_futures: bool = True):
        """Shutdown pool with configurable wait/cancel."""
        if self.executor:
            self.executor.shutdown(wait=wait, cancel_futures=cancel_futures)
```

**Process Tree Manager Component**
```python
class ProcessTreeManager:
    """Manages process tree creation and termination."""

    def __init__(self):
        self.process_groups = {}  # task_id -> process_group_handle

    def create_process_tree(self, task_id: str) -> ProcessGroupHandle:
        """Create isolated process tree for task."""
        # POSIX: prepare setsid setup
        # Windows: create Job Object
        handle = self._platform_create_tree()
        self.process_groups[task_id] = handle
        return handle

    def terminate_tree(self, task_id: str):
        """Terminate entire process tree."""
        handle = self.process_groups.get(task_id)
        if handle:
            self._platform_terminate_tree(handle)
            del self.process_groups[task_id]

    def terminate_all(self):
        """Terminate all tracked process trees."""
        for task_id in list(self.process_groups.keys()):
            self.terminate_tree(task_id)
```

**Subprocess Runner Component**
```python
class SubprocessRunner:
    """Runs subprocess with timeout, output capture, process tree isolation."""

    def run(
        self,
        cmd: List[str],
        timeout: float,
        process_tree: ProcessGroupHandle,
        output_limit: Optional[int] = None
    ) -> SubprocessResult:
        """
        Run subprocess in isolated tree with timeout and output capture.

        Returns: SubprocessResult{exit_code, stdout, stderr, timed_out}
        Raises: Never (all errors converted to SubprocessResult)
        """
        try:
            # Use process_tree handle for platform-specific setup
            # Capture stdout/stderr separately with size limits
            # Enforce timeout with tree termination
            # Decode with errors='backslashreplace'
            pass
        except TimeoutError:
            # Kill entire tree, return timed_out=True
            pass
        except Exception as e:
            # Return error result
            pass
```

**Benefits:**
- Process lifecycle isolated from linting logic
- Platform differences (POSIX/Windows) encapsulated
- Timeout/termination logic centralized
- Easier testing of process management independent of linter execution
- Clearer ownership of process group handles

## 2. Signal Handling and Shutdown Coordination

### Components Involved

**Signal Handler Setup (Lines 11-12)**
- `SIGINT` handler registered at startup
- Handler sets `shutdown_event` (shared state)
- Handler triggers executor shutdown, future cancellation, process group termination
- Handler triggers snapshot restoration for in-flight mutators

**Shutdown Event Propagation (Lines 227-228, 237)**
- `shutdown_event` checked in `as_completed` loop before processing results
- On `--fail-fast` failure: set `shutdown_event`, cancel futures, terminate tasks
- Late results ignored if shutdown event set

**Executor Shutdown (Lines 237, 267)**
- Called with `wait=False, cancel_futures=True`
- Pending futures marked cancelled
- Running tasks must be separately terminated (executor doesn't kill processes)

**Process Group Termination (Lines 237, 267)**
- Iterate over tracked process groups
- Send termination signal to each group
- POSIX: `killpg(process_group_id, SIGTERM)` or `SIGKILL`
- Windows: close Job Object handle (terminates all members)

**Snapshot Restoration (Lines 237, 267)**
- Identify in-flight mutating tasks at shutdown time
- Restore snapshots created in main process before task submission
- Atomic restoration via `os.replace` or git checkout

**Exit Code (Line 268)**
- Return 130 on SIGINT/KeyboardInterrupt

### Coordination Required

1. **Signal Handler <-> Main Event Loop**
   - Handler sets flag (`shutdown_event`)
   - Event loop checks flag before processing each result
   - Race condition: result processing started before flag checked
   - Mitigation: generation counter to ignore late results

2. **Shutdown Event <-> Executor**
   - Set event, then call `executor.shutdown()`
   - Executor cancels pending futures (not yet started)
   - Running futures continue until explicitly killed

3. **Shutdown Event <-> Process Groups**
   - Must terminate N concurrent process groups
   - Each group tracked by main process via handle
   - Termination may fail (process immune, already dead)
   - Best-effort: terminate all, don't wait for confirmation

4. **Shutdown Event <-> Snapshot Restoration**
   - Identify which tasks were in-flight (submitted but not completed)
   - Retrieve snapshot paths from task tracking
   - Restore files atomically
   - Must complete before process exit

5. **Fail-Fast <-> Shutdown Event**
   - Fail-fast uses same shutdown mechanism as SIGINT
   - Additional step: bump generation counter
   - Ensures consistent shutdown behavior

### Failure Modes

**Signal Handler Failures**
- Exception in signal handler: handler exits, SIGINT becomes default (process terminates)
- Handler blocked on I/O: shutdown delayed
- Nested signals: second SIGINT during shutdown may interrupt cleanup

**Race Conditions**
- Result processed after shutdown event set: handled by generation counter
- Process group terminated while being killed: double-terminate is safe
- Snapshot restoration concurrent with process writing: process killed first, but non-atomic

**Incomplete Shutdown**
- Process group termination fails: processes continue running
- Snapshot restoration fails: files left in intermediate state
- Executor shutdown hangs: main process blocked
- Mitigated by `wait=False` but pending futures still in memory

**Exit Code Confusion**
- SIGINT during normal failure: exit 130 overrides exit 1
- Multiple failures during shutdown: only one exit code possible
- Solution: prioritize SIGINT exit code

**Reentrancy**
- Second SIGINT during cleanup: handler called again
- May corrupt shared state
- Solution: set flag to prevent reentrant execution

### Isolation Opportunities

**Shutdown Coordinator Component**
```python
class ShutdownCoordinator:
    """Coordinates graceful shutdown across multiple subsystems."""

    def __init__(self):
        self.shutdown_event = threading.Event()
        self.in_shutdown = threading.Lock()
        self.shutdown_callbacks = []

    def register_callback(self, callback: Callable[[], None]):
        """Register cleanup callback for shutdown."""
        self.shutdown_callbacks.append(callback)

    def initiate_shutdown(self, reason: str):
        """
        Initiate coordinated shutdown.

        Thread-safe, idempotent. First call wins.
        """
        with self.in_shutdown:
            if self.shutdown_event.is_set():
                return  # Already shutting down

            self.shutdown_event.set()
            logger.info(f"Shutdown initiated: {reason}")

            # Execute callbacks in registration order
            for callback in self.shutdown_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.error(f"Shutdown callback failed: {e}")

    def is_shutdown(self) -> bool:
        """Check if shutdown initiated."""
        return self.shutdown_event.is_set()
```

**Signal Handler Component**
```python
class SignalHandler:
    """Manages SIGINT handling with coordinated shutdown."""

    def __init__(self, coordinator: ShutdownCoordinator):
        self.coordinator = coordinator
        self.original_handlers = {}

    def setup(self):
        """Install signal handlers."""
        self.original_handlers[signal.SIGINT] = signal.signal(
            signal.SIGINT, self._handle_sigint
        )

    def _handle_sigint(self, signum, frame):
        """Handle SIGINT with coordinated shutdown."""
        self.coordinator.initiate_shutdown("SIGINT")
        # Note: don't raise KeyboardInterrupt here, let main loop detect

    def restore(self):
        """Restore original signal handlers."""
        for sig, handler in self.original_handlers.items():
            signal.signal(sig, handler)
```

**Cleanup Orchestrator Component**
```python
class CleanupOrchestrator:
    """Orchestrates cleanup of process pools, snapshots, etc."""

    def __init__(
        self,
        pool_manager: ProcessPoolManager,
        tree_manager: ProcessTreeManager,
        snapshot_manager: SnapshotManager,
    ):
        self.pool_manager = pool_manager
        self.tree_manager = tree_manager
        self.snapshot_manager = snapshot_manager

    def cleanup_all(self):
        """Execute full cleanup sequence."""
        # Order matters: terminate processes before restoring snapshots
        self.tree_manager.terminate_all()
        self.pool_manager.shutdown(wait=False, cancel_futures=True)
        self.snapshot_manager.restore_all_inflight()
```

**Integration Pattern**
```python
# Setup
coordinator = ShutdownCoordinator()
signal_handler = SignalHandler(coordinator)
signal_handler.setup()

cleanup = CleanupOrchestrator(pool_manager, tree_manager, snapshot_manager)
coordinator.register_callback(cleanup.cleanup_all)

# Event loop
for future in as_completed(futures):
    if coordinator.is_shutdown():
        break  # Stop processing results
    # ... process result

# Fail-fast
if fail_fast and result.is_failure():
    coordinator.initiate_shutdown("fail-fast")
```

**Benefits:**
- Signal handling isolated from shutdown logic
- Shutdown coordination explicit and testable
- Cleanup order controlled by orchestrator
- Idempotent shutdown (safe to call multiple times)
- Clear callback registration pattern
- No shared state between handler and event loop (only event flag)

## 3. Snapshot Management for Mutators

### Components Involved

**Snapshot Creation (Line 224)**
- Occurs in main process before task submission
- For each mutating linter task with fileset_chunk
- Creates temporary snapshot of fileset_chunk
- Atomic creation: temp file -> rename
- Stores `snapshot_path` in task tracking

**Snapshot Storage**
- Task tracking: `task -> process_group + snapshot_path`
- Snapshot per task (not per linter, not per phase)
- Multiple snapshots may exist for same linter (different chunks)

**Snapshot Restoration (Lines 193, 237, 267)**
- **Crash recovery (Line 193):** Restore only crashed task's fileset from snapshot
- **Fail-fast (Line 237):** Restore snapshots for in-flight mutating tasks
- **SIGINT (Line 267):** Restore snapshots for in-flight mutating tasks
- Atomic restoration: `os.replace` or git checkout

**Snapshot Cleanup**
- Implicit: snapshots in temp directory, cleaned up by OS
- Explicit cleanup not shown in flowchart
- May leave debris if process crashes before restoration

### Coordination Required

1. **Main Process <-> Snapshot Creation**
   - Main process determines which tasks are mutating
   - Main process reads fileset_chunk
   - Main process creates snapshot before submitting task
   - Snapshot path passed to worker process

2. **Snapshot Path <-> Worker Process**
   - Worker receives snapshot_path parameter
   - Worker does not use snapshot (only for recovery)
   - Worker may modify original files
   - Worker returns `files_modified` flag

3. **Task Tracking <-> Snapshot Restoration**
   - Main process tracks: `task_id -> snapshot_path`
   - On crash/shutdown, identify in-flight tasks
   - Retrieve snapshot paths for those tasks
   - Restore files from snapshot

4. **Snapshot Restoration <-> File System**
   - Restore must be atomic (per file)
   - Use `os.replace` (atomic on POSIX/Windows)
   - Or use git checkout (requires clean working tree)
   - Original files may be deleted, modified, or unchanged

5. **Phase Completion <-> Snapshot Cleanup**
   - After phase completes successfully, snapshots no longer needed
   - Should be cleaned up to free disk space
   - Not shown in flowchart (potential leak)

### Failure Modes

**Snapshot Creation Failures**
- Disk full: cannot create snapshot
- Permission denied: cannot read source files
- File deleted between check and snapshot: `FileNotFoundError`
- Large files: snapshot creation slow, delays task submission

**Snapshot Corruption**
- File modified during snapshot creation: inconsistent snapshot
- Snapshot file truncated: restoration fails
- Temp directory cleared during execution: snapshot lost

**Restoration Failures**
- Original file deleted: `os.replace` target doesn't exist (safe, creates new)
- Original file locked: restoration blocked (Windows)
- Snapshot file deleted: cannot restore
- Disk full: cannot write restored file

**Partial Restoration**
- Multiple files in snapshot, restoration fails mid-way
- Some files restored, others not
- Leaves working tree in inconsistent state

**Resource Leaks**
- Snapshot created but never cleaned up
- Disk space exhausted by abandoned snapshots
- Temp directory fills up over multiple runs

**Race Conditions**
- Process writing file while being killed
- Restoration concurrent with write
- Process killed, file in unknown state, restoration may restore partial write

### Isolation Opportunities

**Snapshot Manager Component**
```python
class SnapshotManager:
    """Manages file snapshots for mutating linter tasks."""

    def __init__(self, temp_dir: Path):
        self.temp_dir = temp_dir
        self.snapshots = {}  # task_id -> snapshot_path
        self.inflight_tasks = set()  # tasks currently running

    def create_snapshot(self, task_id: str, fileset: List[Path]) -> Path:
        """
        Create atomic snapshot of fileset.

        Returns: Path to snapshot directory
        Raises: OSError if snapshot creation fails
        """
        snapshot_dir = self.temp_dir / f"snapshot_{task_id}"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        for file_path in fileset:
            try:
                # Copy file to snapshot dir, preserving relative structure
                snapshot_file = snapshot_dir / file_path.name
                self._atomic_copy(file_path, snapshot_file)
            except FileNotFoundError:
                # File deleted before snapshot, skip
                continue

        self.snapshots[task_id] = snapshot_dir
        return snapshot_dir

    def mark_inflight(self, task_id: str):
        """Mark task as in-flight (submitted to executor)."""
        self.inflight_tasks.add(task_id)

    def mark_completed(self, task_id: str):
        """Mark task as completed, cleanup snapshot."""
        self.inflight_tasks.discard(task_id)
        self._cleanup_snapshot(task_id)

    def restore_snapshot(self, task_id: str):
        """
        Restore files from snapshot atomically.

        Best-effort: logs errors but doesn't raise.
        """
        snapshot_dir = self.snapshots.get(task_id)
        if not snapshot_dir or not snapshot_dir.exists():
            logger.warning(f"No snapshot found for task {task_id}")
            return

        for snapshot_file in snapshot_dir.iterdir():
            try:
                original_file = self._resolve_original_path(snapshot_file)
                self._atomic_restore(snapshot_file, original_file)
            except Exception as e:
                logger.error(f"Failed to restore {snapshot_file}: {e}")

        self._cleanup_snapshot(task_id)

    def restore_all_inflight(self):
        """Restore snapshots for all in-flight tasks."""
        for task_id in list(self.inflight_tasks):
            self.restore_snapshot(task_id)

    def _atomic_copy(self, src: Path, dst: Path):
        """Copy file atomically using temp + rename."""
        temp_dst = dst.with_suffix(dst.suffix + '.tmp')
        shutil.copy2(src, temp_dst)
        os.replace(temp_dst, dst)

    def _atomic_restore(self, snapshot_file: Path, original_file: Path):
        """Restore file atomically using os.replace."""
        os.replace(snapshot_file, original_file)

    def _cleanup_snapshot(self, task_id: str):
        """Delete snapshot directory."""
        snapshot_dir = self.snapshots.pop(task_id, None)
        if snapshot_dir and snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
```

**Fileset Snapshot Strategy**
```python
class FilesetSnapshot:
    """Represents a snapshot of a file set with metadata."""

    def __init__(self, snapshot_dir: Path, fileset: List[Path]):
        self.snapshot_dir = snapshot_dir
        self.fileset = fileset
        self.created_at = time.time()
        self.file_hashes = {}  # file -> hash (for verification)

    def verify_integrity(self) -> bool:
        """Verify snapshot integrity before restoration."""
        for file_path in self.fileset:
            snapshot_file = self.snapshot_dir / file_path.name
            if not snapshot_file.exists():
                return False
            # Could verify hash if stored
        return True

    def size_bytes(self) -> int:
        """Calculate total snapshot size."""
        total = 0
        for file_path in self.snapshot_dir.iterdir():
            total += file_path.stat().st_size
        return total
```

**Integration with Task Submission**
```python
# Before submitting mutating task
if linter.mutates_files:
    snapshot_path = snapshot_manager.create_snapshot(task_id, fileset_chunk)
    snapshot_manager.mark_inflight(task_id)
else:
    snapshot_path = None

future = executor.submit(_run_linter_safe, linter, fileset_chunk, chunk_id, snapshot_path)

# After task completes
result = future.result()
if result.status != 'crashed':
    snapshot_manager.mark_completed(task_id)
else:
    snapshot_manager.restore_snapshot(task_id)
```

**Benefits:**
- Snapshot lifecycle isolated from linting logic
- Atomic operations for create/restore
- Explicit tracking of in-flight tasks
- Automatic cleanup on completion
- Centralized error handling for snapshot failures
- Can add verification, size limits, retention policies
- Testable snapshot behavior independent of linter execution

## 4. Result Collection and Ordering

### Components Involved

**Result Generation (Lines 242-243)**
- Worker process executes linter subprocess
- Captures stdout, stderr separately
- Strips ANSI, normalizes paths to repo-relative
- Constructs `LinterResult{status, exit_code, stdout, stderr, file_list, files_modified, chunk_id}`
- Returns via future

**Result Collection (Lines 226-241)**
- Main process uses `as_completed(futures)` for non-blocking collection
- No head-of-line blocking: results collected as they complete
- Each result includes `chunk_id` for ordering

**Output Buffering (Lines 225, 232-234)**
- Text mode only (YAML mode skips to final output)
- Initialize: `output_buffer = {}`, `next_expected_chunk_id = 0`
- On result: buffer output keyed by `chunk_id`
- Sliding-window flush: emit outputs in `chunk_id` order

**Result Aggregation (Line 184)**
- Merge phase results into `all_results` (main thread)
- Aggregate chunk results per linter (multiple chunks -> single linter result)
- Deduplicate diagnostics by `hash(file, line, col, rule_id)`

**Result Storage**
- `all_results` dictionary: `linter -> LinterResult`
- Includes skipped linters: `skipped(no_matching_files)`, `skipped(preflight_failed)`

### Coordination Required

1. **Worker Process <-> Future**
   - Worker returns `LinterResult` via future
   - Result serialized (pickle) for inter-process communication
   - Large results (big stdout) may hit pickle size limits

2. **as_completed <-> Output Buffer**
   - `as_completed` yields results in completion order (non-deterministic)
   - Output buffer reorders by `chunk_id`
   - Sliding window ensures outputs emitted as early as possible in order

3. **Output Buffer <-> Console**
   - Buffered outputs printed to stdout/stderr
   - Must not interleave with linter subprocess output (captured separately)
   - Sliding window prevents long delays (print as soon as in-order)

4. **Chunk Results <-> Linter Aggregation**
   - Multiple chunk results for same linter
   - Aggregation: merge diagnostics, combine file_lists, OR files_modified flags
   - Deduplication: diagnostics must be hashable and comparable

5. **Shutdown Event <-> Result Collection**
   - `as_completed` loop checks `shutdown_event` before processing result
   - Late results (after shutdown) ignored
   - Generation counter distinguishes cancelled vs valid results

### Failure Modes

**Result Serialization Failures**
- Large stdout/stderr exceeds pickle size limit
- Non-picklable objects in `LinterResult`
- Worker crash before returning result: future raises exception

**Buffer Overflow**
- All tasks complete except chunk 0: buffer holds N-1 outputs
- Memory exhaustion if many large outputs buffered
- Mitigation: temp-file rollover for large outputs

**Head-of-Line Blocking in Buffer**
- Chunk 0 takes very long, chunks 1-N complete quickly
- No output until chunk 0 completes (sliding window blocked)
- User sees no progress despite 99% completion

**Deduplication Failures**
- Hash collision: different diagnostics with same hash
- Non-deterministic diagnostic data (timestamps, etc.)
- Diagnostics lost due to false-positive duplicate detection

**Aggregation Inconsistency**
- Chunk 0 says `files_modified=True`, chunk 1 says `files_modified=False`
- Aggregation ORs the flags: overall `files_modified=True`
- May not reflect actual state if chunk 0 crashed after returning

**Late Result Processing**
- Shutdown event set, but result already retrieved from `as_completed`
- Result processed, output printed, but should have been ignored
- Mitigation: generation counter, check shutdown before processing

### Isolation Opportunities

**Result Collector Component**
```python
class ResultCollector:
    """Collects and aggregates linter results from concurrent tasks."""

    def __init__(self):
        self.chunk_results = defaultdict(list)  # linter -> [chunk_result, ...]
        self.aggregated_results = {}  # linter -> LinterResult

    def add_chunk_result(self, linter: Linter, result: LinterResult):
        """Add a chunk result for aggregation."""
        self.chunk_results[linter].append(result)

    def aggregate_linter_results(self, linter: Linter) -> LinterResult:
        """
        Aggregate all chunk results for a linter.

        Combines diagnostics, file_lists, ORs files_modified.
        """
        chunks = self.chunk_results[linter]
        if not chunks:
            return LinterResult(status='skipped')

        # Merge diagnostics with deduplication
        all_diagnostics = []
        seen_hashes = set()
        for chunk in chunks:
            for diagnostic in chunk.diagnostics:
                diag_hash = hash((diagnostic.file, diagnostic.line,
                                 diagnostic.col, diagnostic.rule_id))
                if diag_hash not in seen_hashes:
                    all_diagnostics.append(diagnostic)
                    seen_hashes.add(diag_hash)

        # Combine other fields
        combined = LinterResult(
            status=self._aggregate_status(chunks),
            exit_code=self._aggregate_exit_code(chunks),
            diagnostics=all_diagnostics,
            files_modified=any(c.files_modified for c in chunks),
            file_list=self._merge_file_lists(chunks),
        )

        self.aggregated_results[linter] = combined
        return combined

    def get_all_results(self) -> Dict[Linter, LinterResult]:
        """Get all aggregated results."""
        # Finalize any pending aggregations
        for linter in self.chunk_results:
            if linter not in self.aggregated_results:
                self.aggregate_linter_results(linter)
        return self.aggregated_results
```

**Output Buffer Component**
```python
class OrderedOutputBuffer:
    """Buffers outputs and emits them in chunk_id order."""

    def __init__(self):
        self.buffer = {}  # chunk_id -> output_string
        self.next_expected_id = 0

    def add_output(self, chunk_id: int, output: str):
        """Buffer output for chunk."""
        self.buffer[chunk_id] = output
        self._flush_ready()

    def _flush_ready(self):
        """Flush all outputs that are now in order."""
        while self.next_expected_id in self.buffer:
            output = self.buffer.pop(self.next_expected_id)
            print(output, end='')
            self.next_expected_id += 1

    def flush_all(self):
        """Flush remaining buffered outputs (at end of execution)."""
        remaining_ids = sorted(self.buffer.keys())
        for chunk_id in remaining_ids:
            output = self.buffer.pop(chunk_id)
            print(output, end='')
        self.next_expected_id = remaining_ids[-1] + 1 if remaining_ids else self.next_expected_id

    def pending_count(self) -> int:
        """Count of buffered outputs not yet flushed."""
        return len(self.buffer)
```

**Result Stream Handler Component**
```python
class ResultStreamHandler:
    """Handles streaming results from as_completed with ordering and shutdown."""

    def __init__(
        self,
        futures: List[Future],
        shutdown_coordinator: ShutdownCoordinator,
        output_buffer: OrderedOutputBuffer,
        yaml_mode: bool,
    ):
        self.futures = futures
        self.shutdown_coordinator = shutdown_coordinator
        self.output_buffer = output_buffer
        self.yaml_mode = yaml_mode
        self.generation = 0

    def collect_results(self) -> Dict[Linter, LinterResult]:
        """
        Collect all results with ordered output and shutdown handling.

        Returns: Partial results if shutdown initiated.
        """
        collector = ResultCollector()

        for future in as_completed(self.futures):
            if self.shutdown_coordinator.is_shutdown():
                break  # Stop processing new results

            try:
                result = future.result()
            except Exception as e:
                logger.error(f"Future raised exception: {e}")
                continue

            # Add to collector
            collector.add_chunk_result(result.linter, result)

            # Handle output
            if not self.yaml_mode:
                output = self._format_output(result)
                self.output_buffer.add_output(result.chunk_id, output)

            # Check fail-fast
            if self._should_fail_fast(result):
                self.shutdown_coordinator.initiate_shutdown("fail-fast")
                self.generation += 1  # Invalidate in-flight results

        # Flush remaining outputs
        if not self.yaml_mode:
            self.output_buffer.flush_all()

        return collector.get_all_results()

    def _format_output(self, result: LinterResult) -> str:
        """Format result for text output."""
        # ... formatting logic
        pass

    def _should_fail_fast(self, result: LinterResult) -> bool:
        """Check if result should trigger fail-fast."""
        # ... fail-fast logic
        pass
```

**Integration Pattern**
```python
# Setup
shutdown_coordinator = ShutdownCoordinator()
output_buffer = OrderedOutputBuffer()
stream_handler = ResultStreamHandler(futures, shutdown_coordinator, output_buffer, yaml_mode)

# Collect results
all_results = stream_handler.collect_results()

# Results are aggregated, ordered, and shutdown-aware
```

**Benefits:**
- Result collection isolated from output formatting
- Aggregation logic centralized and testable
- Output ordering explicit and configurable
- Shutdown handling built into stream processing
- Clear separation: collection vs buffering vs aggregation
- Can swap output buffer implementation (file-backed, memory-limited, etc.)
- Can add metrics (result rate, buffer size, etc.)

## 5. Resource Limits and ARG_MAX Chunking

### Components Involved

**CPU Limit (Lines 4, 159, 222)**
- Computed once at startup: `_get_available_cpus()`
- Uses `os.sched_getaffinity(0)` if available, else `os.cpu_count() or 1`
- Used for worker pool sizing
- Preflight workers: `min(len(selected), min(32, max(1, available_cpus * 2)))`
- Execution workers: `min(len(phase_items), max_concurrency or max(1, available_cpus))`

**ARG_MAX Chunking (Lines 175-176)**
- Fileset split into chunks to respect OS argument length limit
- `_chunk_fileset_for_arg_max(fileset, base_cmd_len, env_len, safety_margin=2KB)`
- Budget calculation: `ARG_MAX - base_cmd_len - env_len - safety_margin`
- Base command: `len(exe + flags + config)`
- Environment: `_env_size(os.environ)`
- Each chunk assigned sequential `chunk_id`

**Memory Limits**
- Output capture with size limit or temp-file rollover
- Prevents memory exhaustion from large subprocess outputs
- Not explicitly shown in flowchart, but mentioned in line 242

**Timeout Limits (Line 242)**
- Per-linter timeout enforced on subprocess
- Entire process tree killed on timeout
- Prevents runaway linter processes

**Worker Pool Limits (Lines 159, 222)**
- Preflight: capped at 32 workers
- Execution: capped at task count or `max_concurrency`
- Prevents system overload from too many workers

### Coordination Required

1. **CPU Detection <-> Worker Pool Sizing**
   - CPU count computed once at startup
   - Used for both preflight and execution pools
   - Different formulas: preflight `2x` CPU, execution `1x` CPU
   - Caps: preflight `min(32, ...)`, execution `min(task_count, ...)`

2. **ARG_MAX Budget <-> Command Construction**
   - Budget computed before chunking
   - Accounts for fixed args + environment + margin
   - Chunking must stay within budget
   - Each chunk generates separate subprocess invocation

3. **Chunk Count <-> Worker Pool**
   - Chunking may create more tasks than workers
   - Worker pool size: `min(len(phase_items), ...)`
   - Queue depth: `len(phase_items) - max_workers`
   - Large queue if many small chunks

4. **Fileset Size <-> Chunk Count**
   - Large fileset -> many chunks
   - Many chunks -> many tasks -> deeper queue
   - Each chunk processed sequentially by worker
   - Total time: `sum(chunk_times) / workers`

5. **Environment Size <-> ARG_MAX Budget**
   - Environment size computed once: `_env_size(os.environ)`
   - Assumed constant across all chunks
   - Large environment reduces available arg budget
   - May force smaller chunks

### Failure Modes

**ARG_MAX Overflow**
- Budget calculation error: chunk exceeds ARG_MAX
- Subprocess fails with `E2BIG` (Argument list too long)
- Returned as `LinterResult{status=crashed}`

**ARG_MAX Underflow**
- Budget too conservative: single file exceeds budget
- Impossible to chunk: no valid chunk size
- Error: cannot run linter on this fileset

**CPU Count Detection Failure**
- `sched_getaffinity` unavailable: fallback to `cpu_count`
- `cpu_count` returns `None`: fallback to 1
- May under-utilize or over-utilize system

**Worker Starvation**
- Many chunks, few workers: high queue depth
- Long-running chunks block short chunks
- No work-stealing or prioritization

**Worker Oversubscription**
- `max_concurrency` set too high
- System process/memory limits hit
- Workers crash or hang

**Memory Exhaustion from Output**
- Many tasks with large outputs
- All buffered in memory simultaneously
- OOM if total exceeds available memory
- Mitigation: temp-file rollover (not detailed in flowchart)

**Timeout Too Short**
- Linter needs longer than timeout
- Killed prematurely, reported as timeout
- No per-linter timeout configuration shown

**Timeout Too Long**
- Hung linter not killed for extended period
- Blocks worker, delays other tasks
- No overall phase timeout

### Isolation Opportunities

**CPU Detector Component**
```python
class CPUDetector:
    """Detects available CPU count with fallbacks."""

    @staticmethod
    def get_available_cpus() -> int:
        """
        Get available CPU count.

        Returns: Available CPU count (minimum 1)
        """
        try:
            # Prefer sched_getaffinity (respects cgroups, taskset)
            return len(os.sched_getaffinity(0))
        except AttributeError:
            # Fallback to cpu_count (may overcount in containers)
            return os.cpu_count() or 1
```

**ARG_MAX Chunker Component**
```python
class ArgMaxChunker:
    """Chunks file lists to respect OS argument length limits."""

    def __init__(self, platform: str = sys.platform):
        self.platform = platform
        self.arg_max = self._get_arg_max()

    def _get_arg_max(self) -> int:
        """Get platform ARG_MAX limit."""
        try:
            return os.sysconf('SC_ARG_MAX')
        except (AttributeError, ValueError):
            # Windows or sysconf unavailable
            return 32767 if self.platform == 'win32' else 131072

    def chunk_fileset(
        self,
        fileset: List[Path],
        base_cmd: List[str],
        env: Dict[str, str],
        safety_margin: int = 2048,
    ) -> List[List[Path]]:
        """
        Chunk fileset to respect ARG_MAX.

        Args:
            fileset: Files to chunk
            base_cmd: Fixed command prefix (exe, flags, config)
            env: Environment variables
            safety_margin: Safety margin in bytes

        Returns: List of file chunks
        Raises: ValueError if single file exceeds budget
        """
        # Calculate budget
        base_len = sum(len(arg) + 1 for arg in base_cmd)  # +1 for space/null
        env_len = sum(len(k) + len(v) + 2 for k, v in env.items())  # +2 for =\0
        budget = self.arg_max - base_len - env_len - safety_margin

        if budget <= 0:
            raise ValueError("Base command and environment exceed ARG_MAX")

        # Chunk files
        chunks = []
        current_chunk = []
        current_size = 0

        for file_path in fileset:
            file_arg_len = len(str(file_path)) + 1  # +1 for space/null

            if file_arg_len > budget:
                raise ValueError(f"Single file exceeds ARG_MAX budget: {file_path}")

            if current_size + file_arg_len > budget:
                # Start new chunk
                chunks.append(current_chunk)
                current_chunk = [file_path]
                current_size = file_arg_len
            else:
                # Add to current chunk
                current_chunk.append(file_path)
                current_size += file_arg_len

        if current_chunk:
            chunks.append(current_chunk)

        return chunks
```

**Worker Pool Sizer Component**
```python
class WorkerPoolSizer:
    """Computes worker pool sizes based on task count and CPU availability."""

    def __init__(self, available_cpus: int):
        self.available_cpus = available_cpus

    def compute_preflight_workers(self, linter_count: int) -> int:
        """
        Compute worker count for preflight testing.

        Higher concurrency than execution (I/O bound).
        """
        return min(linter_count, min(32, max(1, self.available_cpus * 2)))

    def compute_execution_workers(
        self,
        task_count: int,
        max_concurrency: Optional[int] = None,
    ) -> int:
        """
        Compute worker count for linter execution.

        Lower concurrency than preflight (CPU bound).
        """
        default_workers = max(1, self.available_cpus)
        workers = max_concurrency or default_workers
        return min(task_count, workers)
```

**Resource Budget Component**
```python
class ResourceBudget:
    """Manages resource budgets for task execution."""

    def __init__(self, arg_max: int, env_size: int):
        self.arg_max = arg_max
        self.env_size = env_size

    def calculate_arg_budget(
        self,
        base_cmd: List[str],
        safety_margin: int = 2048,
    ) -> int:
        """
        Calculate available argument budget.

        Returns: Available bytes for file arguments
        """
        base_len = sum(len(arg) + 1 for arg in base_cmd)
        budget = self.arg_max - base_len - self.env_size - safety_margin
        return max(0, budget)

    def validate_budget(self, base_cmd: List[str]) -> None:
        """
        Validate that budget is positive.

        Raises: ValueError if no budget available
        """
        budget = self.calculate_arg_budget(base_cmd)
        if budget <= 0:
            raise ValueError(
                f"Base command and environment exceed ARG_MAX: "
                f"need {-budget} more bytes"
            )
```

**Integration Pattern**
```python
# Setup
cpu_count = CPUDetector.get_available_cpus()
chunker = ArgMaxChunker()
pool_sizer = WorkerPoolSizer(cpu_count)
budget = ResourceBudget(chunker.arg_max, _env_size(os.environ))

# Preflight
preflight_workers = pool_sizer.compute_preflight_workers(len(linters))
with ThreadPoolExecutor(max_workers=preflight_workers) as executor:
    # ... preflight tests

# Execution
for phase in phases:
    # Chunk filesets
    phase_items = []
    for linter in phase.linters:
        fileset = fileset_by_linter[linter]
        base_cmd = [linter.exe] + linter.flags + linter.config_args

        try:
            budget.validate_budget(base_cmd)
            chunks = chunker.chunk_fileset(fileset, base_cmd, os.environ)
            for chunk_id, chunk in enumerate(chunks):
                phase_items.append((linter, chunk, chunk_id))
        except ValueError as e:
            # Handle budget error
            pass

    # Execute phase
    workers = pool_sizer.compute_execution_workers(len(phase_items))
    with ProcessPoolExecutor(max_workers=workers) as executor:
        # ... execute phase
```

**Benefits:**
- Resource detection isolated and testable
- Chunking logic centralized
- Worker sizing explicit with documented formulas
- Budget calculation separated from chunking
- Platform differences encapsulated
- Clear error messages for budget violations
- Easy to add resource metrics, logging, tuning

## Summary of Process-Centric Decomposition Opportunities

### Key Insights

1. **Process management is deeply embedded** in the main algorithm, mixing lifecycle, signals, snapshots, results, and resources.

2. **Five major process concerns identified**, each with substantial complexity and failure modes.

3. **Coordination patterns are implicit**, making it difficult to reason about thread-safety, shutdown ordering, and failure recovery.

4. **Failure modes are diverse** and span crashes, races, resource exhaustion, partial failures, and cleanup failures.

5. **Isolation is feasible** for all five concerns with clear component boundaries and well-defined interfaces.

### Decomposition Strategy

**Phase 1: Extract Process Infrastructure**
- `ProcessPoolManager` - pool lifecycle
- `ProcessTreeManager` - tree creation/termination
- `SubprocessRunner` - isolated subprocess execution

**Phase 2: Extract Coordination Infrastructure**
- `ShutdownCoordinator` - unified shutdown mechanism
- `SignalHandler` - SIGINT with coordinated shutdown
- `CleanupOrchestrator` - ordered cleanup sequence

**Phase 3: Extract Snapshot Infrastructure**
- `SnapshotManager` - snapshot lifecycle
- `FilesetSnapshot` - snapshot metadata and verification

**Phase 4: Extract Result Infrastructure**
- `ResultCollector` - aggregation logic
- `OrderedOutputBuffer` - ordered output emission
- `ResultStreamHandler` - streaming with shutdown

**Phase 5: Extract Resource Infrastructure**
- `CPUDetector` - CPU count detection
- `ArgMaxChunker` - ARG_MAX-aware chunking
- `WorkerPoolSizer` - worker count computation
- `ResourceBudget` - budget calculation and validation

### Benefits of Decomposition

**Testability**
- Each component testable in isolation
- Mock process creation, signal delivery, file I/O
- Test failure modes without system-level integration

**Reliability**
- Explicit error handling boundaries
- Centralized failure recovery logic
- Clear ownership of resources

**Maintainability**
- Process concerns separated from linting logic
- Platform differences isolated
- Easy to add features (metrics, rate limiting, etc.)

**Flexibility**
- Swap implementations (different snapshot strategies, output formats)
- Adjust resource policies (worker counts, timeouts, budgets)
- Support new platforms with minimal changes

### Risks and Trade-offs

**Complexity Increase**
- More components = more interfaces to maintain
- Coordination logic now distributed across components
- Learning curve for new contributors

**Performance Overhead**
- Additional abstraction layers
- Potential for inefficient cross-component calls
- Serialization overhead for process results

**Integration Challenges**
- Components must compose correctly
- Shutdown ordering critical
- State management across components

### Recommended Approach

1. **Start with high-value, low-risk components**: `CPUDetector`, `ArgMaxChunker` (pure functions, no state)

2. **Progress to infrastructure with clear boundaries**: `SnapshotManager`, `ResultCollector`

3. **Tackle coordination last**: `ShutdownCoordinator`, `CleanupOrchestrator` (cross-cutting, stateful)

4. **Maintain backward compatibility**: Existing algorithm as facade over new components

5. **Incremental migration**: Extract one component at a time, test thoroughly

6. **Document coordination patterns**: Explicitly specify shutdown order, state transitions, error propagation

This analysis demonstrates that process-centric decomposition is viable and offers significant benefits for testability, reliability, and maintainability. The key is careful attention to coordination patterns and failure modes during extraction.
