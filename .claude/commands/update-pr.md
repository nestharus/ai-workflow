# Update PR Command

---

description: Update a PR by handling unresolved review threads
allowed-tools: Task, Read, Glob, Bash

---

Handle unresolved PR review threads: $ARGUMENTS

## Arguments

* If `$ARGUMENTS` is empty: Use current branch (must be on PR branch)
* If `$ARGUMENTS` is a PR ID (e.g., `17` or `#17`): Get branch from GitHub PR
* If `$ARGUMENTS` is a ticket ID (e.g., `NES-87`): Look up branch from Linear
* If `$ARGUMENTS` is a branch name: Use branch directly
* Additional text after identifier: Treated as local tasks

Example: `/update-pr` - use current branch, only PR threads
Example: `/update-pr 17` - PR #17, only PR threads
Example: `/update-pr NES-123` - ticket NES-123, only PR threads
Example: `/update-pr NES-123 ## Comment 1: Fix the bug...` - PR threads + local tasks

## Workflow

### 1. Parse Arguments

Split `$ARGUMENTS` to extract:

* `identifier`: First word (PR ID, ticket ID, or branch name), or empty if no arguments
* `local_tasks_text`: Everything after the identifier (may be empty)

### 2. Get PR Information

If `identifier` is empty (no arguments), call without arguments:

```bash
uv run pr get-pr
```

Otherwise, pass only the identifier (first word):

```bash
uv run pr get-pr {{identifier}}
```

Note: `get-pr` accepts PR ID (17/#17), ticket ID (NES-123), branch name, or nothing.

This returns JSON with:

* `branch_name`: Git branch name (may contain slashes, e.g., `mrasolomon/nes-87-...`)
* `worktree_path`: Path to the worktree (e.g., `.worktrees/mrasolomon/nes-87-...`), or `null` if on branch
* `working_directory`: Where to run commands - either `.` (repo root) or the worktree path
* `is_worktree`: Boolean - `true` if working in worktree, `false` if on current branch
* `pr_number`: PR number
* `pr_url`: PR URL
* `base_branch`: Target branch the PR will merge into

### 3. Set Up Variables

First, get the repository root (where `.worktrees` lives):

```bash
git rev-parse --show-toplevel
```

Extract ticket ID from branch name (for tmp folder and Linear link):

```bash
uv run pr extract-ticket-id {{branch_name}}
```

This returns JSON with `ticket_id` (e.g., `NES-87`) or `null` if no valid ticket pattern found.

Based on the info gathered:

* `ticket_id`: (from `extract-ticket-id` output, may be `null`)
* `branch`: (from `branch_name` in JSON)
* `repo_root`: (from git command above)
* `working_dir`: `{{repo_root}}/{{working_directory}}` (from `working_directory` in JSON - either `.` or worktree path)
* `tmp_folder`: `{{repo_root}}/.tmp/pr-threads/{{ticket_id}}` (use `pr_number` if no ticket_id)
* `pr_number`: (from `pr_number` in JSON)
* `pr_url`: (from `pr_url` in JSON)
* `base_branch`: (from `base_branch` in JSON)

### 4. Import Local Tasks

If `local_tasks_text` is not empty:

#### Step 4a: Write to tmp file

Write the full `local_tasks_text` to a temporary file:

```text
{{tmp_folder}}/local_tasks_raw.txt
```

#### Step 4b: Split into body files

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

#### Step 4c: Import body files

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

* Fetches all unresolved threads from the PR
* Filters to only threads with line numbers (file-specific comments)
* Auto-resolves threads where the first author gave a thumbs-up reaction
* Formats and saves remaining threads as JSON files (`thread_0.json`, `thread_1.json`, etc.)

### 6. Process All Tasks (SEQUENTIAL)

**CRITICAL: Process tasks ONE AT A TIME. Do NOT run pr-comment-handler agents in parallel.**

List all files in `{{tmp_folder}}` matching `thread_*.json` and `local_*.json`. Process each sequentially:

```python
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json (or local_N.json)
worktree: {{working_dir}}
branch: {{branch}}
")
```

Wait for each pr-comment-handler to complete before starting the next one. This ensures:

* Changes from one task don't conflict with another
* Test updates are applied incrementally
* Each handler sees the current state of the codebase

### 7. Handle Responses

After each pr-comment-handler completes, it returns one of:

* `action: resolve` - Thread was resolved (discussion concluded with agreement)
* `action: implement` - Changes were made (and optionally a deferred reply stored)

No additional action needed from the orchestrator - the handler already:

* Resolved the thread if appropriate (for GITHUB origin only)
* Made code changes if needed
* Stored any deferred replies for later posting/output

**For LOCAL tasks**: Collect the `deferred_reply` from each `local_*.json` file after processing.
These will be included in the output summary.

Continue to next task.

### 8. Check for Code Changes

After all tasks are processed, check if any code changes were made:

```bash
cd {{working_dir}} && git status --porcelain
```

If the output is empty (no changes), skip steps 9-11 and go directly to step 14 (Output Summary).

### 9. Run Test Debugger

**Skip this step if no code changes were made (step 8 output was empty).**

Run the test-debugger sub-agent against the working directory:

```python
Task(subagent_type="test-debugger", prompt="
worktree: {{working_dir}}
")
```

This will:

* Run all tests in the working directory
* Debug and fix any failures
* Report the final test status

### 10. Run Lint Fixer

**Skip this step if no code changes were made (step 8 output was empty).**

After tests pass, run the lint-fixer sub-agent against the working directory in changed-only mode:

```python
Task(subagent_type="lint-fixer", prompt="--worktree {{working_dir}} --changed-only")
```

This only lints files that were modified, which is faster and appropriate for PR updates.

### 11. Commit and Push

**Skip this step if no code changes were made (step 8 output was empty).**

If tests pass and changes were made:

```bash
uv run pr commit-push --worktree {{working_dir}} --message "Address PR review feedback"
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

Read each `local_*.json` file in `{{tmp_folder}}` and collect the `deferred_reply` field from each.
These responses will be included in the output summary.

### 15. Cleanup

Delete the tmp folder for the PR comments that was created.

### 16. Output Summary

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
Linear Ticket: `uv run linear get-issue <TICKET_ID>`
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

## Important Rules

* Follow co-author rules in AGENTS.md (no AI co-authors)
* Never defer - implement or challenge, don't postpone
* Run test-debugger and lint-fixer sub-agents against working directory before pushing
* DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.
