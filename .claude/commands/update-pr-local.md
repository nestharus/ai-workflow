# Update PR Local Command

---

description: Handle local CodeRabbit review comments on uncommitted code
allowed-tools: Task, Bash, TodoWrite

---

Process local CodeRabbit review comments: $ARGUMENTS

## Overview

This command processes CodeRabbit review comments on local uncommitted code. Unlike `/update-pr`:
- Works with local uncommitted code (not a PR)
- Does not push changes
- Does not work in a worktree
- Uses the latest local CodeRabbit review file

## Arguments

- Empty: Use the latest CodeRabbit review file
- `--loop`: Run CodeRabbit repeatedly until no project files are modified between cycles
- Review file path: Use a specific review file (incompatible with `--loop`)

Examples:
- `/update-pr-local` - use latest review file
- `/update-pr-local --loop` - continuous improvement loop
- `/update-pr-local .review/20251120T094827Z.review.coderabbit` - use specific file

## Mode Selection

**Do not read file contents** - both modes must only track file paths, counts, and brief summaries.

**Content Access Policy:**

- **Allowed operations**: stat/lstat for metadata, recording file paths and sizes, computing hashes via chunked APIs or OS-level checksums, using jq to extract JSON keys/paths, using `git diff --stat` or `git ls-files` for filenames
- **Prohibited operations**: opening and parsing file text, reading full file into memory, running grep/sed/awk to inspect content, loading files into variables for semantic parsing

**Examples:**
- Allowed: `git diff --name-only`, `jq '.files[]' tasks.json`
- Prohibited: `cat file.py`, parsing file bodies, regex matches against file text

### Argument Validation

Before selecting mode, validate that arguments are not conflicting:

1. Parse arguments to identify:
   - `has_loop`: Whether `--loop` flag is present
   - `review_file`: Any positional argument that is not `--loop` (the review file path)

2. **If both `--loop` and a review file path are provided**, reject with error:
   ```text
   Error: Cannot use --loop with a specific review file path.

   Usage:
     /update-pr-local              Use latest review file (single mode)
     /update-pr-local --loop       Continuous improvement loop
     /update-pr-local <file>       Use specific review file (single mode)

   The --loop flag automatically runs CodeRabbit each cycle and cannot accept a pre-existing review file.
   ```
   **Stop processing and exit.**

### Mode Determination

After validation passes, determine mode:
- If `--loop` present: **Loop Mode**
- Otherwise: **Single Mode**

---

## Single Mode

