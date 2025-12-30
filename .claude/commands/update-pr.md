# Update PR Command

---

description: Handle code review comments with optional worktree support
allowed-tools: Task, Read, Glob, Bash, TodoWrite

---

Process code review comments: $ARGUMENTS

## Overview

This command processes code review comments, either locally or in a worktree for a PR.
After processing, it commits changes, runs lint, squashes commits, and pushes.

**Two modes:**
- **Local mode** (no ticket): Reviews uncommitted code or most recent commit
- **Worktree mode** (with ticket): Works in a worktree, pulls PR comments first

## Arguments

- Empty or `--loop`: Local mode - review uncommitted code in current directory
- Ticket ID (e.g., `NES-123`): Worktree mode - work in worktree, pull PR comments
- Text after identifier: Treated as local tasks (both modes)

Examples:
- `/update-pr` - local mode, single cycle
- `/update-pr --loop` - local mode, continuous loop
- `/update-pr NES-123` - worktree mode for ticket
- `/update-pr NES-123 ## Comment 1: Fix the bug...` - worktree mode + local tasks
- `/update-pr --loop ## Comment 1: Add tests...` - local mode + local tasks

## Mode Selection

**Do not read file contents** - only track file paths, counts, and brief summaries.

**Content Access Policy:**

- **Allowed operations**: stat/lstat for metadata, recording file paths and sizes,
  computing hashes, using jq to extract JSON keys/paths, using `git diff --stat`
  or `git ls-files` for filenames
- **Prohibited operations**: opening and parsing file text, reading full file into
  memory, running grep/sed/awk to inspect content

### Argument Parsing

Parse arguments to identify:
- `has_loop`: Whether `--loop` flag is present
- `ticket_id`: A ticket ID like `NES-123` (matches pattern `[A-Z]+-\d+`)
- `local_tasks_text`: Any text after the identifier/flags (for inline tasks)

Extract `identifier` (first word) and `local_tasks_text` (remainder after identifier).

**Mode determination:**
- If `ticket_id` provided: **Worktree Mode**
- Otherwise: **Local Mode** (with or without `--loop`)

---

## Common Variables

Both modes use these variables:

- `cycle`: Counter starting at 1
- `max_cycles`: Maximum allowed cycles (default 10)
- `all_modified_files`: Set of all project files modified across all cycles
- `cycle_summaries`: List of brief summaries per cycle
- `loop_start_time`: Timestamp when the loop begins
- `initial_commit`: SHA of HEAD when loop started (for squashing)
- `commits_made`: Count of commits made during session
- `working_dir`: Directory where work happens (repo root or worktree)
- `tmp_folder`: `{{working_dir}}/.tmp/pr-review`
- `review_dir`: `{{working_dir}}/.review` (coderabbit output location)

---

## Local Mode

Works in current directory, reviews uncommitted code or most recent commit.

### Setup

```bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
```

Set:
- `repo_root`: Git repository root
- `working_dir`: Same as repo_root
- `current_branch`: Current git branch
- `initial_commit`: Current HEAD SHA (for squashing later)
- `base_branch`: Same as current_branch
- `tmp_folder`: `{{working_dir}}/.tmp/pr-review`
- `review_dir`: `{{working_dir}}/.review`
- `pr_number`: None (no PR in local mode)

Record `loop_start_time`. Initialize: `cycle = 1`, `commits_made = 0`.

### Import Local Tasks (if local_tasks_text exists)

Spawn a `local-task-importer` agent:

```python
Task(subagent_type="local-task-importer", model="haiku", prompt=f"""
local_tasks_text: {local_tasks_text}
tmp_folder: {tmp_folder}
""")
```

Creates `local_0.json`, `local_1.json`, etc. in `{{tmp_folder}}`.

### Loop Iteration

Repeat until clean or max_cycles reached:

#### Step 1: Check Cycle Limit

If `cycle > max_cycles`:
- Log warning and exit loop

Record `cycle_start_time`.

#### Step 2: Determine CodeRabbit Target

**First cycle:**

Check for uncommitted changes:
```bash
cd {{working_dir}} && git status --porcelain
```

- If uncommitted changes exist: Use `--type uncommitted`
- If no uncommitted changes: Use `--base-commit HEAD~1` (review most recent commit)

**Subsequent cycles (cycle > 1):**

Always use `--base-commit HEAD~1` (review the commit we just made).

#### Step 3: Run CodeRabbit

Run CodeRabbit synchronously and extract `review_file` from stdout:

