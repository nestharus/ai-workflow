# Lint-Fixer Sub-Agent Workflow

> **Metadata:** Description: Run lint-fixer sub-agent until all lint errors are
> fixed. Allowed tools: Task, Bash, Read, Grep, Glob, TodoWrite

Fix all lint errors AND warnings in the project by repeatedly running the lint-fixer sub-agent.

## Arguments

This command accepts the following optional arguments via `$ARGUMENTS`:

* `--changed-only`: Only lint files that have been changed (uncommitted or last commit).
  When this flag is present, the lint-fixer sub-agent will only check changed files,
  and verification commands will also be scoped to changed files.

## Workflow

### Step 0: Parse Arguments

Check if `--changed-only` was provided in `$ARGUMENTS`:

* If `--changed-only` is present, set `CHANGED_ONLY_MODE=true`
* Otherwise, set `CHANGED_ONLY_MODE=false`

When in changed-only mode, detect the changed files once at the start for use in Step 3:

```bash
# Get uncommitted changes (staged + unstaged), deduplicated
UNCOMMITTED=$( (git diff --name-only HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null) | sort -u)

# If no uncommitted changes, get files from last commit
if [ -z "$UNCOMMITTED" ]; then
    CHANGED_FILES=$(git diff --name-only HEAD~1..HEAD 2>/dev/null)
else
    CHANGED_FILES=$UNCOMMITTED
fi
```

### Step 1: Run Lint-Fixer Sub-Agent

Invoke the lint-fixer sub-agent with the appropriate arguments:

**Standard mode** (no `--changed-only`):

```bash
Task(subagent_type="lint-fixer", prompt="")
```

**Changed-only mode** (with `--changed-only`):

```bash
Task(subagent_type="lint-fixer", prompt="--changed-only")
```

### Step 2: Evaluate Results

After the lint-fixer returns, check its summary:

* If the lint-fixer reports **success** (no lint errors remain), you are done
* If the lint-fixer reports **remaining fixable errors or warnings** (ruff, mypy, yamllint, etc.), go to Step 3
* If the lint-fixer reports **errors or warnings are unfixable** (with reasons), go to Step 4 (Investigation)
* If the lint-fixer asks you to fix specific errors or warnings manually, fix them and return to Step 1
* If **no meaningful progress** after 2-3 iterations (same errors or warnings recurring), go to Step 4 (Investigation)

### Step 3: Verify Progress

If you are unsure whether the lint-fixer was successful:

**Standard mode** (no `--changed-only`):

1. Run to check current lint status:
   * `uv run lint scripts` - Validates pyproject.toml script entry point naming conventions
   * `uv run lint ruff` - Auto-formats code and fixes linting issues
   * `uv run lint mypy` - Type checking
   * `uv run lint hadolint` - Dockerfile linting
   * `uv run lint pymarkdown` - Markdown validation
   * `uv run lint yamllint` - YAML validation
   * `uv run lint actionlint` - GitHub Actions workflow linting
   * `uv run lint dotenvlint` - .env file validation
   * `uv run lint checkov` - OpenAPI schema security scans
   * `uv run lint detect-secrets` - Secret detection in code
   * `uv run lint gitleaks` - Git leak detection
   * `uv run lint trivy` - Security vulnerability scanning
2. Review the output for errors and warnings
3. If errors or warnings exist, return to Step 1
4. If no errors and no warnings remain, you are done

**Changed-only mode** (with `--changed-only`):

1. Run linters with `--files` flag using the `$CHANGED_FILES` from Step 0:
   * `uv run lint ruff --files $CHANGED_FILES`
   * `uv run lint mypy --files $CHANGED_FILES`
   * `uv run lint hadolint --files $CHANGED_FILES`
   * `uv run lint pymarkdown --files $CHANGED_FILES`
   * `uv run lint yamllint --files $CHANGED_FILES`
   * `uv run lint actionlint --files $CHANGED_FILES`
   * `uv run lint dotenvlint --files $CHANGED_FILES`
   * `uv run lint detect-secrets --files $CHANGED_FILES`
   * `uv run lint gitleaks --files $CHANGED_FILES`
   * Note: `scripts`, `checkov`, and `trivy` linters do not support `--files` and are skipped in changed-only mode
