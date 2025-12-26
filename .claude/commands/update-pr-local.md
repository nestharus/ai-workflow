# Update PR Local Command

---

description: Handle local CodeRabbit review comments on uncommitted code
allowed-tools: Task, Read, Glob, Bash

---

Process local CodeRabbit review comments: $ARGUMENTS

## Overview

This command processes CodeRabbit review comments on local uncommitted code. Unlike `/update-pr`:
- Works with local uncommitted code (not a PR)
- Does not push changes
- Does not work in a worktree
- Uses the latest local CodeRabbit review file

## Arguments

- Empty: Use the latest CodeRabbit review file
- Review file path: Use a specific review file

Examples:
- `/update-pr-local` - use latest review file
- `/update-pr-local .review/20251120T094827Z.review.coderabbit` - use specific file

## Workflow

### 1. Get Review File

If arguments provided, use that path. Otherwise:

```bash
uv run review.latest --type coderabbit
```

Returns path to latest `.review/*.review.coderabbit` file.

### 2. Set Up Variables

```bash
git rev-parse --show-toplevel
git branch --show-current
```

Set:
- `repo_root`: Git repository root
- `working_dir`: Same as repo_root (no worktree)
- `current_branch`: Current git branch
- `tmp_folder`: `{{repo_root}}/.tmp/local-review`

### 3. Parse CodeRabbit Review

```bash
uv run pr parse-coderabbit --review-file {{review_file}} --output-dir {{tmp_folder}}
```

Creates `coderabbit_0.json`, `coderabbit_1.json`, etc.

### 4. Process All Tasks (SEQUENTIAL)

**CRITICAL: Process tasks ONE AT A TIME. Do NOT run pr-comment-handler agents in parallel.**

List all `coderabbit_*.json` in `{{tmp_folder}}`. Process each sequentially:

```python
Task(subagent_type="pr-comment-handler", prompt="
thread_file: {{tmp_folder}}/coderabbit_N.json
worktree: {{working_dir}}
branch: {{current_branch}}
")
```

Wait for each handler to complete before starting the next. This ensures changes don't conflict and each handler sees current codebase state.

Handler returns `action: implement` with changes made. Collect summaries from each for output.

### 5. Check for Code Changes

```bash
git status --porcelain
```

If empty (no changes), skip step 6.

### 6. Run Lint Fixer

**Skip if no code changes (step 5 empty).**

```python
Task(subagent_type="lint-fixer", prompt="--changed-only")
```

Only lints modified files (faster, appropriate for local updates).

### 7. Cleanup

Delete the tmp folder:

```bash
rm -rf {{tmp_folder}}
```

### 8. Output Summary

```bash
git diff --stat
```

Print to terminal:

```text
================================================================================
LOCAL REVIEW COMPLETE
================================================================================

Review file: {{review_file}}
Tasks processed: {{task_count}}

Changes made:
{{git_diff_stat}}

Next steps:
1. Review the changes: git diff
2. Run tests: uv run pytest
3. Commit when ready: git add -p && git commit

================================================================================
```

## Code Review Tools

Automated code reviews are performed using CodeRabbit and SonarQube. Agents must not run
these commands; a human must run them, and the agent fetches the latest artifact afterward.

### CodeRabbit

This command processes CodeRabbit reviews. CodeRabbit provides AI-driven feedback on
work-in-progress code.

* **Human-run command**: `uv run review.coderabbit -- [--base <branch> | --type <mode> |
  --base-commit <sha>] [extra coderabbit args]` (defaults to `--base main` when no target
  flag is provided)
* **Selection rule**: Choose exactly one of `--base`, `--type`, or `--base-commit`;
  do not combine
* **Agent retrieval**: `uv run review.latest --type coderabbit` (prints the newest
  `.review/*.review.coderabbit` path)
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

### SonarQube

SonarQube analysis is available but not processed by this command (local output is not
useful for agent processing). Documentation retained for reference.

* **Usage**: `./scripts/sonar_scan.sh [OPTIONS]`
* **Options**:
  * `-t, --token`: Authentication token (overrides `SONAR_TOKEN` env var)
  * `-u, --url`: SonarQube server URL (default: `http://localhost:9000`)
  * `--`: Arguments after this flag are passed directly to `sonar-scanner-cli`
* **Environment Variables**: `SONAR_TOKEN`, `SONAR_HOST_URL`
* **Human-run wrapper**: `uv run review.sonar -- [sonar_scan args]`
* **Agent retrieval**: `uv run review.latest --type sonar` (prints the newest
  `.review/*.review.sonar` path)
* **Log output**: Wrapper writes to `.review/<timestamp>.review.sonar` and echoes the path
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

## Rules

- No AI co-authors (see AGENTS.md)
- Never defer - implement or challenge
- Use sub-agent for lint-fixer
