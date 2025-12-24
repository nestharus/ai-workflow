# Lint-Fixer Sub-Agent Workflow

> **Metadata:** Description: Run lint-fixer sub-agent until all lint errors are
> fixed. Allowed tools: Task, Bash, Read, Grep, Glob, TodoWrite

Fix all lint errors AND warnings by repeatedly running the lint-fixer sub-agent.

## Arguments

* `--changed-only`: Only lint changed files (uncommitted first, then last commit if none)
* `--commit <sha>`: Only lint files from specific commit
* `--files <file1> <file2> ...`: Only lint specific files

## Workflow

### Step 1: Run Lint-Fixer Sub-Agent

```python
Task(subagent_type="lint-fixer", prompt="$ARGUMENTS")
```

Pass `--changed-only` or `--commit <sha>` through `$ARGUMENTS` if provided.

### Step 2: Evaluate Results

After lint-fixer returns, check its summary:

* **Success** (no errors remain): Done
* **Remaining fixable errors**: Return to Step 1
* **Manual fix requested**: Fix and return to Step 1
* **No progress after 2-3 iterations**: Go to Step 3 (Investigation)
* **Unfixable errors reported**: Go to Step 3 (Investigation)

### Step 3: Investigate Conflicting Linter Settings

**Triggers for investigation:**
* Lint-fixer explicitly reports errors as unfixable (with reasons)
* Error counts bouncing up and down without net reduction
* Same errors keep reappearing after being fixed

When triggered, spawn an investigation sub-agent (the sub-agent investigates, NOT you):

```python
Task(
  subagent_type="general-purpose",
  prompt="""
Investigate and resolve conflicting linter settings causing unfixable errors.

## Context from lint-fixer
<paste lint-fixer's "Remaining Issues" section here>

## Your Task
1. Read config files: .yamllint.yaml, pyproject.toml, .pymarkdown.json, .hadolint.yaml
2. Analyze for conflicts: line length, indentation, quote styles, block scalar preferences
3. Apply fixes to linter configs, document changes with comments

## Report Back
What conflicts found, what changes made, whether resolved, any remaining issues.
"""
)
```

**Important**: Include lint-fixer's error explanations so sub-agent knows what to investigate.

After sub-agent returns:
* If conflicts resolved: Return to Step 1
* If unresolvable: Go to Step 4

### Step 4: Report Unresolvable Issues

Document what was investigated, the specific conflict, why it cannot be resolved, then stop.

## Lint Commands

```bash
uv run lint [--changed-only]           # All linters
uv run lint ">=mypy" [--changed-only]  # From mypy onwards (use quotes!)
uv run lint ruff [--changed-only]      # Single linter
```

## Suppression Policy

The lint-fixer sub-agent AND any manual fixes must **NEVER** add `# noqa`, `# type: ignore`, or similar without explicit justification.

1. **Per-file ignores preferred**: Check `pyproject.toml` `[tool.ruff.lint.per-file-ignores]` first
2. **Inline suppressions require justification**: Only for genuine edge cases with explanatory comment
3. **Fix code, don't suppress**: Refactor to comply, not add suppressions
4. **Report, don't suppress**: If unfixable without suppression, report it - let caller decide

Reference: `docs/development/linting-strategy.yml` for approved ignores.

## Important Notes

* **Track progress**: Use TodoWrite to track remaining error counts per iteration
* **Pass context**: Include lint-fixer's error explanations when spawning investigation sub-agent
* **Don't persist when stuck**: Delegate investigation rather than re-running lint-fixer repeatedly
* **Investigation sub-agent can fix configs**: The sub-agent has permission to modify linter settings to resolve conflicts

## Success Criteria

Lint-fixer sub-agent produces no errors and no warnings.
