---
name: impl-reducer
description: Implements Reducer pattern - reduce/aggregate data
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Reducer Pattern Implementor

Implement the **Reducer** pattern - a function that reduces/aggregates multiple values into one.

## Pattern Definition

```python
def reduce_<what>(
    items: Iterable[T],
    initial: R | None = None,
) -> R:
    """Reduce items to single value.

    Args:
        items: Items to reduce
        initial: Starting value

    Returns:
        Aggregated result
    """
```

## Implementation Rules

1. **Associative operation**: (a op b) op c = a op (b op c)
2. **Identity element**: Provide sensible initial value
3. **Type-safe**: Input type T, output type R
4. **Handle empty**: Return identity for empty input
5. **Single pass**: Process items once

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def reduce_line_counts(file_stats: Iterable[FileStat]) -> int:
    """Reduce file statistics to total line count.

    Args:
        file_stats: File statistics to aggregate

    Returns:
        Total line count across all files
    """
    return sum(stat.line_count for stat in file_stats)


def reduce_errors_by_category(
    errors: Iterable[Error],
) -> dict[str, list[Error]]:
    """Reduce errors into groups by category.

    Args:
        errors: Errors to categorize

    Returns:
        Errors grouped by category
    """
    result: dict[str, list[Error]] = {}
    for error in errors:
        result.setdefault(error.category, []).append(error)
    return result
```

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
