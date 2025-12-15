---
description: Update code based on PR review comments or direct feedback
---

# Update Branch

Update code based on feedback from PR review comments or direct user input.

Input: `{{input}}` (pr-url, pr-number, ticket-id, branch-name, or direct feedback text)

## Prerequisites

- For PR flow: PR must exist with review comments
- For direct feedback flow: Working branch must exist

## Arguments

The command automatically detects the feedback source:

**PR Reference (triggers PR flow):**
- Contains only digits (PR number): `17`
- Starts with `#` (PR number): `#17`
- Contains `github.com` or `/pull/` (PR URL)
- Matches ticket pattern (e.g., `NES-87`)
- Looks like a branch name (contains `/` or `-`)

**Direct Feedback (triggers direct flow):**
- Freeform text that doesn't match PR patterns
- Examples:
  - "Add error handling for network timeouts"
  - "Refactor the UserService to use dependency injection"
  - "Fix the bug in the calculateTotal function where negative values are not handled"

## Workflow

### Step 1: Determine Feedback Source

Check if input is a PR reference (URL/number/ticket/branch) or direct feedback.

**If PR reference:** Proceed to Step 2 (fetch PR comments)
**If direct feedback:** Skip to Step 2b (handle direct feedback)

### Step 2: Parse Arguments and Get PR Information (PR Reference Flow)

If input is empty, use current branch. Otherwise, pass the argument:

```bash
pr get-pr {{input}}
```

This returns JSON with branch details, worktree path, PR info, etc.

Get repository root and extract ticket ID:

```bash
git rev-parse --show-toplevel
pr extract-ticket-id {{branch_name}}
```

Set up variables:
- ticket_id, branch, repo_root, working_dir, tmp_folder, pr_number, pr_url, base_branch

Create tmp folder.

Proceed to Step 3 (fetch PR threads).

### Step 2b: Handle Direct Feedback (Direct Feedback Flow)

When direct feedback is provided (not a PR reference):

Set up variables:
- branch: Current git branch
- repo_root, working_dir, tmp_folder, feedback_text

Create tmp folder and write feedback to file:

```bash
echo "{{input}}" > {{tmp_folder}}/direct_feedback.md
```

Skip to Step 4b (process direct feedback).

### Step 3: Fetch Unresolved PR Threads (PR Reference Flow)

Fetch all unresolved review comments from the PR:

```bash
pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

This automatically:
- Fetches all unresolved threads from the PR
- Filters to only threads with line numbers (file-specific comments)
- Auto-resolves threads where the first author gave a thumbs-up reaction
- Saves remaining threads as JSON files

If no thread files are created, skip to Step 9 (no comments to address).

### Step 4: Process Each Review Thread Sequentially (PR Reference Flow)

**CRITICAL: Process threads ONE AT A TIME. Do NOT run in parallel.**

List all files in tmp_folder matching `thread_*.json`. Process each sequentially.

For each thread file, invoke the pr-comment-handler agent using #agent:pr-comment-handler:

```text
#agent:pr-comment-handler
thread_file: {{tmp_folder}}/thread_N.json
worktree: {{working_dir}}
branch: {{branch}}
```

Wait for completion. The handler returns one of:
- `action: resolve` - Thread resolved through discussion (no code changes)
- `action: implement` - Code changes made (and optionally deferred reply stored)

The handler already:
- Resolved the thread if appropriate
- Made code changes if needed
- Updated or added tests
- Stored any deferred replies

Continue to next thread.

### Step 4b: Process Direct Feedback (Direct Feedback Flow)

When direct feedback is provided, invoke the feedback-handler agent using #agent:feedback-handler:

```text
#agent:feedback-handler
feedback_file: {{tmp_folder}}/direct_feedback.md
worktree: {{working_dir}}
branch: {{branch}}
ticket_id: {{ticket_id or 'N/A'}}
```

The handler will:
- Analyze the feedback to understand requested changes
- Identify affected files and components
- Make necessary code changes
- Update or add tests as needed
- Document changes made

### Step 5: Check for Code Changes

After all threads/feedback are processed, check if any code changes were made:

```bash
cd {{working_dir}} && git status --porcelain
```

If output is empty (no changes), skip to Step 10 (cleanup and summary).

### Step 6: Run Implementation Drift Review

**Skip this step if no code changes were made.**

Fetch the implementation plan from the Linear ticket (if ticket_id exists) and run implementation drift review using #agent:implementation-drift-reviewer.

If drift review fails, report drift issues and stop. The user must decide whether to update the plan or fix the code.

### Step 7: Run Lint Fixer

**Skip this step if no code changes were made.**

Run lint-fixer using #agent:lint-fixer in changed-only mode.

### Step 8: Run Test Debugger

**Skip this step if no code changes were made.**

Run test-debugger using #agent:test-debugger to ensure all tests pass. This will debug and fix any failures.

If tests fail after debugging, report the failures and stop.

### Step 9: Commit and Push Changes

**Skip this step if no code changes were made.**

Commit and push the changes:

```bash
pr commit-push --worktree {{working_dir}} --message "Address feedback"
```

### Step 10: Post Deferred Replies (PR Reference Flow Only)

**Skip this step if using direct feedback flow.**

Post any deferred replies stored in thread files:

```bash
pr post-deferred-replies --pr {{pr_number}} --threads-dir {{tmp_folder}}
```

### Step 11: Resolve Addressed Threads (PR Reference Flow Only)

**Skip this step if using direct feedback flow.**

The pr-comment-handler already resolved threads where appropriate during processing. No additional resolution needed.

### Step 12: Request Review (PR Reference Flow Only)

**Skip this step if no code changes were made or using direct feedback flow.**

Request CodeRabbit review:

```bash
pr request-review --pr {{pr_number}}
```

### Step 13: Write Receipt

Write a receipt documenting the update in `{{tmp_folder}}/receipts/update-branch-receipt.md`.

### Step 14: Cleanup

Delete the tmp folder.

### Step 15: Output Summary

Print comprehensive summary including:
- Ticket and PR information
- References (working_directory, commits)
- Changes summary (threads processed, reviews performed)
- Review process instructions
- Commands for viewing changes
- Receipt location

## Output

The command will output:
- Summary of feedback processed
- Changes made (if any)
- Review status (if code changed)
- Commands for viewing the implementation
- Receipt location

## Error Handling

- If PR fetch fails, report the error and stop
- If no unresolved threads found (PR flow) and no feedback provided (direct flow), report success (nothing to update) and skip to cleanup
- If handler fails, report the error and stop
- If implementation drift review fails, report drift issues and stop (user must decide: update plan or fix code)
- If lint fixer fails, report lint issues and stop
- If test debugger fails, report test failures and stop
- If commit/push fails, report the error and stop
- Always clean up tmp folder, even on errors
- Always write a receipt (mark as FAILED if errors occurred)

## Important Rules

- Process threads/feedback sequentially, not in parallel
- Always run implementation drift review after code changes
- Always run lint fixer and test debugger before pushing
- Never defer work - implement or challenge, don't postpone
- Write receipts for all operations
- The handlers are responsible for analyzing intent, making code changes, updating/adding tests, resolving threads (PR flow), and storing deferred replies (PR flow)

## Notes

- This command supports both PR review comments and direct feedback
- Feedback source is automatically detected based on input format
- For PR flow: threads are processed sequentially and can be resolved or implemented
- For direct feedback flow: feedback is processed as a single unit
- All code changes are validated through drift review, lint, and tests before pushing
