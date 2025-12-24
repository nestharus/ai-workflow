# Update PR Command

---

description: Update a PR by handling unresolved review threads
allowed-tools: Task, Read, Glob, Bash

---

Handle unresolved PR review threads: $ARGUMENTS

## Arguments

- Empty: Use current branch (must be on PR branch)
- PR ID (`17` or `#17`): Get branch from GitHub PR
- Ticket ID (`NES-87`): Look up branch from Linear
- Branch name: Use directly
- Text after identifier: Treated as local tasks

Examples:
- `/update-pr` - current branch, only PR threads
- `/update-pr 17` - PR #17, only PR threads
- `/update-pr NES-123 ## Comment 1: Fix the bug...` - PR threads + local tasks

## Workflow

### 1. Parse Arguments

Extract `identifier` (first word) and `local_tasks_text` (remainder).

### 2. Get PR Information

```bash
uv run pr get-pr           # no arguments
uv run pr get-pr {{identifier}}  # with identifier
```

Returns: `branch_name`, `worktree_path`, `working_directory`, `is_worktree`, `pr_number`, `pr_url`, `base_branch`

### 3. Set Up Variables

```bash
git rev-parse --show-toplevel
uv run pr extract-ticket-id {{branch_name}}
```

Set:
- `ticket_id`, `branch`, `repo_root`
- `working_dir`: `{{repo_root}}/{{working_directory}}`
- `tmp_folder`: `{{repo_root}}/.tmp/pr-threads/{{ticket_id or pr_number}}`

### 4. Import Local Tasks (if local_tasks_text exists)

**Step 4a:** Write `local_tasks_text` to `{{tmp_folder}}/local_tasks_raw.txt`

**Step 4b:** Split into body files using Python:

```python
import re
from pathlib import Path

raw_file = Path("{{tmp_folder}}/local_tasks_raw.txt")
text = raw_file.read_text()

# Split by separator (--- or ## Comment N:)
parts = re.split(r"\n---+\n", text.strip())  # or r"(?=## Comment \d+:)"
parts = [p.strip() for p in parts if p.strip()]

for i, body in enumerate(parts):
    Path(f"{{tmp_folder}}/body_{i}.txt").write_text(body)
raw_file.unlink()
```

**Step 4c:** Import body files (creates `local_0.json`, `local_1.json`, deletes body files):

```bash
uv run pr import-local-tasks --output-dir {{tmp_folder}} {{tmp_folder}}/body_0.txt {{tmp_folder}}/body_1.txt ...
```

### 5. Fetch Unresolved Threads

```bash
uv run pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

This automatically:
- Fetches unresolved threads with line numbers (file-specific comments)
- Auto-resolves threads where first author gave thumbs-up reaction
- Saves as `thread_0.json`, `thread_1.json`, etc.

### 6. Process All Tasks (SEQUENTIAL)

**CRITICAL: Process tasks ONE AT A TIME. Do NOT run pr-comment-handler agents in parallel.**

List all `thread_*.json` and `local_*.json` in `{{tmp_folder}}`. Process each sequentially:

```python
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json
worktree: {{working_dir}}
branch: {{branch}}
")
```

Wait for each handler to complete before starting the next. This ensures changes don't conflict and each handler sees current codebase state.

Handler returns `action: resolve` (thread resolved) or `action: implement` (changes made, deferred reply stored). For LOCAL tasks, collect `deferred_reply` from each `local_*.json` for output summary.

### 7. Check for Code Changes

```bash
cd {{working_dir}} && git status --porcelain
```

If empty (no changes), skip steps 8-10 and go directly to step 11.

### 8. Run Test Debugger

**Skip if no code changes (step 7 empty).**

```python
Task(subagent_type="test-debugger", prompt="worktree: {{working_dir}}")
```

### 9. Run Lint Fixer

**Skip if no code changes (step 7 empty).**

```python
Task(subagent_type="lint-fixer", prompt="--worktree {{working_dir}} --changed-only")
```

Only lints modified files (faster, appropriate for PR updates).

### 10. Commit and Push

**Skip if no code changes (step 7 empty).**

```bash
uv run pr commit-push --worktree {{working_dir}} --message "Address PR review feedback"
```

### 11. Post Deferred Replies & Request Review

```bash
# Post deferred replies (skips LOCAL origin tasks automatically)
uv run pr post-deferred-replies --pr {{pr_number}} --threads-dir {{tmp_folder}}

# Request review only if code changes were made
uv run pr request-review --pr {{pr_number}}
```

### 12. Collect Local Task Responses

Read each `local_*.json` file in `{{tmp_folder}}` and collect the `deferred_reply` field from each.
These responses will be included in the output summary.

### 13. Cleanup

Delete the tmp folder for the PR comments that was created.

### 14. Output Summary

Get commit information:

```bash
cd {{working_dir}}
# Current branch commit (HEAD of PR branch)
git rev-parse HEAD
# Target branch commit (what PR merges into)
git rev-parse origin/{{base_branch}}
```

Print to terminal:

```text
================================================================================
PR UPDATE COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: {{ticket_id or "N/A"}}
{{#if ticket_id}}
Run `uv run linear get-issue <TICKET_ID>` to fetch plan.
{{/if}}
Pull Request: {{pr_url}}

References:
  working_directory: {{working_dir}}
  current_branch_commit: <CURRENT_SHA>   # HEAD of PR branch (latest)
  pr_target_branch_commit: <TARGET_SHA>  # HEAD of target branch

Review Process:
1. Read ticket description for the implementation plan
2. Read files in working directory for complete implementation understanding
3. Look at current commit to see the latest changes
4. Diff branch against pr_target_branch_commit for all changes

Commands:
  # Read implementation files
  cd {{working_dir}}

  # See latest commit details
  cd {{working_dir}} && git log -1

  # Diff all PR changes against target branch
  cd {{working_dir}} && git diff <pr_target_branch_commit>...<current_branch_commit>

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

## Rules

- No AI co-authors (see AGENTS.md)
- Never defer - implement or challenge
- **DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.**
- Use sub-agents for test-debugger and lint-fixer
