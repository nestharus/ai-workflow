---
name: impl-filter
description: Implements Filter pattern - yields elements that pass predicate (stream)
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Filter Pattern Implementor

Implement the **Filter** pattern - a stream function that yields elements only if they pass a predicate.

## Pattern Definition

```python
def filter_<what>(iterable: Iterable[T], predicate: Callable[[T], bool]) -> Iterator[T]:
    """Filter iterable, yielding elements that pass predicate.

    Args:
        iterable: Source iterable
        predicate: Function that returns True for elements to keep

    Yields:
        Elements where predicate returns True
    """
    for item in iterable:
        if predicate(item):
            yield item
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

A filter is part of stream processing:
- Used WITH walkers in pipelines
- For each element: if predicate passes, yield; otherwise skip
- Unlike classifier (returns bool), filter yields or doesn't yield
- Lazy evaluation - processes on demand

## Implementation Rules

1. **Stream-based**: Uses `yield`, not `return`
2. **Predicate-driven**: Yields only if predicate returns True
3. **Lazy**: Processes elements on demand
4. **Composable**: Can chain with other stream operations
5. **Clear naming**: `filter_<what_is_being_filtered>`

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def filter_valid(items: Iterable[T], is_valid: Callable[[T], bool]) -> Iterator[T]:
    """Filter to only valid items.

    Args:
        items: Items to filter
        is_valid: Validity predicate

    Yields:
        Items where is_valid returns True
    """
    for item in items:
        if is_valid(item):
            yield item


def filter_by_type(items: Iterable[Any], target_type: type) -> Iterator[Any]:
    """Filter items by type.

    Args:
        items: Mixed items
        target_type: Type to keep

    Yields:
        Items of target type
    """
    for item in items:
        if isinstance(item, target_type):
            yield item


def filter_non_empty(strings: Iterable[str]) -> Iterator[str]:
    """Filter out empty strings.

    Args:
        strings: String iterable

    Yields:
        Non-empty strings
    """
    for s in strings:
        if s.strip():
            yield s


def filter_modified_since(
    files: Iterable[Path],
    since: datetime,
) -> Iterator[Path]:
    """Filter files modified since a date.

    Args:
        files: File paths
        since: Cutoff datetime

    Yields:
        Files modified after since
    """
    for f in files:
        if f.exists():
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime > since:
                yield f
```

## Usage in Stream Pipeline

```python
# Composing with walker
for commit in filter_valid(
    walk_commits(repo_path),
    is_merge_commit
):
    process(commit)

# Chaining filters
pipeline = filter_non_empty(
    filter_by_type(
        walk_json_values(data, "message"),
        str
    )
)
```

## Filter vs Classifier

| Filter | Classifier |
|--------|------------|
| Yields or doesn't yield | Returns True/False |
| Stream operation | Pure function |
| `filter_*(iter, pred)` → Iterator | `is_*(data)` → bool |
| Used in pipelines | Used in conditions |
