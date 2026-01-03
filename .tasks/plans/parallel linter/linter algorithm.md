flowchart TD
subgraph Entry["Entry Point"]
START([main]) --> PARSE_ARGS["_parse_args()"]
PARSE_ARGS --> INIT_CPUS["available_cpus = _get_available_cpus()<br/>(len(os.sched_getaffinity(0)) if supported<br/>else (os.cpu_count() or 1))"]
INIT_CPUS --> YAML_CHECK{"output_format<br/>== 'yaml'?"}
YAML_CHECK --> |Yes| SET_YAML[yaml_output = true]
YAML_CHECK --> |No| SET_TEXT[yaml_output = false]
SET_YAML --> INIT_META["meta = {warnings: [], errors: []}"]
SET_TEXT --> INIT_META
INIT_META --> INIT_RESULTS["all_results = {}"]
INIT_RESULTS --> SETUP_SIGNALS["setup_signal_handlers()<br/>(SIGINT: set shutdown_event; shutdown executors, cancel futures,<br/>terminate process groups (POSIX) / close Job Objects (Windows),<br/>restore in-flight mutator snapshots (created in main process))"]
SETUP_SIGNALS --> VALIDATE_OPTS
end

subgraph FileOptions["File Option Validation"]
VALIDATE_OPTS{"More than one of:<br/>--changed-only<br/>--files<br/>--commit?"}
VALIDATE_OPTS --> |Yes| MUTUAL_ERR["Record error in meta.errors; in text mode print to stderr:<br/>mutually exclusive"]
MUTUAL_ERR --> FINAL_OUTPUT
VALIDATE_OPTS --> |No| FILE_MODE
end

subgraph FileDetermination["File Determination"]
FILE_MODE{"Which file<br/>option?"}
FILE_MODE --> |--changed-only| CHANGED_ONLY["files = _get_changed_files()"]
FILE_MODE --> |--commit SHA| COMMIT_FILES["files = _get_changed_files(commit)"]
FILE_MODE --> |--files| EXPLICIT_FILES["files = _filter_existing_files(<br/>args.files)"]
FILE_MODE --> |None| WHOLE_REPO["files = _get_repo_files()<br/>(git ls-files -co --exclude-standard)"]

CHANGED_ONLY --> CHECK_EMPTY1{"files empty?"}
COMMIT_FILES --> CHECK_EMPTY2{"files empty?"}
EXPLICIT_FILES --> DROPPED_CHECK{"Any explicit file args<br/>were dropped (not found)?"}
DROPPED_CHECK --> |Yes| WARN_DROPPED["Add warning to meta.warnings; in text mode warn to stderr:<br/>Some explicit file args not found"]
WARN_DROPPED --> CHECK_EMPTY3{"files empty?"}
DROPPED_CHECK --> |No| CHECK_EMPTY3

CHECK_EMPTY1 --> |Yes| PRINT_NONE1["Report to stderr (or suppress in YAML mode):<br/>No changes detected"]
CHECK_EMPTY2 --> |Yes| PRINT_NONE2["Report to stderr (or suppress in YAML mode):<br/>No files in commit"]
CHECK_EMPTY3 --> |Yes| PRINT_NONE3["Record error in meta.errors; in text mode print to stderr:<br/>Requested files not found"]

PRINT_NONE1 --> FINAL_OUTPUT
PRINT_NONE2 --> FINAL_OUTPUT
PRINT_NONE3 --> FINAL_OUTPUT

CHECK_EMPTY1 --> |No| PRINT_FILES1["Report to stderr (or suppress in YAML mode):<br/>Print file count"]
CHECK_EMPTY2 --> |No| PRINT_FILES2["Report to stderr (or suppress in YAML mode):<br/>Print file count"]
CHECK_EMPTY3 --> |No| LINTER_SELECT

PRINT_FILES1 --> LINTER_SELECT
PRINT_FILES2 --> LINTER_SELECT
WHOLE_REPO --> LINTER_SELECT
end