```bash
cd {{working_dir}}
if [ "{{coderabbit_target}}" = "uncommitted" ]; then
  uv run review.coderabbit --output-dir {{review_dir}} -- --type uncommitted | uv run pr extract-review-path
else
  uv run review.coderabbit --output-dir {{review_dir}} -- --base-commit HEAD~1 | uv run pr extract-review-path
fi
```

If no review file or error, exit loop.

#### Step 4: Parse and Aggregate

```bash
cd {{working_dir}}
uv run pr parse-coderabbit --review-file {{review_file}} --output-dir {{tmp_folder}}
aggregated_json="{{tmp_folder}}/aggregated.json"
uv run pr aggregate-tasks --input-dir {{tmp_folder}} > "$aggregated_json"
```

If no tasks, remove review file and exit loop (clean state).

#### Step 5: Process Files in Parallel

Spawn `pr-comment-handler` agents - one per file in `tasks_by_file`.

For `__global__` tasks (local tasks without file paths), process sequentially.

Wait for all to complete.

#### Step 6: Run Tests on Changed Files

```python
py_files = [f for f in files if f.endswith(".py")]
for file_path in py_files:
    Task(subagent_type="test-debugger", prompt=f"""
    file: {file_path}
    worktree: {working_dir}
    """)
```

#### Step 7: Commit Changes

Check for changes to commit:
```bash
cd {{working_dir}} && git status --porcelain
```

If changes exist:
```bash
cd {{working_dir}} && git add -A && git commit -m "Address review feedback (cycle {{cycle}})"
```

Increment `commits_made`.

#### Step 8: Cleanup and Continue

```bash
rm -rf {{tmp_folder}}
rm -f {{review_file}}
```

Add `files` to `all_modified_files`.
Record cycle summary.
Increment `cycle`.
Continue loop.

---

## Worktree Mode

Works in a worktree for a PR, pulls PR comments on first cycle.

### Setup

Get PR info:
```bash
uv run pr get-pr {{ticket_id}}
```

Returns: `branch_name`, `worktree_path`, `working_directory`, `pr_number`, `base_branch`

If `working_directory` is not `.` (needs worktree):
```bash
uv run pr setup-worktree {{ticket_id}}
```

Set:
- `working_dir`: Resolved worktree path (absolute)
- `pr_number`: PR number from get-pr
- `base_branch`: Target branch for PR
- `current_branch`: Branch name
- `tmp_folder`: `{{working_dir}}/.tmp/pr-review`
- `review_dir`: `{{working_dir}}/.review`

Change to working directory and get initial commit:
```bash
cd {{working_dir}}
git rev-parse HEAD
```

Set `initial_commit`. Record `loop_start_time`. Initialize: `cycle = 1`, `commits_made = 0`.

### Import Local Tasks (if local_tasks_text exists)

Spawn a `local-task-importer` agent (same as Local Mode).

### Loop Iteration

#### Step 1: Check Cycle Limit

Same as local mode.

#### Step 2: Determine Review Source (First Cycle Only)

**First cycle only:**

Fetch PR comments:
```bash
uv run pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

Check if any thread files were created:
```bash
ls {{tmp_folder}}/thread_*.json 2>/dev/null | wc -l
```

- If threads exist: Skip CodeRabbit, use PR threads as tasks
- If no threads: Run CodeRabbit with `--base {{base_branch}}`

**Subsequent cycles:**

Always run CodeRabbit with `--base-commit HEAD~1`.

#### Step 3: Run CodeRabbit (if needed)

If not using PR threads, run CodeRabbit synchronously and extract `review_file` from stdout:

```bash
cd {{working_dir}}
if [ "{{cycle}}" -eq 1 ] && [ "{{no_pr_threads}}" = "true" ]; then
  uv run review.coderabbit --output-dir {{review_dir}} -- --base {{base_branch}} | uv run pr extract-review-path
else
  uv run review.coderabbit --output-dir {{review_dir}} -- --base-commit HEAD~1 | uv run pr extract-review-path
fi
```

Parse coderabbit output:
```bash
cd {{working_dir}}
uv run pr parse-coderabbit --review-file {{review_file}} --output-dir {{tmp_folder}}
```

#### Step 4: Aggregate Tasks

```bash
aggregated_json="{{tmp_folder}}/aggregated.json"
uv run pr aggregate-tasks --input-dir {{tmp_folder}} > "$aggregated_json"
```

If no tasks, exit loop (clean state).

#### Step 5: Process Files in Parallel

Same as local mode - spawn `pr-comment-handler` agents.

Handle `__global__` tasks (local tasks) sequentially after file-specific tasks.

#### Step 6: Run Tests

Same as local mode.

#### Step 7: Commit Changes

Same as local mode:
```bash
cd {{working_dir}}
git add -A
git commit -m "Address review feedback (cycle {{cycle}})"
```

#### Step 8: Cleanup and Continue

Same as local mode.

---

## Post-Loop: Finalize

After loop exits (for both modes):

### 1. Final Lint

Run lint on ALL files modified across all cycles:

```python
for file_path in all_modified_files:
    Task(subagent_type="lint-fixer", prompt=f'--worktree "{working_dir}" --files "{file_path}"')
