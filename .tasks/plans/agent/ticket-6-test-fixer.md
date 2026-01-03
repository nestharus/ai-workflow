# Ticket 6: Test Fixer Agent

Implements: [TASK-04](plan.md#task-04--implement-test-fixer-agent)

## Implements

- Component: [COM-04](design-map.md#component-com-04-test-fixer)
- Algorithms: ALG-TEST-01, ALG-TEST-02, ALG-TEST-03
- Contracts: [CON-10](design-map.md#component-com-04-test-fixer)
- PRD Rules: ROUTE-08

## Dependencies

- Requires: [TASK-01](plan.md#task-01--configure-complexity-router-models), [TASK-02](plan.md#task-02--define-state-schemas)

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-test-fixer.md` |

## Acceptance Criteria

- [ ] Agent instruction file created
- [ ] Runs pytest for specific file
- [ ] Classifies failure severity
- [ ] Routes to appropriate Codex model (per [ROUTE-08](requirements.md#route-08))
- [ ] Applies fixes using selected model
- [ ] Returns result with status

## Severity-Based Routing

Per [ROUTE-08](requirements.md#route-08):

| Severity | Criteria | Model |
|----------|----------|-------|
| Low | Simple assertion failure, typo | Codex Medium |
| Medium | Logic error, missing case | Codex High |
| High | Complex failure, multiple fixes needed | Codex XHigh |

## Severity Classification

```
LOW:
- AssertionError with simple value mismatch
- ImportError with clear missing import
- NameError with typo

MEDIUM:
- Multiple assertion failures
- Type errors
- Attribute errors

HIGH:
- Failures in multiple test functions
- Complex fixture issues
- Integration test failures
```

## Input Context

```json
{
  "file_path": "path/to/source.py",
  "test_file": "tests/test_source.py"
}
```

## Output Result

```json
{
  "file_path": "path/to/source.py",
  "status": "success | error",
  "tests_passed": true,
  "fixes_applied": ["Fixed assertion in test_foo", "Added import"]
}
```