subgraph GetChangedFiles["_get_changed_files(commit?)"]
GCF_START([Start]) --> HAS_COMMIT{"commit<br/>specified?"}
HAS_COMMIT --> |Yes| GIT_DIFF_COMMIT["git diff-tree --no-commit-id<br/>--name-only --diff-filter=d<br/>-r <commit>"]
HAS_COMMIT --> |No| GIT_DIFF_HEAD["git diff HEAD --name-only --diff-filter=d<br/>(staged+unstaged vs HEAD)"]
HAS_COMMIT --> |No| GIT_UNTRACKED["git ls-files --others --exclude-standard<br/>(untracked new files)"]

GIT_DIFF_HEAD --> NORMALIZE_DIFF_HEAD["Normalize paths early:<br/>os.path.relpath(path, repo_root)<br/>(strip leading './' and empties)"]
GIT_UNTRACKED --> NORMALIZE_UNTRACKED["Normalize paths early:<br/>os.path.relpath(path, repo_root)<br/>(strip leading './' and empties)"]
NORMALIZE_DIFF_HEAD --> MERGE_UNCOMMITTED["Merge diff + untracked"]
NORMALIZE_UNTRACKED --> MERGE_UNCOMMITTED
MERGE_UNCOMMITTED --> DEDUP_UNCOMMITTED["Deduplicate paths (preserve order)<br/>(before os.path.exists)"]
DEDUP_UNCOMMITTED --> FILTER_UNCOMMITTED["Optional: apply global ignores<br/>(custom ignore files/patterns)<br/>(.gitignore is already respected for untracked)"]
FILTER_UNCOMMITTED --> EXISTS_UNCOMMITTED["Filter existing files via os.path.exists<br/>(drop deleted paths)"]
EXISTS_UNCOMMITTED --> DIFF_EMPTY{"merged output<br/>empty?"}
DIFF_EMPTY --> |Yes| RETURN_NOCHANGES[/"Return [] (no changes)"/]
DIFF_EMPTY --> |No| SORT_UNCOMMITTED["Sort paths"]
SORT_UNCOMMITTED --> RETURN_UNCOMMITTED[/"Return sorted files"/]

GIT_DIFF_COMMIT --> NORMALIZE_COMMIT["Normalize paths early:<br/>os.path.relpath(path, repo_root)<br/>(strip leading './' and empties)"]
NORMALIZE_COMMIT --> DEDUP_COMMIT["Deduplicate paths (defensive)<br/>(before os.path.exists)"]
DEDUP_COMMIT --> FILTER_COMMIT["Optional: apply global ignores<br/>(custom ignore files/patterns)"]
FILTER_COMMIT --> EXISTS_COMMIT["Filter existing files via os.path.exists<br/>(drop deleted paths)"]
EXISTS_COMMIT --> SORT_COMMIT["Sort paths"]
SORT_COMMIT --> RETURN_COMMIT[/"Return sorted files in commit"/]
end

subgraph GetRepoFiles["_get_repo_files()"]
GRF_START([Start]) --> GIT_ALL["git ls-files -co --exclude-standard<br/>(tracked + untracked new files)"]
GIT_ALL --> FILTER_REPO_FILES["Optional: apply global ignores<br/>(custom ignore files/patterns)<br/>(.gitignore is already respected for untracked)"]
FILTER_REPO_FILES --> SORT_REPO_FILES["Sort paths"]
SORT_REPO_FILES --> RETURN_REPO_FILES[/"Return sorted files"/]
end

subgraph LinterSelection["Linter Selection"]
LINTER_SELECT{"args.linters<br/>specified?"}
LINTER_SELECT --> |Yes| EXPAND_SPECS["For each spec:<br/>_expand_linter_spec()"]
LINTER_SELECT --> |No| ALL_LINTERS["linters_to_run =<br/>LINTER_NAMES"]

EXPAND_SPECS --> VALID_SPEC{"All specs expanded<br/>without errors?"}
VALID_SPEC --> |No| INVALID_SPEC["Record error in meta.errors; in text mode print to stderr:<br/>Invalid linter specification"]
INVALID_SPEC --> FINAL_OUTPUT
VALID_SPEC --> |Yes| TRACK_EXPLICIT["Track explicitly requested linters<br/>(specs with operator == none)"]
TRACK_EXPLICIT --> CONVERT_INSTANCES
ALL_LINTERS --> CONVERT_INSTANCES
end

