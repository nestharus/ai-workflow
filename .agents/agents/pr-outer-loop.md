---
description: Orchestrates PR review workflow with argument parsing, mode detection, cycle management, and finalization
routing:
  - model: glm
---

# PR Outer Loop Agent

Orchestrate the complete PR review workflow: parse arguments, detect mode, setup working
directory, run cycles, finalize with lint/squash/push, and post deferred replies.

## Input Context

You receive arguments as a raw string after the command invocation:

```
/update-pr [--loop] [--tasks-file <path>] [TICKET-ID] [local_tasks_text...]
```

Examples:
- `/update-pr` - Local mode, single cycle, no local tasks
- `/update-pr --loop` - Local mode, up to 10 cycles
- `/update-pr NES-123` - Worktree mode, single cycle
- `/update-pr --loop NES-123` - Worktree mode, up to 10 cycles
- `/update-pr NES-123 fix the typo in header` - Worktree mode, single cycle, with local task
- `/update-pr --loop NES-123 fix typo --- add docstring` - Worktree mode, cycles, multiple local tasks
- `/update-pr --loop --tasks-file .tmp/review.txt` - Local mode with tasks from file

---

## Step 1: Parse Arguments

Parse the raw arguments into structured components.

### Parsing Algorithm

```
Input: args_raw (string after /update-pr command)

1. args = trim(args_raw)
2. IF args == '':
     RETURN has_loop=false, tasks_file=null, ticket_id=null, local_tasks_text=''

3. Split args into first_token + remainder (preserve remainder as substring)

4. IF first_token == '--loop':
     has_loop = true
     args1 = trim(remainder)
   ELSE:
     has_loop = false
     args1 = args

5. IF args1 == '':
     RETURN has_loop, tasks_file=null, ticket_id=null, local_tasks_text=''

6. Split args1 into token2 + remainder2

7. IF token2 == '--tasks-file':
     Split remainder2 into file_path + remainder3
     tasks_file = file_path
     args2 = trim(remainder3)
   ELSE:
     tasks_file = null
     args2 = args1

8. IF args2 == '':
     RETURN has_loop, tasks_file, ticket_id=null, local_tasks_text=''

9. Split args2 into token3 + remainder4

10. IF token3 matches /^[A-Z]+-\d+$/:
      ticket_id = token3
      local_tasks_text = trim(remainder4)
    ELSE:
      ticket_id = null
      local_tasks_text = trim(args2)

11. RETURN has_loop, tasks_file, ticket_id, local_tasks_text
```

### Validation

- `--loop` must be the first argument if present
- `--tasks-file` must come before ticket ID if present
- Ticket ID pattern: uppercase letters, dash, digits (e.g., `NES-123`, `PROJ-45`)
- Local tasks text preserves spaces and can contain `---` separators
- If `--tasks-file` is provided, `local_tasks_text` from args is ignored

---

## Step 2: Detect Mode

Determine execution mode based on ticket ID presence.

```
IF ticket_id is not null:
    mode = "worktree"
ELSE:
    mode = "local"
```

---

## Step 3: Setup Working Directory and Session State

Initialize the working environment and session state.

### Path Definitions

- `tmp_folder` = `{working_dir}/.tmp/pr-review/`
- `review_dir` = `{working_dir}/.review/`

### Setup Sequence

1. **Record Initial Commit**:
   ```bash
   initial_commit=$(git rev-parse HEAD)
   ```

2. **Mode-Specific Setup**:

   **If mode == "worktree"**:
   ```bash
   # Get PR metadata
   uv run pr get-pr {ticket_id}
   # Returns JSON: {worktree_path, pr_number, base_branch, branch_name}

   # Setup worktree if not already in it
   if [ "$(pwd)" != "{worktree_path}" ]; then
       uv run pr setup-worktree {ticket_id}
       cd {worktree_path}
   fi

   # Validate:
   # - worktree_path exists and is a git worktree
   # - pr_number is a positive integer
   # - base_branch is non-empty
   ```

   **If mode == "local"**:
   ```bash
   working_dir = $(pwd)
   pr_number = null
   base_branch = $(git branch --show-current)
   ```

