---
description: Update code based on PR review comments or direct feedback
argument-hint: pr-url or pr-number or ticket-id or "direct feedback text"
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# Update Branch

Update code based on feedback for `$ARGUMENTS`.

This command can handle:
1. **PR URL or PR number**: Fetches unresolved review comments from the PR
2. **Direct feedback**: Applies user-provided comments/changes directly

Parse arguments: PR URL, PR number (e.g., `17` or `#17`), ticket ID (e.g., `NES-87`), branch name, or direct feedback text.

## Workflow

### Step 1: Determine Feedback Source

Check if `$ARGUMENTS` is a PR reference (URL/number/ticket/branch) or direct feedback:

**If PR reference (contains numbers, slashes, or ticket pattern):**
- Proceed to Step 2 (fetch PR comments)

**If direct feedback (freeform text):**
- Skip to Step 2b (handle direct feedback)

### Step 2: Parse Arguments and Get PR Information (PR Reference Flow)

If `$ARGUMENTS` is empty, use current branch:

```bash
uv run pr get-pr
```

Otherwise, pass the argument:

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:
- `branch_name`: Git branch name
- `worktree_path`: Path to worktree or `null` if on branch
- `working_directory`: Where to run commands (`.` or worktree path)
- `is_worktree`: Boolean indicating if using worktree
- `pr_number`: PR number
- `pr_url`: PR URL
- `base_branch`: Target branch the PR merges into

Get repository root:

```bash
git rev-parse --show-toplevel
```

Extract ticket ID from branch name:

```bash
uv run pr extract-ticket-id {{branch_name}}
```

This returns JSON with `ticket_id` (e.g., `NES-87`) or `null`.

Set up variables:
- `ticket_id`: From extract-ticket-id output (may be null)
- `branch`: From branch_name in JSON
- `repo_root`: From git command
- `working_dir`: `{{repo_root}}/{{working_directory}}`
- `tmp_folder`: `{{repo_root}}/.tmp/update-branch/{{ticket_id or pr_number}}`
- `pr_number`: From pr_number in JSON
- `pr_url`: From pr_url in JSON
- `base_branch`: From base_branch in JSON

Create tmp folder:

```bash
mkdir -p {{tmp_folder}}
```

Proceed to Step 3 (fetch PR threads).

### Step 2b: Handle Direct Feedback (Direct Feedback Flow)

When direct feedback is provided (not a PR reference):

Set up variables:
- `branch`: Current git branch
- `repo_root`: From `git rev-parse --show-toplevel`
- `working_dir`: `{{repo_root}}`
- `tmp_folder`: `{{repo_root}}/.tmp/update-branch/direct-feedback`
- `feedback_text`: `$ARGUMENTS`

Create tmp folder:

```bash
mkdir -p {{tmp_folder}}
```

Write feedback to file:

```bash
echo "$feedback_text" > {{tmp_folder}}/direct_feedback.md
```

Skip to Step 4b (process direct feedback).

### Step 3: Fetch Unresolved PR Threads (PR Reference Flow)

Fetch all unresolved review comments from the PR:

```bash
uv run pr fetch-threads --pr {{pr_number}} --output-dir {{tmp_folder}}
```

This automatically:
- Fetches all unresolved threads from the PR
- Filters to only threads with line numbers (file-specific comments)
- Auto-resolves threads where the first author gave a thumbs-up reaction
- Saves remaining threads as JSON files (`thread_0.json`, `thread_1.json`, etc.)

If no thread files are created, skip to Step 9 (no comments to address).

### Step 4: Process Each Review Thread Sequentially (PR Reference Flow)

**CRITICAL: Process threads ONE AT A TIME. Do NOT run in parallel.**

List all files in `{{tmp_folder}}` matching `thread_*.json`. Process each sequentially:

For each thread file:

#### 4a. Analyze Reviewer Intent

Invoke the pr-comment-handler agent:

