---
description: Run lint-fixer sub-agent until only markdown-restriction errors remain
allowed-tools: Task, Bash, Read, Grep, Glob, TodoWrite
---

Fix all lint errors in the project by repeatedly running the lint-fixer sub-agent.

## Workflow

### Step 1: Run Lint-Fixer Sub-Agent

Invoke the lint-fixer sub-agent with an empty prompt:

```
Task(subagent_type="lint-fixer", prompt="")
```

### Step 2: Evaluate Results

After the lint-fixer returns, check its summary:

- If the lint-fixer reports **success** (only markdown-restriction errors remain), you are done
- If the lint-fixer reports **remaining fixable errors** (ruff, mypy, yamllint, etc.), go to Step 3
- If the lint-fixer reports **errors are unfixable** (with reasons), go to Step 4 (Investigation)
- If the lint-fixer asks you to fix specific errors manually, fix them and return to Step 1
- If **no meaningful progress** after 2-3 iterations (same errors recurring), go to Step 4 (Investigation)

### Step 3: Verify Progress

If you are unsure whether the lint-fixer was successful:

1. Run `uv run lint` to check current lint status
2. Review the output for errors
3. If errors exist, return to Step 1
4. If no errors remain, you are done

### Step 4: Investigate Conflicting Linter Settings

When the lint-fixer reports **errors are unfixable** OR you observe **no meaningful progress**
after multiple iterations, delegate investigation to a sub-agent.

**Triggers for investigation:**
- The lint-fixer explicitly reports it cannot fix certain errors (review its stated reasons)
- Error counts are bouncing up and down without net reduction
- The same errors keep reappearing after being fixed

#### Spawn Investigation Sub-Agent

Use the Task tool with `subagent_type="general-purpose"` to investigate and fix linter conflicts:

```
Task(
  subagent_type="general-purpose",
  prompt="""
Investigate and resolve conflicting linter settings that are causing unfixable lint errors.

## Context from lint-fixer
<paste the lint-fixer's "Remaining Issues" section with its explanations here>

## Your Task
1. Read the linter configuration files:
   - `.yamllint.yaml` - YAML linting rules
   - `pyproject.toml` - Ruff, mypy, and other Python tool settings
   - `.pymarkdown.json` - Markdown linting rules
   - `.hadolint.yaml` - Dockerfile linting rules

2. Analyze for conflicts such as:
   - Line length differences between linters
   - Indentation rule conflicts
   - Quote style conflicts
   - Block scalar vs quoted string preferences

3. Use Firecrawl to research solutions:
   - Search for documentation on resolving the specific conflict
   - Look for best practices for multi-linter Python projects

4. Apply fixes:
   - Modify linter configuration to resolve conflicts
   - Ensure settings are aligned across all linters
   - Document any changes with comments in config files

## Report Back
Provide a summary of:
- What conflicts you found
- What configuration changes you made
- Whether the conflicts are now resolved
- Any remaining issues that could not be resolved (and why)
"""
)
```

**Important**: Include the lint-fixer's error explanations in the prompt so the sub-agent
knows exactly what to investigate.

#### After Sub-Agent Returns

Review the sub-agent's report:
- If conflicts were resolved, return to Step 1 to run lint-fixer again
- If issues remain unresolvable, go to Step 5

### Step 5: Report Unresolvable Issues

If after investigation you determine the issue cannot be resolved:

1. Document what you investigated
2. Explain the specific conflict
3. Report why it cannot be resolved
4. Stop - do not continue running lint-fixer

## Important Notes

- **Track progress** - use TodoWrite to track remaining error counts per iteration
- **Pass context to sub-agents** - include lint-fixer's error explanations when spawning investigation
- **Don't be persistent when stuck** - delegate investigation rather than re-running lint-fixer
- **Sub-agents can fix configs** - the investigation sub-agent has permission to modify linter settings

## Success Criteria

The project is fully linted when `uv run lint` produces output where the only failures are from the `markdown-restriction` linter.
