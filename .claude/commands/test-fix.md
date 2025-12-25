# Test-Fixer Sub-Agent Workflow

> **Metadata:** Description: Run test-fixer sub-agent until all tests pass and coverage
> thresholds are met. Allowed tools: Task, Bash, Read, Grep, Glob, TodoWrite

Fix all test failures and ensure coverage meets thresholds by running the test-fixer sub-agent.

## Workflow

### Step 1: Run Test-Fixer Sub-Agent

```python
Task(subagent_type="test-fixer", prompt="")
```

The test-fixer agent contains its own instructions; pass an empty string for the prompt.

### Step 2: Evaluate Results

After test-fixer returns, check its summary:

* **Success** (all tiers pass): Done
* **Remaining test failures**: Return to Step 1
* **Remaining coverage gaps**: Return to Step 1
* **No progress detected** (any of the following across 2+ consecutive iterations): Go to Step 3 (Investigation)
  - Identical failures: Same test failures persist with unchanged error signatures
  - No net reduction: Total failure count does not decrease between iterations
  - Coverage stagnation: Coverage percentage changes by less than 0.5% between iterations
* **Unfixable issues reported**: Go to Step 3 (Investigation)

### Step 3: Investigate Blocking Issues

**Triggers for investigation:**
* Test-fixer explicitly reports issues as unfixable (with reasons)
* Same failures keep reappearing after being fixed
* Coverage gaps that cannot be addressed without architectural changes

When triggered, spawn an investigation sub-agent:

```python
Task(
  subagent_type="general-purpose",
  prompt="""
Investigate and resolve blocking test issues.

## Context from test-fixer
<paste test-fixer's "Remaining Issues" section here>

## Your Task
1. Analyze the root cause of the blocking issue
2. Determine if it's a test problem, source code bug, or configuration issue
3. Apply fixes or document why the issue cannot be resolved

## Report Back
What was found, what changes made, whether resolved, any remaining issues.
"""
)
```

**Important**: Include test-fixer's error details so sub-agent knows what to investigate.

After sub-agent returns:
* If issues resolved: Return to Step 1
* If unresolvable: Go to Step 4

### Step 4: Report Unresolvable Issues

Document what was investigated, the specific issue, why it cannot be resolved, then stop.

## Test Commands

```bash
uv run test-coverage                    # All tiers
uv run test-coverage --tier unit        # Single tier
uv run test-coverage --no-validate      # Report only
uv run pytest tests/path/to/test.py -v  # Specific test
```

## Coverage Analysis

After `test-coverage`, query `.coverage/coverage.db`:

```bash
uv run coverage-summary                          # Overall summary
uv run coverage-files --limit 20                 # Files with issues
uv run coverage-file app/core/factory.py         # File details
uv run coverage-functions --limit 10             # Functions below threshold
```

## Important Notes

* **Track progress**: Use TodoWrite to track remaining failures/gaps per iteration
* **Pass context**: Include test-fixer's error details when spawning investigation sub-agent
* **Don't persist when stuck**: Delegate investigation rather than re-running test-fixer repeatedly
* **Prefer fixing source**: Fix source code bugs over modifying tests (unless tests are wrong)

## Success Criteria

Test-fixer sub-agent produces all tiers passing with coverage thresholds met.