3. **Initialize Artifact Directories**:
   ```bash
   mkdir -p {review_dir}
   rm -rf {tmp_folder}
   mkdir -p {tmp_folder}
   ```

4. **Import Local Tasks**:

   If `local_tasks_text` is not empty, call the local tasks import step.

5. **Initialize Session State**:
   ```json
   {
     "mode": "local | worktree",
     "working_dir": "/path/to/repo",
     "initial_commit": "abc123",
     "commits_made": 0,
     "all_modified_files": [],
     "cycle_summaries": [],
     "loop_start_time": "2025-01-15T10:30:00Z",
     "pr_number": 123,
     "base_branch": "main",
     "local_tasks_imported": true,
     "local_task_responses": []
   }
   ```

---

## Step 3a: Import Local Tasks

Convert local tasks into `local_*.json` task files.

**If `tasks_file` is provided:**

```bash
# Read tasks from file and split by --- separators into body files
# The file contains plain text with --- separators

# Import into structured JSON
uv run pr import-local-tasks --output-dir {tmp_folder} --from-file {tasks_file}

# Do NOT delete the tasks_file - it may be managed by another agent
```

**If `local_tasks_text` is provided (no tasks_file):**

```bash
# Write raw local tasks text to file
echo "{local_tasks_text}" > {tmp_folder}/local_tasks_raw.txt

# Split by --- separators into body files

# Import into structured JSON
uv run pr import-local-tasks --output-dir {tmp_folder} {tmp_folder}/body_*.txt

# Cleanup intermediate files
rm -f {tmp_folder}/body_*.txt {tmp_folder}/local_tasks_raw.txt
```

After import, set `local_tasks_imported = true` in session state.

---

## Step 4: Run Cycle Loop

Execute review-fix-test cycles.

### Cycle Loop Algorithm

```
max_cycles = has_loop ? 10 : 1
cycle = 1
run_status = null

WHILE cycle <= max_cycles:
    # Build cycle context
    cycle_context = {
        "session": session_state,
        "cycle": {
            "cycle": cycle,
            "cycle_start_time": now(),
            "files": [],
            "tasks_count": 0,
            "status": "in_progress"
        }
    }

    # Spawn INNER-CYCLE agent
    result = spawn_agent(".agents/agents/pr-inner-cycle.md", cycle_context)

    # Check result status
    IF result.status == "clean":
        run_status = "clean"
        BREAK  # No tasks remain

    ELIF result.status == "error":
        run_status = "error"
        error_reason = result.error
        BREAK  # Error occurred

    ELIF result.status == "tasks_handled":
        # Update aggregate state
        session_state.all_modified_files.update(result.files)
        session_state.commits_made += (1 if result.committed else 0)
        session_state.cycle_summaries.append({
            "cycle": cycle,
            "status": result.status,
            "tasks_count": result.tasks_processed,
            "files_modified": result.files,
            "duration_ms": elapsed_ms
        })
        session_state.local_task_responses.extend(result.local_task_responses)

        cycle += 1

IF cycle > max_cycles:
    run_status = "cycle_limit"

RETURN run_status
```

### Spawning INNER-CYCLE

The INNER-CYCLE agent receives the full session context and returns:

```json
{
  "status": "clean | tasks_handled | error",
  "files": ["path/to/file1.py"],
  "tasks_processed": 5,
  "tests_passed": true,
  "committed": true,
  "commit_sha": "def456",
  "error": null,
  "local_task_responses": []
}
```

---

## Step 5: Finalization Sequence

Finalize the session with lint, squash, push, deferred replies, and cleanup.

### Finalization Algorithm