**Do not read file contents** - only track file paths, counts, and brief summaries. See [Content Access Policy](#mode-selection) for allowed/prohibited operations.

### 1. Get Review File

If arguments provided (not `--loop`), use that path. Otherwise:

```bash
uv run review.latest --type coderabbit
```

**If no review file exists** (exit code 1), output and stop:
```text
Nothing to process.
```

### 2. Set Up Variables

```bash
git rev-parse --show-toplevel
git branch --show-current
```

Set:
- `repo_root`: Git repository root
- `working_dir`: Same as repo_root
- `current_branch`: Current git branch
- `tmp_folder`: `{{repo_root}}/.tmp/local-review`

### 3. Parse and Aggregate

```bash
uv run pr parse-coderabbit --review-file {{review_file}} --output-dir {{tmp_folder}}
uv run pr aggregate-tasks --input-dir {{tmp_folder}}
```

**Exit code handling for `pr aggregate-tasks`:**

- **Exit code 0**: Tasks found. The command outputs JSON with:
  - `files`: Array of modified file paths
  - `tasks_by_file`: Object mapping each file path to an array of task file names

  If `tasks_by_file` is empty (no tasks for any file), this is a no-op - no comment handlers will be spawned and the flow continues safely to cleanup.

- **Exit code 1**: No tasks found (aggregated task count is zero). Clean up and output:
  ```bash
  rm -rf {{tmp_folder}}
  rm -f {{review_file}}
  ```
  ```text
  Nothing to process.
  ```

### 4. Process Files in Parallel

Spawn `pr-comment-handler` Task agents in **parallel** - one per file:

```python
for file_path, task_files in tasks_by_file.items():
    Task(subagent_type="pr-comment-handler", prompt="""
    Process these tasks for file: {{file_path}}

    Tasks (in order):
    {% for task_file in task_files %}
    - {{tmp_folder}}/{{task_file}}
    {% endfor %}

    worktree: {{working_dir}}
    branch: {{current_branch}}
    """)
```

### 5. Run Tests in Parallel

Filter to Python files only, then spawn `test-debugger` agents in **parallel** - one per file:

```python
py_files = [f for f in files if f.endswith(".py")]
for file_path in py_files:
    Task(subagent_type="test-debugger", prompt=f"""
    file: {file_path}
    worktree: {working_dir}
    """)
```

**Note**: Only `.py` files have associated tests. Skip non-Python files (markdown, shell scripts, etc.).

### 6. Lint in Parallel

Spawn `lint-fixer` agents in **parallel** - one per file:

```python
for file_path in files:
    Task(subagent_type="lint-fixer", prompt=f'--worktree "{working_dir}" --files "{file_path}"')
```

**Note**: Paths are quoted to handle spaces correctly.

### 7. Cleanup and Summary

```bash
rm -rf {{tmp_folder}}
rm -f {{review_file}}
git diff --stat
```

Output summary and stop.

---

## Loop Mode

**CRITICAL: Minimize context usage. Do not read file contents. Only track paths.** See [Content Access Policy](#mode-selection) for allowed/prohibited operations.

### Memory Management

The `all_modified_files` set grows across cycles. To prevent unbounded memory growth, a cap check is performed immediately after Step 3 (aggregate) in each Loop Iteration:

- **Default cap**: 500 paths (typical path ~100 bytes = ~50KB max memory usage)
- **Check timing**: Immediately after Step 3 (Parse and Aggregate) completes, before Step 4 (Hash Files Before Editing)
- **Behavior when cap exceeded**:
  1. Log a warning: `WARNING: all_modified_files exceeded 500 paths. Resetting to current cycle only.`
  2. Clear the set entirely
  3. Re-populate with only the current cycle's paths by reading `aggregated.json` (saved in Step 3 via `uv run pr aggregate-tasks`) and extracting the `files` array

This ensures the set contains only paths from the current cycle, discarding historical paths from previous cycles. See Step 3a for the explicit implementation.

### Loop Variables

- `cycle`: Counter starting at 1
- `max_cycles`: Maximum allowed cycles (default 10)
- `all_modified_files`: Set of all project files modified across all cycles
- `cycle_summaries`: List of brief summaries per cycle
- `loop_start_time`: Timestamp when the loop begins
- `cycle_start_time`: Timestamp when each cycle begins
- `cycle_durations`: List of durations for each cycle (in seconds)
- `before_hash`: Path to before-edit hash file (`{{tmp_folder}}/before.json`)
- `after_hash`: Path to after-edit hash file (`{{tmp_folder}}/after.json`)

### Loop Start

```bash
git rev-parse --show-toplevel
git branch --show-current
```

Set `repo_root`, `working_dir`, `current_branch`, `tmp_folder`, `before_hash`, `after_hash`.

Record `loop_start_time` (current timestamp). Initialize loop variables:
- `cycle = 1`
- `cycle_durations = []`

### Loop Iteration

Repeat until clean or max_cycles reached:

#### Step 1: Check Cycle Limit and Record Start Time

If `cycle > max_cycles`:
- Log warning: `WARNING: Maximum cycles ({{max_cycles}}) reached. Aborting loop.`
- Append to `cycle_summaries`: `Cycle {{cycle}}: ABORTED - maximum cycle limit reached`
- **Exit loop** (do not continue)

Record `cycle_start_time` (current timestamp).

#### Step 2: Run CodeRabbit (Background with Polling)

Spawn a `coderabbit-poller` agent (haiku):

```python
Task(subagent_type="coderabbit-poller", model="haiku", prompt="""
command: uv run review.coderabbit -- --type uncommitted
""")
```

Wait for result. If `NO_CHANGES` or `ERROR`, exit loop.
Extract `review_file` from `REVIEW_FILE: <path>`.

#### Step 3: Parse and Aggregate

```bash
uv run pr parse-coderabbit --review-file {{review_file}} --output-dir {{tmp_folder}}
```

Capture aggregate output once and reuse:

```bash
aggregated_json="{{tmp_folder}}/aggregated.json"
uv run pr aggregate-tasks --input-dir {{tmp_folder}} > "$aggregated_json"
```

If no tasks (empty or zero count), remove the review file immediately and continue to next iteration:

```bash
rm -f {{review_file}}
```

**Note**: This immediate removal prevents stale review files from persisting between cycles. Step 9's cleanup is a fallback for normal cycle completion.

The `pr aggregate-tasks` command outputs JSON with:
- `files`: Array of modified file paths
- `tasks_by_file`: Object mapping each file path to an array of task file names

Extract `files` list and `tasks_by_file` mapping from the saved JSON file.

#### Step 3a: Check Memory Cap

Immediately after aggregation, check if `all_modified_files` exceeds the 500-path cap:

```python
import subprocess

PATH_CAP = 500

if len(all_modified_files) > PATH_CAP:
    # Log warning
    print(f"WARNING: all_modified_files exceeded {PATH_CAP} paths. Resetting to current cycle only.")

    # Clear the set entirely
    all_modified_files.clear()

    # Re-populate with only current cycle's paths from aggregated.json using jq
    try:
        result = subprocess.run(
            ["jq", "-r", ".files[]", aggregated_json],
            capture_output=True,
            text=True,
            check=True
        )
        current_cycle_files = [line for line in result.stdout.strip().split("\n") if line]
        all_modified_files.update(current_cycle_files)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to extract files from aggregated.json: {e.stderr}")
        raise
```

**Note**: This check extracts the `files` array from `aggregated.json` using jq (consistent with the Content Access Policy). The reset discards historical paths from previous cycles while preserving the current cycle's paths. Error handling ensures failures are logged and propagated.

#### Step 4: Hash Files Before Editing

Extract file list from the saved aggregated JSON and pipe into the hash command:

```bash
set -o pipefail
if ! jq -r '.files[]' "$aggregated_json" | uv run pr file-hash --root {{repo_root}} > {{before_hash}}; then
    echo "ERROR: Failed to generate before-edit hash. Pipeline command failed."
    rm -rf {{tmp_folder}}
    rm -f {{review_file}}
    exit 1
fi
```

**Error handling notes:**
- `set -o pipefail` ensures the pipeline fails if any command in the pipe fails
- On failure: prints error message, cleans up temp folder and review file, exits with code 1
- Callers can detect failures via the non-zero exit status
- Reuses the saved `aggregated.json` instead of re-running `pr aggregate-tasks`

#### Step 5: Process Files in Parallel

Spawn `pr-comment-handler` agents - one per file in `tasks_by_file`.

Wait for all to complete. Do not store detailed results - only note success/failure.

#### Step 6: Hash Files After Editing

Extract file list from the saved aggregated JSON and pipe into the hash command:

```bash
set -o pipefail
if ! jq -r '.files[]' "$aggregated_json" | uv run pr file-hash --root {{repo_root}} > {{after_hash}}; then
    echo "ERROR: Failed to generate after-edit hash. Pipeline command failed."
    rm -rf {{tmp_folder}}
    rm -f {{review_file}}
    exit 1
fi
```

**Error handling notes:**
- Same pattern as the before-edit hash step
- On failure: prints error message, cleans up temp folder and review file, exits with code 1
- Reuses the saved `aggregated.json` instead of re-running `pr aggregate-tasks`

#### Step 7: Compare Hashes

```bash
uv run pr file-hash-compare {{before_hash}} {{after_hash}}
```

- Exit code 0 = IDENTICAL (no changes made)
- Exit code 1 = DIFFERENT (files were modified)
- Exit code 2 = ERROR

#### Step 8: Evaluate Results

Calculate `cycle_duration` as current timestamp minus `cycle_start_time` (in seconds).

**If ERROR** (exit code 2):
- Log error: `ERROR: File hash comparison failed.`
- Append to `cycle_summaries`: `Cycle {{cycle}}: FAILED - hash comparison error`
- **Exit loop** immediately (do not proceed to tests or further processing)

**If IDENTICAL** (exit code 0):
- Append `cycle_duration` to `cycle_durations`
- Record final cycle summary
- **Exit loop** (clean state achieved)

**If DIFFERENT** (exit code 1):
- Add `files` list to `all_modified_files`
- Run tests on Python files:

```python
py_files = [f for f in files if f.endswith(".py")]
for file_path in py_files:
    Task(subagent_type="test-debugger", prompt=f"""
    file: {file_path}
    worktree: {working_dir}
    """)
```

Wait for all to complete. Record overall status (PASSED/FIXED/PARTIAL/BLOCKED).

**Note**: Only `.py` files have associated tests. Skip non-Python files.

- Append `cycle_duration` to `cycle_durations`
- Record brief cycle summary: `Cycle {{cycle}}: {{task_count}} tasks, {{file_count}} files, test status: {{status}}, duration: {{cycle_duration}}s`
- Increment `cycle`
- Continue loop

#### Step 9: Cleanup Cycle

```bash
rm -rf {{tmp_folder}}
rm -f {{review_file}}
```

**Note**: The hash files (`{{before_hash}}` and `{{after_hash}}`) are stored inside `{{tmp_folder}}` (as defined in Loop Variables), so they are automatically removed when `{{tmp_folder}}` is deleted.

### Post-Loop: Final Lint

After loop exits, run lint on ALL files that were modified across all cycles:

```python
for file_path in all_modified_files:
    Task(subagent_type="lint-fixer", prompt=f'--worktree "{working_dir}" --files "{file_path}"')
```

**Note**: Paths are quoted to handle spaces correctly.

### Final Summary

Calculate `total_elapsed` as current timestamp minus `loop_start_time` (in seconds).
Format as `{{minutes}}m {{seconds}}s` for display.

```bash
git diff --stat
```

Output:
```text
================================================================================
LOOP COMPLETE
================================================================================

Cycles: {{cycle}}
Total elapsed: {{total_elapsed_formatted}}
Total files modified: {{len(all_modified_files)}}

Cycle summaries:
{{cycle_summaries}}

Files modified:
{{all_modified_files}}

Changes:
{{git_diff_stat}}

Next steps:
1. Review the changes: git diff
2. Commit when ready: git add -p && git commit

================================================================================
```

---

## Code Review Tools

Automated code reviews are performed using CodeRabbit. The `--loop` mode runs this automatically;
single mode requires a human to run it first.

* **Human-run command**: `uv run review.coderabbit -- [--base <branch> | --type <mode> | --base-commit <sha>]`
* **Agent retrieval**: `uv run review.latest --type coderabbit`
* **Timeout guidance**: Allow up to 2 hours for CodeRabbit

## Rules

- **This command must not read file contents** - only track paths
- **Loop mode must minimize context** - store only paths, counts, and brief summaries
- No AI co-authors (see AGENTS.md)
- Never defer - implement or challenge
- Always use sub-agents for: comment handling, testing, linting
- Process sub-agents in parallel where possible
- In loop mode: tests on changed files (when hashes differ), lint only at end
- In single mode: both tests and lint
