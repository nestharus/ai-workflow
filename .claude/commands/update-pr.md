---
description: Update a PR by handling unresolved review threads
allowed-tools: Task, Read, Glob, Bash
---

# Update PR Command

Handle unresolved PR review threads for ticket: $ARGUMENTS

## Arguments

The first argument is the ticket ID. Any text after the ticket ID is treated as local tasks.

Example: `/update-pr NES-123` - only PR threads
Example: `/update-pr NES-123 ## Comment 1: Fix the bug...` - PR threads + local tasks

## Workflow

### 1. Parse Arguments

Split `$ARGUMENTS` to extract:
- `ticket_id`: First word (e.g., `NES-123`)
- `local_tasks_text`: Everything after the ticket ID (may be empty)

### 2. Get PR Information

```bash
uv run pr get-pr {{ticket_id}}
```

This returns JSON with:
- `branch_name`: Git branch name
- `pr_number`: PR number
- `pr_url`: PR URL
- `base_branch`: Target branch the PR will merge into

### 3. Set Up Variables

First, get the repository root (where `.worktrees` lives):
```bash
git rev-parse --show-toplevel
```

Based on ticket info:
- `ticket_id`: (from step 1)
- `branch`: (from `branch_name` in JSON)
- `repo_root`: (from git command above)
- `worktree`: `{{repo_root}}/.worktrees/{{branch}}`
- `tmp_folder`: `{{repo_root}}/.tmp/pr-threads/{{branch}}`
- `pr_number`: (from `pr_number` in JSON)
- `pr_url`: (from `pr_url` in JSON)
- `base_branch`: (from `base_branch` in JSON)

### 4. Import Local Tasks

If `local_tasks_text` is not empty:

**Step 4a: Write to tmp file**

Write the full `local_tasks_text` to a temporary file:
```
{{tmp_folder}}/local_tasks_raw.txt
```

**Step 4b: Split into body files**

Identify the pattern that separates tasks (e.g., `---` on its own line, or `## Comment N:` headers).
Run an inline Python script to split the file into individual body files:

```python
import re
from pathlib import Path

raw_file = Path("{{tmp_folder}}/local_tasks_raw.txt")
text = raw_file.read_text()

# Split by the identified pattern (adjust regex as needed)
# Example for --- separator:
parts = re.split(r"\n---+\n", text.strip())
# Example for ## Comment N: headers:
# parts = re.split(r"(?=## Comment \d+:)", text.strip())

parts = [p.strip() for p in parts if p.strip()]

for i, body in enumerate(parts):
    body_file = Path(f"{{tmp_folder}}/body_{i}.txt")
    body_file.write_text(body)

# Delete the raw file
raw_file.unlink()
```

**Step 4c: Import body files**

Pass the body files to the github client to create the local task JSON files:

```bash
uv run pr import-local-tasks --output-dir {{tmp_folder}} {{tmp_folder}}/body_0.txt {{tmp_folder}}/body_1.txt ...
```

This creates `local_0.json`, `local_1.json`, etc. and deletes the body files.

### 5. Fetch Unresolved Threads

```bash
uv run pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

This automatically:
- Fetches all unresolved threads from the PR
- Filters to only threads with line numbers (file-specific comments)
- Auto-resolves threads where the first author gave a thumbs-up reaction
- Formats and saves remaining threads as JSON files (`thread_0.json`, `thread_1.json`, etc.)

### 6. Process All Tasks (SEQUENTIAL)

**CRITICAL: Process tasks ONE AT A TIME. Do NOT run pr-comment-handler agents in parallel.**

List all files in `{{tmp_folder}}` matching `thread_*.json` and `local_*.json`. Process each sequentially:

```
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json (or local_N.json)
worktree: {{worktree}}
branch: {{branch}}
")
```

Wait for each pr-comment-handler to complete before starting the next one. This ensures:
- Changes from one task don't conflict with another
- Test updates are applied incrementally
- Each handler sees the current state of the codebase

### 7. Handle Responses

After each pr-comment-handler completes, it returns one of:

- `action: resolve` - Thread was resolved (discussion concluded with agreement)
- `action: implement` - Changes were made (and optionally a deferred reply stored)

No additional action needed from the orchestrator - the handler already:
- Resolved the thread if appropriate (for GITHUB origin only)
- Made code changes if needed
- Stored any deferred replies for later posting/output

**For LOCAL tasks**: Collect the `deferred_reply` from each `local_*.json` file after processing. These will be included in the output summary.

Continue to next task.

### 8. Check for Code Changes

After all tasks are processed, check if any code changes were made:

```bash
cd {{worktree}} && git status --porcelain
```

If the output is empty (no changes), skip steps 9-11 and go directly to step 14 (Output Summary).

### 9. Run Test Debugger

**Skip this step if no code changes were made (step 8 output was empty).**

Run the test-debugger sub-agent against the worktree:

```
Task(subagent_type="test-debugger", prompt="
worktree: {{worktree}}
")
```

This will:
- Run all tests in the worktree
- Debug and fix any failures
- Report the final test status

### 10. Run Lint Fixer

**Skip this step if no code changes were made (step 8 output was empty).**

After tests pass, run the lint-fixer sub-agent against the worktree in changed-only mode:

```
Task(subagent_type="lint-fixer", prompt="--worktree {{worktree}} --changed-only")
```

This only lints files that were modified, which is faster and appropriate for PR updates.

### 11. Commit and Push

**Skip this step if no code changes were made (step 8 output was empty).**

If tests pass and changes were made:

```bash
uv run pr commit-push --worktree {{worktree}} --message "Address PR review feedback"
```

### 12. Post Deferred Replies (GitHub only)

Post any deferred replies stored in thread files (skips LOCAL origin tasks automatically):

```bash
uv run pr post-deferred-replies --pr {{pr_number}} --threads-dir {{tmp_folder}}
```

### 13. Request CodeRabbit Review

**Skip this step if no code changes were made (step 8 output was empty).**

Only request CodeRabbit review if there were code changes:

```bash
uv run pr request-review --pr {{pr_number}}
```

### 14. Collect Local Task Responses

Read each `local_*.json` file in `{{tmp_folder}}` and collect the `deferred_reply` field from each. These responses will be included in the output summary.

### 15. Cleanup

Delete the tmp folder for the PR comments that was created.

### 16. Output Summary

Get commit information:
```bash
cd {{worktree}}
# Current branch commit (HEAD of PR branch)
git rev-parse HEAD
# Target branch commit (what PR merges into)
git rev-parse origin/{{base_branch}}
```

Print to terminal:

```
================================================================================
PR UPDATE COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: {{ticket_id}}
Linear Ticket: https://linear.app/issue/{{ticket_id}}
Pull Request: {{pr_url}}

References:
  worktree_directory: {{worktree}}
  current_branch_commit: <CURRENT_SHA>   # HEAD of PR branch (latest changes)
  pr_target_branch_commit: <TARGET_SHA>  # HEAD of target branch (merge base)

Review Process:
1. Read ticket description for the implementation plan
2. Read worktree files for complete implementation understanding
3. Look at current commit to see the latest changes
4. Diff branch against pr_target_branch_commit for all changes

Commands:
  # Read implementation files
  cd {{worktree}}

  # See latest commit details
  cd {{worktree}} && git log -1

  # Diff all PR changes against target branch
  cd {{worktree}} && git diff <pr_target_branch_commit>...<current_branch_commit>

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

## Important Rules

- Follow co-author rules in AGENTS.md (no AI co-authors)
- Never defer - implement or challenge, don't postpone
- Run test-debugger and lint-fixer sub-agents against worktree before pushing
- DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.