subgraph ExpandSpec["_expand_linter_spec(spec)"]
ES_START([Start]) --> PARSE_OP["Parse operator:<br/>>= | <= | > | < | none"]
PARSE_OP --> VALID_NAME{"linter_name in<br/>LINTER_NAMES?"}
VALID_NAME --> |No| RETURN_ERROR[/"Return error (unknown linter)"/]
VALID_NAME --> |Yes| APPLY_OP{"Operator?"}
APPLY_OP --> |>=| SLICE_GTE["LINTER_NAMES[idx:]"]
APPLY_OP --> |>| SLICE_GT["LINTER_NAMES[idx+1:]"]
APPLY_OP --> |<=| SLICE_LTE["LINTER_NAMES[:idx+1]"]
APPLY_OP --> |<| SLICE_LT["LINTER_NAMES[:idx]"]
APPLY_OP --> |none| SINGLE["[linter_name]"]

SLICE_GTE --> EXPANDED_EMPTY{"expanded list<br/>empty?"}
SLICE_GT --> EXPANDED_EMPTY
SLICE_LTE --> EXPANDED_EMPTY
SLICE_LT --> EXPANDED_EMPTY
SINGLE --> EXPANDED_EMPTY
EXPANDED_EMPTY --> |Yes| EXPANDED_WARN["Log debug to stderr: spec expands to empty list"]
EXPANDED_WARN --> RETURN_EMPTY[/"Return []"/]
EXPANDED_EMPTY --> |No| RETURN_LIST[/"Return linter list"/]
end

subgraph ConvertAndSchedule["Convert & Schedule"]
CONVERT_INSTANCES["Convert linter specs<br/>to instances"] --> UNKNOWN_CHECK{"All linters<br/>known?"}
UNKNOWN_CHECK --> |No| UNKNOWN_ERR["Record error in meta.errors; in text mode print to stderr:<br/>Unknown linter"]
UNKNOWN_ERR --> FINAL_OUTPUT
UNKNOWN_CHECK --> |Yes| ASSIGN_INSTANCE_ID["Assign unique instance_id to each linter instance<br/>(instance_id participates in __hash__/__eq__; preserve order)"]
ASSIGN_INSTANCE_ID --> SCHEDULE["schedule_linters(<br/>linter_instances, files)"]
end

subgraph ScheduleLinters["schedule_linters()"]
SL_START([Start]) --> FOR_LINTER["For each linter"]
FOR_LINTER --> CLASSIFY{"mutates_files?"}
CLASSIFY --> |Yes| ADD_MUTATING["Add to mutating_linters"]
CLASSIFY --> |No| PARALLEL_SAFE{"parallel_safe?"}
PARALLEL_SAFE --> |Yes| ADD_READONLY_PAR["Add to read_only_parallel_safe"]
PARALLEL_SAFE --> |No| ADD_READONLY_SEQ["Add to read_only_sequential"]
ADD_MUTATING --> NEXT_LINTER
ADD_READONLY_PAR --> NEXT_LINTER
ADD_READONLY_SEQ --> NEXT_LINTER

NEXT_LINTER --> BUILD_PHASES["Build phases"]
BUILD_PHASES --> SORT_MUTATORS["Sort mutating linters deterministically:<br/>by priority (asc), then name"]
SORT_MUTATORS --> PACK_MUTATORS["Build mutating phases (parallel where safe):<br/>greedily pack mutators whose calculate_fileset(files)<br/>resources are disjoint (via linter.scope: File vs Directory);<br/>sequentialize only on overlap"]
PACK_MUTATORS --> READONLY_SEQ_PHASES["Each read-only sequential linter<br/>gets own phase"]
READONLY_SEQ_PHASES --> READONLY_PAR_PHASE["All read-only parallel-safe linters<br/>in final parallel phase"]
READONLY_PAR_PHASE --> TAG_PHASES["Phase objects include:<br/>is_mutating boolean"]
TAG_PHASES --> ORDER_PHASES["Order phases: all is_mutating=True phases first<br/>(mutating before read-only; preserve internal order)"]
end

