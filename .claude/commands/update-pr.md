---
description: Update a PR by handling unresolved review threads
allowed-tools: Task, Read, Glob, Bash
---

# Update PR Command

Handle unresolved PR review threads for ticket: $ARGUMENTS

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:
- `branch_name`: Git branch name
- `pr_number`: PR number
- `pr_url`: PR URL
- `base_branch`: Target branch the PR will merge into

### 2. Set Up Variables

Based on ticket info:
- `ticket_id`: $ARGUMENTS
- `branch`: (from `branch_name` in JSON)
- `worktree`: `.worktrees/$ARGUMENTS`
- `tmp_folder`: `.tmp/pr-threads/$ARGUMENTS`
- `pr_number`: (from `pr_number` in JSON)
- `pr_url`: (from `pr_url` in JSON)
- `base_branch`: (from `base_branch` in JSON)

### 3. Fetch Unresolved Threads

```bash
uv run pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

This automatically:
- Fetches all unresolved threads from the PR
- Filters to only threads with line numbers (file-specific comments)
- Auto-resolves threads where the first author gave a thumbs-up reaction
- Formats and saves remaining threads as JSON files (`thread_0.json`, `thread_1.json`, etc.)

### 4. Process Each Thread (SEQUENTIAL)

**CRITICAL: Process threads ONE AT A TIME. Do NOT run pr-comment-handler agents in parallel.**

List files in `{{tmp_folder}}` and for each thread file, process sequentially:

```
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json
worktree: {{worktree}}
branch: {{branch}}
")
```

Wait for each pr-comment-handler to complete before starting the next one. This ensures:
- Changes from one thread don't conflict with another
- Test updates are applied incrementally
- Each handler sees the current state of the codebase

### 5. Handle Responses

After each pr-comment-handler completes, it returns one of:

- `action: resolve` - Thread was resolved (discussion concluded with agreement)
- `action: implement` - Changes were made (and optionally a deferred reply stored)

No additional action needed from the orchestrator - the handler already:
- Resolved the thread if appropriate
- Made code changes if needed
- Stored any deferred replies for later posting

Continue to next thread.

### 6. Check for Code Changes

After all threads are processed, check if any code changes were made:

```bash
cd {{worktree}} && git status --porcelain
```

If the output is empty (no changes), skip steps 7-9 and go directly to step 11 (Output Summary).

### 7. Run Test Debugger

**Skip this step if no code changes were made (step 6 output was empty).**

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

### 8. Run Lint Fixer

**Skip this step if no code changes were made (step 6 output was empty).**

After tests pass, run the lint-fixer sub-agent against the worktree in changed-only mode:

```
Task(subagent_type="lint-fixer", prompt="--worktree {{worktree}} --changed-only")
```

This only lints files that were modified, which is faster and appropriate for PR updates.

### 9. Commit and Push

**Skip this step if no code changes were made (step 6 output was empty).**

If tests pass and changes were made:

```bash
uv run pr commit-push --worktree {{worktree}} --message "Address PR review feedback"
```

### 10. Request CodeRabbit Review

Post any deferred replies and request CodeRabbit review. The command automatically skips the review request if there are no deferred replies AND no code changes.

If code changes were made (step 6 output was non-empty):
```bash
uv run pr request-review --pr {{pr_number}} --threads-dir {{tmp_folder}} --has-code-changes
```

If no code changes were made:
```bash
uv run pr request-review --pr {{pr_number}} --threads-dir {{tmp_folder}}
```

Delete the tmp folder for the PR comments that was created.

### 11. Output Summary

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
================================================================================
```

## Important Rules

- Follow co-author rules in AGENTS.md (no AI co-authors)
- Never defer - implement or challenge, don't postpone
- Run test-debugger and lint-fixer sub-agents against worktree before pushing
- DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.