```python
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/thread_N.json
worktree: {{working_dir}}
branch: {{branch}}
")
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

When direct feedback is provided:

Invoke the feedback-handler agent:

```python
Task(subagent_type="feedback-handler", prompt="
feedback_file: {{tmp_folder}}/direct_feedback.md
worktree: {{working_dir}}
branch: {{branch}}
ticket_id: {{ticket_id or 'N/A'}}
")
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

Fetch the implementation plan from the Linear ticket (if ticket_id exists):

```bash
uv run linear get-issue-description {{ticket_id}} > {{tmp_folder}}/plan.md
```

Run implementation drift review:

```python
Task(subagent_type="implementation-drift-reviewer", prompt="
ticket_id: {{ticket_id}}
plan_file: {{tmp_folder}}/plan.md
working_dir: {{working_dir}}
")
```

If drift review fails, the reviewer will report specific drift issues. The handlers
should have followed the plan, so drift failures indicate either:
1. The plan needs updating (use `/update-plan` command)
2. The implementation deviated from plan (need to fix code)

Report the drift issues and stop. The user must decide whether to update the plan or fix the code.

### Step 7: Run Lint Fixer

**Skip this step if no code changes were made.**

Run lint-fixer in changed-only mode:

```python
Task(subagent_type="lint-fixer", prompt="--worktree {{working_dir}} --changed-only")
```

This lints only the modified files.

### Step 8: Run Test Debugger

**Skip this step if no code changes were made.**

Run test-debugger to ensure all tests pass:

```python
Task(subagent_type="test-debugger", prompt="
worktree: {{working_dir}}
")
```

This will:
- Run all tests in the working directory
- Debug and fix any failures
- Report final test status

If tests fail after debugging, report the failures and stop.

### Step 9: Commit and Push Changes

**Skip this step if no code changes were made.**

Commit and push the changes:

```bash
uv run pr commit-push --worktree {{working_dir}} --message "Address feedback"
```

### Step 10: Post Deferred Replies (PR Reference Flow Only)

**Skip this step if using direct feedback flow.**

Post any deferred replies stored in thread files:

```bash
uv run pr post-deferred-replies --pr {{pr_number}} --threads-dir {{tmp_folder}}
```

This posts replies to GitHub for threads where the handler stored a response.

### Step 11: Resolve Addressed Threads (PR Reference Flow Only)

**Skip this step if using direct feedback flow.**

The pr-comment-handler already resolved threads where appropriate during processing (Step 4).
No additional resolution needed here.

### Step 12: Request Review (PR Reference Flow Only)

**Skip this step if no code changes were made or using direct feedback flow.**

Request CodeRabbit review:

```bash
uv run pr request-review --pr {{pr_number}}
```

### Step 13: Write Receipt

Write a receipt documenting the update:

```bash
mkdir -p {{tmp_folder}}/receipts
cat > {{tmp_folder}}/receipts/update-branch-receipt.md << 'EOF'
# Code Update Receipt

{{#if pr_number}}
**PR**: {{pr_number}}
{{/if}}
**Ticket**: {{ticket_id or "N/A"}}
**Branch**: {{branch}}
**Timestamp**: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Operation**: UPDATE
**Feedback Source**: {{#if pr_number}}PR Review Comments{{else}}Direct Feedback{{/if}}

## Inputs Used
{{#if pr_number}}
- PR review comments from {{pr_url}}
{{else}}
- Direct feedback from user
{{/if}}
- Existing code in {{working_dir}}
{{#if ticket_id}}
- Implementation plan from Linear ticket {{ticket_id}}
{{/if}}

## Outputs Produced
- Updated code in {{working_dir}}
- Test updates
- Lint fixes
{{#if code_changes}}
- Git commit and push to {{branch}}
{{/if}}

{{#if pr_number}}
## Threads Processed
<COUNT> review threads processed
<COUNT_RESOLVED> threads resolved through discussion
<COUNT_IMPLEMENTED> threads addressed with code changes
{{else}}
## Feedback Processed
Direct feedback applied to branch
{{/if}}

## Reviews Performed
{{#if code_changes}}
- Implementation drift review (passed)
- Lint review (passed)
- Test suite (passed)
{{else}}
- No code changes - skipped reviews
{{/if}}

## Deviations
None

## Next Action Recommended
{{#if code_changes}}
{{#if pr_number}}
Review the updated PR: {{pr_url}}
{{else}}
Review the updated branch: {{branch}}
{{/if}}
{{else}}
{{#if pr_number}}
All comments resolved through discussion. PR ready for re-review.
{{else}}
No changes were needed based on feedback.
{{/if}}
{{/if}}
EOF
```

### Step 14: Cleanup

Delete the tmp folder:

```bash
rm -rf {{tmp_folder}}
```

### Step 15: Output Summary

Get commit information:

```bash
cd {{working_dir}}
# Current branch commit (HEAD of branch)
git rev-parse HEAD
# Target branch commit (what PR merges into, if PR exists)
{{#if base_branch}}
git rev-parse origin/{{base_branch}}
{{/if}}
```

Print to terminal:

```text
================================================================================
BRANCH UPDATE COMPLETE{{#if pr_number}} - REVIEW REQUESTED{{/if}}
================================================================================

{{#if ticket_id}}
Ticket: {{ticket_id}}
Run `uv run linear get-issue {{ticket_id}}` to fetch plan.
{{/if}}
{{#if pr_number}}
Pull Request: {{pr_url}}
{{else}}
Branch: {{branch}}
{{/if}}

References:
  working_directory: {{working_dir}}
  current_branch_commit: <CURRENT_SHA>   # HEAD of branch (latest)
{{#if base_branch}}
  pr_target_branch_commit: <TARGET_SHA>  # HEAD of target branch
{{/if}}

{{#if code_changes}}
Changes Summary:
{{#if pr_number}}
  - <COUNT> review threads processed
  - <COUNT_RESOLVED> resolved through discussion
  - <COUNT_IMPLEMENTED> addressed with code changes
{{else}}
  - Direct feedback applied
{{/if}}
  - Implementation drift review: PASSED
  - Lint review: PASSED
  - Test suite: PASSED

Review Process:
1. Read ticket description for the implementation plan
2. Read files in working directory for complete implementation understanding
3. Look at current commit to see the latest changes
{{#if base_branch}}
4. Diff branch against pr_target_branch_commit for all changes
{{/if}}

Commands:
  # Read implementation files
  cd {{working_dir}}

  # See latest commit details
  cd {{working_dir}} && git log -1

{{#if base_branch}}
  # Diff all changes against target branch
  cd {{working_dir}} && git diff <pr_target_branch_commit>...<current_branch_commit>
{{/if}}
{{else}}
{{#if pr_number}}
No code changes were made. All review comments were resolved through discussion.
The PR is ready for re-review.
{{else}}
No code changes were made based on the provided feedback.
{{/if}}
{{/if}}

Receipt written to: {{tmp_folder}}/receipts/update-branch-receipt.md
================================================================================
```

## Error Handling

* If PR fetch fails, report the error and stop
* If no unresolved threads found (PR flow) and no feedback provided (direct flow), report success (nothing to update) and skip to cleanup
* If handler fails, report the error and stop
* If implementation drift review fails, report drift issues and stop (user must decide: update plan or fix code)
* If lint fixer fails, report lint issues and stop
* If test debugger fails, report test failures and stop
* If commit/push fails, report the error and stop
* Always clean up tmp folder, even on errors
* Always write a receipt (mark as FAILED if errors occurred)

## Important Rules

* Process threads/feedback sequentially, not in parallel
* Always run implementation drift review after code changes
* Always run lint fixer and test debugger before pushing
* Never defer work - implement or challenge, don't postpone
* Write receipts for all operations
* The handlers are responsible for:
  - Analyzing intent (reviewer or user)
  - Making code changes
  - Updating/adding tests
  - Resolving threads when appropriate (PR flow)
  - Storing deferred replies (PR flow)

## Feedback Source Detection

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