SCHEDULE --> COMMIT_MUTATING_CHECK{"--commit mode AND<br/>any mutating linter selected?"}
COMMIT_MUTATING_CHECK --> |Yes| COMMIT_MUTATING_ERR["Record error in meta.errors; in text mode print to stderr:<br/>Mutating linters forbidden with --commit"]
COMMIT_MUTATING_ERR --> FINAL_OUTPUT
COMMIT_MUTATING_CHECK --> |No| PHASES_EMPTY{"phases<br/>empty?"}
PHASES_EMPTY --> |Yes| NO_LINTERS["Report to stderr (or suppress in YAML mode):<br/>No linters to run"]
NO_LINTERS --> FINAL_OUTPUT
PHASES_EMPTY --> |No| APPLICABILITY_PRESCAN["Applicability pre-scan + cache:<br/>fileset_by_linter = {}<br/>for each selected linter:<br/>fileset = calculate_fileset(files)<br/>fileset_by_linter[linter] = fileset<br/>if fileset empty:<br/>all_results[linter] = skipped(no_matching_files); drop from phases"]
APPLICABILITY_PRESCAN --> ANY_APPLICABLE{"Any linters remain<br/>after pre-scan?"}
ANY_APPLICABLE --> |No| NO_APPLICABLE["Report to stderr (or suppress in YAML mode):<br/>No applicable linters to run"]
NO_APPLICABLE --> FINAL_OUTPUT
ANY_APPLICABLE --> |Yes| PREFLIGHT_SELECTED["Preflight (parallel): run linter.test()<br/>for applicable linters only"]
PREFLIGHT_SELECTED --> PREFLIGHT_WORKERS["preflight_workers = min(len(selected),<br/>min(32, max(1, available_cpus * 2)))"]
PREFLIGHT_WORKERS --> PREFLIGHT_POOL["ThreadPoolExecutor(max_workers=preflight_workers)<br/>-> futures (test)<br/>(linter.test() must enforce strict timeout)"]
PREFLIGHT_POOL --> PREFLIGHT_DONE["Collect preflight via as_completed"]
PREFLIGHT_DONE --> PREFLIGHT_OK{"All tests<br/>passed?"}
PREFLIGHT_OK --> |No| PREFLIGHT_EXPLICIT_CHECK{"Any explicitly requested<br/>linters failed preflight?"}
PREFLIGHT_EXPLICIT_CHECK --> |Yes| PREFLIGHT_EXPLICIT_FAIL["Record error in meta.errors; in text mode print to stderr:<br/>Explicitly requested linter failed preflight"]
PREFLIGHT_EXPLICIT_FAIL --> FINAL_OUTPUT
PREFLIGHT_EXPLICIT_CHECK --> |No| PREFLIGHT_DROP["Drop failing linter(s); record all_results[l] = skipped(preflight_failed);<br/>in text mode warn to stderr; always add meta.warnings"]
PREFLIGHT_DROP --> PREFLIGHT_REMAIN{"Any healthy<br/>linters left?"}
PREFLIGHT_REMAIN --> |No| PREFLIGHT_NONE["Record error in meta.errors; in text mode print to stderr:<br/>No operational linters to run"]
PREFLIGHT_NONE --> FINAL_OUTPUT
PREFLIGHT_REMAIN --> |Yes| INIT_STATE["(ready to execute phases)"]
PREFLIGHT_OK --> |Yes| INIT_STATE["(ready to execute phases)"]