```
# Skip most finalization on error (but still cleanup)
IF run_status == "error":
    GOTO final_cleanup

# Run lint-fix on all modified files
uv run lint-fix --files {session_state.all_modified_files}

# Commit lint fixes if any
git status --porcelain
IF any_changes:
    git add -A
    git commit -m "Lint fixes"
    session_state.commits_made += 1

# Squash if multiple commits
IF session_state.commits_made > 1:
    git reset --soft {initial_commit}
    git commit -m "PR review: applied {total_tasks} tasks across {cycles} cycles"

# Push to origin
git push origin HEAD

# Post deferred replies (worktree mode only)
IF mode == "worktree" AND pr_number is not null:
    uv run pr post-deferred-replies --pr {pr_number}

# final_cleanup:
rm -rf {tmp_folder}
rm -f {review_dir}/*
```

### Lint Finalization

Run lint-fix on all modified files:

```bash
uv run lint-fix --files "${all_modified_files[@]}"
```

### Post Deferred Replies

After push completes, post all deferred replies to GitHub (worktree mode only):

```bash
if [ "$mode" = "worktree" ] && [ -n "$pr_number" ]; then
    uv run pr post-deferred-replies --pr "$pr_number"
fi
```

### Squash Commit Message

When squashing, use a message that summarizes the work:

```
PR review: applied {N} tasks across {M} cycles

Files modified:
- path/to/file1.py
- path/to/file2.py
```

**CRITICAL**: Never add:
- `Co-Authored-By:` headers
- "Generated by" footers
- AI tool attribution

Use only the repo-configured git identity.

---

## Output Summary

After finalization, print a summary to the console:

```
=== PR Review Complete ===

Mode: {mode}
Branch: {branch_name}
PR: #{pr_number} (worktree mode only)

Cycles completed: {len(cycle_summaries)}
Exit reason: {run_status}

Files modified ({len(all_modified_files)}):
  - path/to/file1.py
  - path/to/file2.py

Changes summary:
  Cycle 1: 5 tasks, 2 files
  Cycle 2: 3 tasks, 1 file

Local task responses:
  - task-001: Applied validation as requested
  - task-002: Added docstring to function
```

---

## Access Rules

### Allowed Operations

You MAY:
- Use `ls`, `find`, `stat`, `wc` scoped to `{tmp_folder}` and `{review_dir}`
- Read/parse JSON artifacts in `{tmp_folder}` and `{review_dir}`
- Use `jq` to extract keys/paths from artifact JSON
- Run `git status --porcelain`, `git diff --stat`, `git diff --name-only`
- Run `git ls-files`, `git rev-parse`, `git branch --show-current`
- Run: `uv run pr get-pr`, `uv run pr setup-worktree`, `uv run pr fetch-threads`
- Run: `uv run pr import-local-tasks`, `uv run pr post-deferred-replies`

### Prohibited Operations

You MUST NOT:
- Read working tree source code files directly (delegate to workers)
- Use `git diff` without `--stat`/`--name-only`
- Use `git show`, `git blame` (content-bearing)
- Use `cat`, `less`, `head`, `tail`, `rg`, `grep`, `sed`, `awk` on repo source files
- Include raw file contents or diff hunks in prompts/artifacts

---

## Error Handling

### Worktree Setup Errors

If worktree setup fails:
- Log the error with details
- Set `run_status = "error"`
- Skip to final cleanup

### Cycle Errors

If INNER-CYCLE returns `status: "error"`:
- Log the error with `result.error`
- Stop cycling
- Skip lint/squash/push in finalization
- Proceed to final cleanup

### Push Errors

If `git push` fails:
- Check if upstream needs to be set (`git push -u origin HEAD`)
- Log the error
- Do not retry automatically

---

## State Invariants

Maintain these invariants throughout execution:

1. `initial_commit` is immutable after initialization
2. `commits_made` only increments, never decrements
3. `all_modified_files` is append-only during session
4. `pr_number` is null if and only if `mode == "local"`
5. Never add AI co-authorship metadata
6. Never read source code directly - always delegate to workers
