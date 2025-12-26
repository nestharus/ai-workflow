---
name: impl-zip
description: Implements Zip pattern - combine multiple streams index-by-index
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Zip Pattern Implementor

Implement the **Zip** pattern - combine multiple streams index-by-index into one.

## Pattern Definition

```python
def zip_<what>(
    *iterables: Iterable[T]
) -> Iterator[tuple[T, ...]]:
    """Combine streams index-by-index.

    Args:
        iterables: Streams to combine

    Yields:
        Tuples of aligned elements
    """
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

A zip combines streams by alignment (index/time):
- Many-to-one pattern
- Elements paired by position
- Opposite of Splitter (one-to-many)
- Different from Reducer (aggregates single stream)

For aggregating a single stream, use **Reducer** instead.
For building from parts (not streams), use **Builder** instead.

## Implementation Rules

1. **Index-aligned**: Elements paired by position
2. **Multiple inputs**: Takes N streams
3. **Single output**: Produces one combined stream
4. **Shortest wins**: Stops when shortest stream exhausts (default)
5. **Clear naming**: `zip_<what_is_being_combined>`

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def zip_streams(*iterables: Iterable[T]) -> Iterator[tuple[T, ...]]:
    """Combine streams index-by-index.

    Args:
        iterables: Streams to combine

    Yields:
        Tuples of aligned elements
    """
    return zip(*iterables)


def zip_longest_streams(
    *iterables: Iterable[T],
    fillvalue: T | None = None
) -> Iterator[tuple[T | None, ...]]:
    """Combine streams, padding shorter ones.

    Args:
        iterables: Streams to combine
        fillvalue: Value for exhausted streams

    Yields:
        Tuples of aligned elements (padded)
    """
    return itertools.zip_longest(*iterables, fillvalue=fillvalue)


def zip_with(
    fn: Callable[..., R],
    *iterables: Iterable[T]
) -> Iterator[R]:
    """Combine streams using a function.

    Args:
        fn: Function to combine elements
        iterables: Streams to combine

    Yields:
        Results of applying fn to aligned elements
    """
    for items in zip(*iterables):
        yield fn(*items)


def zip_commits_with_diffs(
    commits: Iterable[Commit],
    diffs: Iterable[Diff]
) -> Iterator[tuple[Commit, Diff]]:
    """Combine commit and diff streams.

    Args:
        commits: Commit stream
        diffs: Diff stream

    Yields:
        Paired (commit, diff) tuples
    """
    return zip(commits, diffs)


def zip_requests_with_responses(
    requests: Iterable[Request],
    responses: Iterable[Response]
) -> Iterator[tuple[Request, Response]]:
    """Combine request and response streams.

    Args:
        requests: Request stream
        responses: Response stream

    Yields:
        Paired (request, response) tuples
    """
    return zip(requests, responses)


def zip_keys_values(
    keys: Iterable[K],
    values: Iterable[V]
) -> dict[K, V]:
    """Combine key and value streams into dict.

    Args:
        keys: Key stream
        values: Value stream

    Returns:
        Dict from zipped pairs
    """
    return dict(zip(keys, values))


def zip_with_index(iterable: Iterable[T]) -> Iterator[tuple[int, T]]:
    """Combine stream with index positions.

    Args:
        iterable: Source stream

    Yields:
        (index, element) tuples
    """
    return enumerate(iterable)
```

## Zip vs Reducer

| Zip | Reducer |
|-----|---------|
| Multiple streams | Single stream |
| Index-aligned | Aggregates all |
| `zip(a, b)` → tuples | `reduce(stream)` → single value |
| Preserves cardinality | Collapses to one |

## Zip vs Builder

| Zip | Builder |
|-----|---------|
| Stream alignment | Part assembly |
| Index-by-index | All parts at once |
| `zip(commits, diffs)` | `build_request(method, url, headers)` |
| Time/position aligned | Not stream-based |

## Zip vs Splitter

| Zip | Splitter |
|-----|----------|
| Many → One | One → Many |
| Combines streams | Fans out stream |
| `zip(a, b)` → combined | `split(x, 2)` → a, b |
| Merger | Broadcaster |