subgraph PhaseLoop["Phase Execution Loop"]
INIT_STATE --> PHASE_ITER["For each phase (scheduled linters)"]
PHASE_ITER --> PHASE_ITEMS["Build phase_items (from cache):<br/>next_chunk_id = 0<br/>for linter in phase.linters:<br/>fileset = fileset_by_linter[linter]<br/>if fileset empty:<br/>all_results[linter] = skipped(no_matching_files)<br/>else:<br/>fileset_chunks = _chunk_fileset_for_arg_max(<br/>fileset, base_cmd_len=len(exe+flags+config), env_len=_env_size(os.environ), safety_margin=2KB)<br/>for fileset_chunk in fileset_chunks:<br/>add (linter, fileset_chunk, chunk_id=next_chunk_id); next_chunk_id += 1"]
PHASE_ITEMS --> PHASE_EMPTY{"phase_items<br/>empty?"}
PHASE_EMPTY --> |Yes| NEXT_PHASE
PHASE_EMPTY --> |No| PHASE_META["is_mutating_phase = phase.is_mutating<br/>(set by scheduler)"]
PHASE_META --> SHOULD_PRINT_PHASE{"yaml_output?"}

SHOULD_PRINT_PHASE --> |Yes| EXEC_PHASE["execute_phase(phase_items,<br/>yaml_output, fail_fast)"]
SHOULD_PRINT_PHASE --> |No| PRINT_PHASE["Print phase header:<br/>Running linter(s)"]
PRINT_PHASE --> EXEC_PHASE
EXEC_PHASE --> COLLECT_RESULTS["Merge phase results into all_results (main thread):<br/>aggregate chunk results per linter;<br/>dedupe diagnostics by hash(file,line,col,rule_id)"]
COLLECT_RESULTS --> PHASE_MODIFIED["phase_modified = is_mutating_phase AND<br/>any(result.files_modified)"]
PHASE_MODIFIED --> CHECK_FAILURES

CHECK_FAILURES{"Any failed<br/>linters?"} --> |No| NEXT_PHASE
CHECK_FAILURES --> |Yes| HANDLE_FAILURE

HANDLE_FAILURE --> MUTATE_CRASH_CHECK{"is_mutating_phase AND<br/>any mutating linter crashed?"}
MUTATE_CRASH_CHECK --> |Yes| MUTATE_CRASH["Record crash result (include traceback) into all_results;<br/>record error in meta.errors; in text mode print to stderr:<br/>Mutating linter crashed"]
MUTATE_CRASH --> MUTATE_RECOVER["Recovery (atomic): restore only the crashed mutator task's fileset<br/>from its pre-run snapshot using os.replace/rename<br/>(or git checkout those paths if safe)"]
MUTATE_RECOVER --> FINAL_OUTPUT
MUTATE_CRASH_CHECK --> |No| FAIL_FAST{"--fail-fast?"}
FAIL_FAST --> |Yes| FINAL_OUTPUT
FAIL_FAST --> |No| HANDLE_FAILURE_TYPE{"is_mutating_phase?"}
HANDLE_FAILURE_TYPE --> |Yes| MUTATE_FAIL["Report to stderr (or suppress in YAML mode):<br/>Mutating linter reported issues"]
MUTATE_FAIL --> NEXT_PHASE
HANDLE_FAILURE_TYPE --> |No| READONLY_FAIL["Report to stderr (or suppress in YAML mode):<br/>Failed linters"]
READONLY_FAIL --> NEXT_PHASE

NEXT_PHASE --> MORE_PHASES{"More phases?"}
MORE_PHASES --> |Yes| RECHECK_MUTATING{"Previous phase<br/>was mutating?"}
RECHECK_MUTATING --> |Yes| RECHECK_MODIFIED{"phase_modified?"}
RECHECK_MODIFIED --> |Yes| PRUNE_DELETED["files = _filter_existing_files(files)<br/>(remove deleted via os.path.exists)"]
PRUNE_DELETED --> PRUNE_FILESET_CACHE["fileset_by_linter[l] = _filter_existing_files(<br/>fileset_by_linter[l])  (for all l)"]
PRUNE_FILESET_CACHE --> PHASE_ITER
RECHECK_MODIFIED --> |No| PHASE_ITER
RECHECK_MUTATING --> |No| PHASE_ITER
MORE_PHASES --> |No| FINAL_OUTPUT
end

subgraph ExecutePhase["execute_phase()"]
EP_START([Start]) --> EP_EMPTY{"phase_items<br/>empty?"}
EP_EMPTY --> |Yes| EP_EMPTY_RET[/"Return {}"/]
EP_EMPTY --> |No| EP_SINGLE{"len(phase_items)<br/>== 1?"}
EP_SINGLE --> |Yes| EXEC_SINGLE["_execute_single_linter()"]
EP_SINGLE --> |No| EXEC_PARALLEL["_execute_parallel_linters()"]

