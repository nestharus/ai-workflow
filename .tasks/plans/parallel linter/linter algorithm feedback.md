### Process Management & Concurrency

* **Move snapshot creation to the main thread.** Currently, `_run_linter_safe` (worker thread/process) creates snapshots. If the main process receives `SIGINT` and immediately kills child process groups, the workers may die before restoring files. Create file snapshots in the main thread *before* submitting the task to the executor. Pass the snapshot paths to the worker. This allows the main `SIGINT` handler to reliably track and restore files even if workers are dead.
* **Account for environment variables in ARG_MAX.** When calculating `ARG_MAX` budget in `_chunk_fileset_for_arg_max`, subtract the size of the current environment variables (`os.environ`). On POSIX systems, the environment limits the total space available for arguments.
* **Use Job Objects for Windows termination.** The logic mentions `setsid` for POSIX but only `CREATE_NEW_PROCESS_GROUP` for Windows. To ensure robust cleanup on Windows, use Job Objects. Assign the linter subprocess to a Job Object configured to terminate all processes in the job when the handle is closed. This catches grandchildren processes that might escape `taskkill`.
* **Cap preflight workers.** `max(1, available_cpus * 2)` can be aggressive if `available_cpus` is high (e.g., 32 cores -> 64 workers). Cap this at a static limit (e.g., 32) to prevent exhausting file descriptors or thread limits during the preflight phase.

### Resilience & Error Handling

* **Global shutdown event check.** In the `AS_COMPLETED_LOOP`, check a `shutdown_event` flag immediately upon retrieving a future, before processing the result. If a fail-fast triggered from a previous result, this prevents the processing or storage of results that finished concurrently, ensuring a clean stop.
* **Deduplicate linter instances with explicit IDs.** Hashing by configuration might merge two identical linter runs intended to be separate (e.g., running the same linter twice for stress testing). Assign a unique instance ID during expansion and include this ID in the hash to preserve intent.

### File Handling & Logic

* **Enforce file arguments.** Since all linters support filtering, simplify the `PHASE_ITEMS` logic. Remove the branch for `linter.appends_files_to_cli == False`. Require all linters to accept the fileset chunks. This eliminates the edge case where a linter runs once without arguments and potentially scans non-target files.
* **Unique Chunk IDs.** The current logic uses `chunk_id=phase_order_index` for non-appending linters and chunking indices for appending ones. Use a tuple `(linter_id, chunk_index)` or a globally incrementing integer for `chunk_id`. This ensures the output buffer has a strictly unique key for every task, preventing collision in the sliding window sort.

### Output & Determinism

* **Separate Standard Streams.** In `_run_linter_safe`, capture `stdout` and `stderr` separately rather than merging them immediately. Merge them only when constructing the final result object. This allows the YAML output mode to structure `stdout` and `stderr` into distinct fields, which is valuable for parsing tools.
* **Preserve Linter Order in Parallel Phase.** When buffering output in `BUFFER_OUTPUT`, ensure the `next_expected_chunk_id` sequence respects the original sort order of `PHASE_ITEMS`. If chunks are generated dynamically, pre-calculate the total number of expected chunks and their IDs before execution begins so the sliding window knows exactly what the sequence "0, 1, 2..." represents.