```

### 2. Commit Lint Fixes

```bash
cd {{working_dir}}
git status --porcelain
```

If changes exist:
```bash
git add -A
git commit -m "Lint fixes"
```

Increment `commits_made`.

### 3. Squash Commits

If `commits_made > 1`:

```bash
cd {{working_dir}}
git reset --soft {{initial_commit}}
git commit -m "Address code review feedback"
```

**Note**: This squashes all commits made during the session into one.

### 4. Push

```bash
cd {{working_dir}}
git push origin {{current_branch}}
```

For worktree mode, if this is a new branch:
```bash
git push -u origin {{current_branch}}
```

### 5. Post Deferred Replies (Worktree Mode Only)

**Skip if not in worktree mode (no pr_number).**

```bash
uv run pr post-deferred-replies --pr {{pr_number}} --threads-dir {{tmp_folder}}
```

### 6. Collect Local Task Responses

If local tasks were processed, collect responses from `local_*.json` files:

```python
import json
from pathlib import Path

tmp_folder = Path("{{tmp_folder}}")
local_task_responses = []

for json_file in sorted(tmp_folder.glob("local_*.json")):
    data = json.loads(json_file.read_text())
    if "deferred_reply" in data:
        local_task_responses.append({
            "content": data.get("content", ""),
            "deferred_reply": data["deferred_reply"]
        })
```

### 7. Final Cleanup

```bash
rm -rf {{tmp_folder}}
```

### 8. Final Summary

```bash
cd {{working_dir}}
git diff --stat {{initial_commit}}..HEAD
```

Output:
```text
================================================================================
REVIEW COMPLETE
================================================================================

Mode: {{local_or_worktree}}
Branch: {{current_branch}}
{{#if pr_number}}
PR: #{{pr_number}}
{{/if}}
Cycles: {{cycle}}
Total elapsed: {{total_elapsed_formatted}}
Total files modified: {{len(all_modified_files)}}
Commits squashed: {{commits_made}}

Cycle summaries:
{{cycle_summaries}}

Files modified:
{{all_modified_files}}

Changes:
{{git_diff_stat}}

{{#if local_task_responses}}
--------------------------------------------------------------------------------
LOCAL TASK RESPONSES
--------------------------------------------------------------------------------
{{#each local_task_responses}}
### Local Task {{index}}

{{content}}

**Response:**

{{deferred_reply}}

{{/each}}
{{/if}}
================================================================================
```

---

## File Locations

All files are created relative to `working_dir` to support parallel execution:

| File Type | Location |
|-----------|----------|
| CodeRabbit reviews | `{{working_dir}}/.review/` |
| Task files | `{{working_dir}}/.tmp/pr-review/` |
| Thread files | `{{working_dir}}/.tmp/pr-review/thread_*.json` |
| Local task files | `{{working_dir}}/.tmp/pr-review/local_*.json` |
| Aggregated JSON | `{{working_dir}}/.tmp/pr-review/aggregated.json` |

This allows running reviews in parallel across multiple worktrees + main directory.

---

## Code Review Tools

* **CodeRabbit uncommitted**: `uv run review.coderabbit --output-dir {{review_dir}} -- --type uncommitted`
* **CodeRabbit vs branch**: `uv run review.coderabbit --output-dir {{review_dir}} -- --base <branch>`
* **CodeRabbit vs commit**: `uv run review.coderabbit --output-dir {{review_dir}} -- --base-commit <sha>`
* **PR threads**: `uv run pr fetch-threads --pr <number> --output-dir <dir>`
* **Timeout guidance**: Allow up to 2 hours for CodeRabbit

## Rules

- **This command must not read file contents** - only track paths
- **Minimize context** - store only paths, counts, and brief summaries
- No AI co-authors (see AGENTS.md)
- Never defer - implement or challenge
- Always use sub-agents for: comment handling, testing, linting
- Process sub-agents in parallel where possible
- Tests run after each cycle, lint only at end
- Always squash commits before pushing
- Always push at the end
- Post deferred replies only in worktree mode (when pr_number exists)
- All file paths relative to working_dir for parallel execution support