EXEC_SINGLE --> RUN_SAFE1["_run_linter_safe(linter, fileset_chunk, chunk_id, snapshot_path)<br/>(catches exceptions)"]
EXEC_PARALLEL --> CALC_WORKERS["max_workers = min(len(phase_items),<br/>max_concurrency or max(1, available_cpus))<br/>(available_cpus computed once at startup)"]
CALC_WORKERS --> PROCESS_POOL["ProcessPoolExecutor<br/>(max_workers=max_workers)<br/>(avoids the GIL for CPU-bound Python linters)"]
PROCESS_POOL --> SUBMIT_ALL["For each phase_item (main process):<br/>if linter.mutates_files: snapshot fileset_chunk (temp -> rename)<br/>Submit _run_linter_safe(linter, fileset_chunk, chunk_id, snapshot_path)<br/>-> futures (track running task -> process group / Job Object + snapshot_path)"]
SUBMIT_ALL --> INIT_OUTPUT_STATE["Initialize output state (text mode):<br/>expected_chunk_ids = [0..len(phase_items)-1]; next_expected_chunk_id = 0;<br/>shutdown_event = False; output_buffer = {}"]
INIT_OUTPUT_STATE --> AS_COMPLETED_LOOP["Collect futures via as_completed(futures)<br/>(no head-of-line blocking)"]
AS_COMPLETED_LOOP --> CHECK_SHUTDOWN{"shutdown_event?"}
CHECK_SHUTDOWN --> |Yes| NEXT_RESULT
CHECK_SHUTDOWN --> |No| STORE_RESULT["If not cancelled (generation matches): store result into results dict<br/>(ignore late results from in-flight tasks after fail-fast)"]
AS_COMPLETED_LOOP --> |Done| FLUSH_BUFFER["Flush buffered output (text mode):<br/>drain sliding window until empty"]
STORE_RESULT --> EMIT_RESULT{"yaml_output?"}
EMIT_RESULT --> |No| BUFFER_OUTPUT["Buffer output (keyed by chunk_id)<br/>(preserve deterministic order)"]
EMIT_RESULT --> |Yes| NO_PRINT["(no stdout printing)"]
BUFFER_OUTPUT --> SLIDING_FLUSH["Sliding-window flush (text mode):<br/>while output_buffer[next_expected_chunk_id] exists:<br/>print; next_expected_chunk_id += 1"]
SLIDING_FLUSH --> FAILFAST_EARLY{"--fail-fast AND<br/>result is failure?"}
NO_PRINT --> FAILFAST_EARLY
FAILFAST_EARLY --> |Yes| CANCEL_FUTURES["Set shutdown_event; mark phase cancelled (bump generation); cancel pending futures;<br/>hard-stop running tasks by terminating their process groups (POSIX) / closing Job Objects (Windows);<br/>restore snapshots for any terminated mutating tasks (snapshots created in main process); shutdown(wait=False, cancel_futures=True)"]
CANCEL_FUTURES --> FLUSH_BUFFER
FLUSH_BUFFER --> EP_PAR_RET[/"Return results dict<br/>(may be partial on fail-fast)"/]
FAILFAST_EARLY --> |No| NEXT_RESULT["Continue loop"]
NEXT_RESULT --> AS_COMPLETED_LOOP
RUN_SAFE1 --> LINTER_RUN["try: (snapshot_path provided for mutators; created by main process before submit)<br/>Build command: fixed args (exe+flags+config) + fileset_chunk<br/>(ARG_MAX budget accounts for fixed args + environment + 2KB margin)<br/>Run linter subprocess in its own process tree (POSIX: setsid; Windows: Job Object kill-on-close)<br/>(enforce per-linter timeout; kill entire process tree on expiry)<br/>(capture stdout and stderr separately with size limit or temp-file rollover;<br/>decode with errors='backslashreplace'; no direct writes to sys.stdout/stderr)<br/>strip ANSI (YAML-safe); normalize paths to repo-relative before storing<br/>return LinterResult{status, exit_code,<br/>stdout, stderr, file_list, files_modified, chunk_id}<br/>except TimeoutError:<br/>return LinterResult{status=timeout}<br/>except FileNotFoundError:<br/>return LinterResult{status=skipped, skip_reason=input_files_vanished}<br/>except Exception:<br/>return LinterResult{status=crashed}"]
end

