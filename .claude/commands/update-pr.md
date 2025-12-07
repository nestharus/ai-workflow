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

Run pr-agent with operation `fetch-threads`:

```
Task(subagent_type="pr-agent", prompt="
Operation: fetch-threads
ticket_id: {{ticket_id}}
tmp_folder: {{tmp_folder}}
worktree: {{worktree}}
branch: {{branch}}
pr_number: {{pr_number}}
")
```

### 4. Process Each Thread

List files in `{{tmp_folder}}` and for each thread file:

```
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json
worktree: {{worktree}}
branch: {{branch}}
")
```

### 5. Handle Responses

For each pr-comment-handler response:

- If `action: resolve`: Call pr-agent with `resolve-thread` operation
- If `action: reply`: Call pr-agent with `post-reply` operation
- If `action: implement`: Changes already made, continue to next thread

### 6. Run Tests

After all threads processed, run tests in the worktree:

```bash
cd {{worktree}} && uv run pytest
```

Next run lint-fixer sub-agent against the worktree.

### 7. Commit and Push

If tests pass and changes were made, call pr-agent:

```
Task(subagent_type="pr-agent", prompt="
Operation: commit-push
worktree: {{worktree}}
commit_message: Address PR review feedback
")
```

### 8. Request CodeRabbit Review

After push, call pr-agent:

```
Task(subagent_type="pr-agent", prompt="
Operation: request-review
pr_number: {{pr_number}}
")
```

Delete the tmp folder for the PR comments that was created.

## Important Rules

- Follow co-author rules in AGENTS.md (no AI co-authors)
- Only resolve threads that meet the thumbs-up criteria
- Never defer - implement or challenge, don't postpone
- Run tests in worktree and lint-fixer sub-agent against worktree before pushing
- DO NOT RUN LINTING DIRECTLY. USE THE SUB-AGENT.