2. Review the output for errors and warnings
3. If errors or warnings exist, return to Step 1
4. If no errors and no warnings remain, you are done

### Step 4: Investigate Conflicting Linter Settings

When the lint-fixer reports **errors or warnings are unfixable** OR you observe **no meaningful progress**
after multiple iterations, delegate investigation to a sub-agent.

**Triggers for investigation:**
* The lint-fixer explicitly reports it cannot fix certain errors or warnings (review its stated reasons)
* Error counts are bouncing up and down without net reduction
* The same errors or warnings keep reappearing after being fixed

#### Spawn Investigation Sub-Agent

Use the Task tool with `subagent_type="general-purpose"` to investigate and fix linter conflicts:

```bash
Task(
  subagent_type="general-purpose",
  prompt="""
Investigate and resolve conflicting linter settings that are causing unfixable lint errors or warnings.

## Context from lint-fixer
<paste the lint-fixer's "Remaining Issues" section with its explanations here>

## Your Task
1. Read the linter configuration files:
   * `.yamllint.yaml` - YAML linting rules
   * `pyproject.toml` - Ruff, mypy, and other Python tool settings
   * `.pymarkdown.json` - Markdown linting rules
   * `.hadolint.yaml` - Dockerfile linting rules

2. Analyze for conflicts such as:
   * Line length differences between linters
   * Indentation rule conflicts
   * Quote style conflicts
   * Block scalar vs quoted string preferences

3. Use Firecrawl to research solutions:
   * Search for documentation on resolving the specific conflict
   * Look for best practices for multi-linter Python projects

4. Apply fixes:
   * Modify linter configuration to resolve conflicts
   * Ensure settings are aligned across all linters
   * Document any changes with comments in config files

## Report Back
Provide a summary of:
* What conflicts you found
* What configuration changes you made
* Whether the conflicts are now resolved
* Any remaining issues that could not be resolved (and why)
"""
)
```

**Important**: Include the lint-fixer's error explanations in the prompt so the sub-agent
knows exactly what to investigate.

#### After Sub-Agent Returns

Review the sub-agent's report:
* If conflicts were resolved, return to Step 1 to run lint-fixer again
* If issues remain unresolvable, go to Step 5

### Step 5: Report Unresolvable Issues

If after investigation you determine the issue cannot be resolved:

1. Document what you investigated
2. Explain the specific conflict
3. Report why it cannot be resolved
4. Stop - do not continue running lint-fixer

## Important Notes

* **Track progress** - use TodoWrite to track remaining error counts per iteration
* **Pass context to sub-agents** - include lint-fixer's error explanations when spawning investigation
* **Don't be persistent when stuck** - delegate investigation rather than re-running lint-fixer
* **Sub-agents can fix configs** - the investigation sub-agent has permission to modify linter settings

## CRITICAL: No Random Suppressions

The lint-fixer sub-agent and any manual fixes must **NEVER** add `# noqa`, `# type: ignore`,
or similar suppression comments to silence warnings unless explicitly justified.

### Policy

1. **Per-file ignores are preferred** - The project uses `pyproject.toml` `[tool.ruff.lint.per-file-ignores]`
   for systematic patterns (tests, scripts, etc.). Check if the file already has the rule ignored.

2. **Inline suppressions require justification** - Only add inline noqa for:
   * Production S608 with validated paths (must have explanatory comment)
   * Root-level scripts needing S603 for subprocess
   * Genuine edge cases with no applicable per-file ignore

3. **Fix code, don't suppress** - The proper fix is to refactor code to comply with rules,
   not to add suppressions.

4. **Report, don't suppress** - If the lint-fixer cannot fix an error without adding a
   suppression, it should report it as unfixable. You can then decide whether to:
   * Add a per-file ignore to `pyproject.toml` (for systematic patterns)
   * Add an inline suppression with justification (for genuine edge cases)
   * Escalate for human review

### Reference

See `docs/development/linting-strategy.yml` for the full linting strategy and approved ignores.

## Success Criteria

The project is fully linted when lint-fixer sub-agent produces no errors and no warnings.