subgraph FinalOutput["Final Output & Exit"]
FINAL_OUTPUT{"yaml_output?"} --> |Yes| OUTPUT_YAML["_output_yaml_results(<br/>all_results, meta)"]
FINAL_OUTPUT --> |No| CALC_EXIT
OUTPUT_YAML --> CALC_EXIT

CALC_EXIT["any_failure = (len(meta.errors) > 0) OR any(!r.success)"] --> EXIT_CHECK{"any_failure?"}
EXIT_CHECK --> |Yes| FINALIZE_FAIL["Finalize & flush stdout/stderr"]
FINALIZE_FAIL --> EXIT_FAILURE([return 1])
EXIT_CHECK --> |No| FINALIZE_OK["Finalize & flush stdout/stderr"]
FINALIZE_OK --> EXIT_SUCCESS([return 0])
end

subgraph ExceptionHandling["Exception Handling"]
EX_RUNTIME["RuntimeError"] --> EX_PRINT1["Record error in meta.errors; in text mode print to stderr"]
EX_PRINT1 --> FINAL_OUTPUT

EX_OS["OSError"] --> EX_PRINT2["Record error in meta.errors; in text mode print to stderr"]
EX_PRINT2 --> FINAL_OUTPUT

EX_YAML["YAMLError"] --> EX_PRINT3["Record error in meta.errors; in text mode print to stderr"]
EX_PRINT3 --> FINAL_OUTPUT

EX_SIGINT["KeyboardInterrupt / SIGINT"] --> EX_SIGINT_HANDLE["Set shutdown_event; shutdown executors(wait=False, cancel_futures=True);<br/>terminate running process groups (POSIX) / close Job Objects (Windows);<br/>restore snapshots for in-flight mutating tasks (atomic; snapshots created in main process); flush output"]
EX_SIGINT_HANDLE --> EXIT_INTERRUPTED([return 130])
end

style START fill:#90EE90
style EXIT_SUCCESS fill:#98FB98
style EXIT_FAILURE fill:#FFB6C1
style EXIT_INTERRUPTED fill:#FFDAB9

This flowchart covers the complete algorithm:

