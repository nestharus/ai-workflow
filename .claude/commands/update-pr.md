---
description: Update a PR by handling unresolved review threads
allowed-tools: Task, Read, Glob, Bash, mcp__linear__get_issue
---

# Update PR Command

Handle unresolved PR review threads for ticket: $ARGUMENTS

## Workflow

### 1. Get Ticket Information from Linear

Use the Linear MCP to fetch the ticket details:
- Ticket ID: `$ARGUMENTS`
- Get: branch name, PR URL, ticket URL

Extract the PR number from the PR URL.

### 2. Set Up Variables

Based on Linear data:
- `ticket_id`: $ARGUMENTS
- `branch`: (from Linear issue git branch name)
- `worktree`: `.worktrees/$ARGUMENTS`
- `tmp_folder`: `.tmp/pr-threads/$ARGUMENTS`
- `pr_number`: (extracted from PR URL)
- `pr_url`: (from Linear attachments)
- `ticket_url`: Linear ticket URL

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

After each pr-comment-handler completes:

- If `action: reply`: Post the reply:
  ```bash
  uv run pr post-reply --pr {{pr_number}} --thread-file {{thread_file}} --body "{{reply_body}}"
  ```
- If `action: implement`: Changes and test updates already made, continue to next thread

### 6. Run Test Debugger

After ALL threads are processed, run the test-debugger sub-agent against the worktree:

```
Task(subagent_type="test-debugger", prompt="
worktree: {{worktree}}
")
```

This will:
- Run all tests in the worktree
- Debug and fix any failures
- Report the final test status

### 7. Run Lint Fixer

After tests pass, run the lint-fixer sub-agent against the worktree.

### 8. Commit and Push

If tests pass and changes were made:

```bash
uv run pr commit-push --worktree {{worktree}} --message "Address PR review feedback"
```

### 9. Request CodeRabbit Review

After push:

```bash
uv run pr request-review --pr {{pr_number}}
```

Delete the tmp folder for the PR comments that was created.

## Important Rules

- Follow co-author rules in AGENTS.md (no AI co-authors)
- Never defer - implement or challenge, don't postpone
- Run test-debugger and lint-fixer sub-agents against worktree before pushing
- DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.