1. Entry Point - Argument parsing, CPU count detection, YAML output mode detection, initialization of `meta` + `all_results`, and SIGINT handler registration (immediate cancellation)
2. File Option Validation - Mutual exclusivity check for --changed-only, --files, --commit; errors are recorded and emitted as structured output in YAML mode
3. File Determination - File selection; warnings (e.g., missing explicit `--files` paths) are recorded in `meta.warnings` and included in YAML output; exit success for empty change/commit sets; exit failure when explicit `--files` resolves to no existing paths (requested paths not found); whole-repo mode uses explicit repository file discovery rather than relying on per-linter defaults
4. Changed Files Logic - Uses `git diff HEAD --name-only --diff-filter=d` plus `git ls-files --others --exclude-standard` for the working tree; commit mode uses `git diff-tree --diff-filter=d`; both paths go through a common pipeline of normalize-to-repo-relative early + dedupe-before-filter-existing + ignore + sort (drop deleted paths via `os.path.exists`)
5. Linter Selection - Expanding linter specs with range operators (>=, >, <=, <); unknown linter names error immediately; empty expansions (e.g., `last_linter>`) are valid, logged at debug level, and may yield "No linters to run"; each linter instance is assigned a unique `instance_id` during conversion and `instance_id` participates in `__hash__`/`__eq__` so identical configurations do not collapse into one run
6. Scheduling - schedule_linters() separates mutating vs read-only linters (read-only may be sequential vs parallel-safe) into phases, sorts mutators deterministically (priority, then name), and packs mutators into the same phase when their calculated resources are disjoint (scope-aware: File vs Directory) while sequentializing on overlap; phase ordering enforces that all mutating phases complete before any read-only phase begins; `--commit` mode forbids mutating linters
7. Applicability Pre-scan + Preflight Validation - Before preflight, run `calculate_fileset(files)` once per selected linter, cache into `fileset_by_linter`, and drop linters with no matching files (record `skipped(no_matching_files)` in `all_results`); run `linter.test()` in parallel only for remaining applicable linters with strict per-test timeouts using `preflight_workers = min(len(selected), min(32, max(1, available_cpus * 2)))`; if a user explicitly requested a linter by name and it fails preflight, hard-error; otherwise, drop failing linters, record `skipped(preflight_failed)` in `all_results`, and proceed with the remaining set
8. Applicability & Task Generation - Phase-item generation uses cached `fileset_by_linter` (no per-phase `calculate_fileset`); linters with empty filesets are recorded as `skipped(no_matching_files)`; split filesets into ARG_MAX-safe chunks using an arg budget that accounts for fixed command overhead + environment size + 2KB margin; assign each task a unique sequential `chunk_id` in `phase_items` order; every linter invocation receives explicit file arguments (never "run once with no files"); exit 0 when nothing is runnable across all phases
9. Phase Execution Loop - Phases execute (single = sequential, multiple = parallel); phase mutating-ness is precomputed by the scheduler; chunk results are aggregated per linter and diagnostics are deduplicated before storing into `all_results`; in text mode, per-chunk output is buffered and flushed via a sliding window (`next_expected_chunk_id`) using precomputed sequential chunk IDs, and the `as_completed` loop checks `shutdown_event` before processing future results to ensure a clean stop after fail-fast/SIGINT
10. Failure Handling - Mutating linter crashes record a traceback into `all_results`, attempt file recovery only for the crashed mutator task’s fileset snapshot (atomic restore via `os.replace`/rename; or git checkout those paths if safe), and abort immediately; timeouts terminate the entire process tree (process group on POSIX, Job Object on Windows); `--fail-fast` aborts on the first failure by setting `shutdown_event`, hard-stopping running tasks, restoring snapshots for in-flight mutators, and ignoring late results; otherwise, failures are reported and execution continues
11. Deleted Files - `_run_linter_safe()` treats `FileNotFoundError` as a skip instead of failing the entire run; no per-linter file-list refresh is required within a phase
12. Fileset Drift - After a mutating phase that actually modified files, refresh by filtering the existing file list against the filesystem (remove deleted paths) and pruning deleted paths from `fileset_by_linter`; do not re-query git for new/changed paths and do not re-run `calculate_fileset`
13. Concurrency - `available_cpus` is computed once at startup (sched_getaffinity when supported, else cpu_count); preflight uses ThreadPoolExecutor with a static worker cap; ProcessPoolExecutor is used for parallel linter execution to avoid the GIL on CPU-bound Python linters; ARG_MAX chunking happens during phase-item generation using an arg budget that accounts for fixed command overhead + environment size + 2KB margin; mutator snapshots are created in the main process before submission so SIGINT/fail-fast can restore even if workers are killed; Windows termination uses Job Objects; parallel results are collected via `as_completed` with a `shutdown_event` check; fail-fast hard-stops running tasks (not just canceling pending futures); text-mode output is flushed via sliding-window buffering for deterministic, real-time feedback; `_run_linter_safe()` catches exceptions
14. Output - YAML format or text format with error details; stdout and stderr are captured separately (YAML keeps distinct fields) and decoding is resilient to non-UTF-8 output; paths in results are normalized to repo-relative; in YAML mode, warnings/errors are included under `meta` and per-linter results are structured (exit_code/stdout/stderr/file_list/files_modified) and distinguish `skipped(no_matching_files)` vs `skipped(preflight_failed)` vs `skipped(input_files_vanished)` vs `timeout`
15. Exit Codes - 0 for success (including "no applicable linters" for a valid file set); 1 for invalid inputs (recorded in `meta.errors`) or linter failures; 130 for SIGINT/KeyboardInterrupt
