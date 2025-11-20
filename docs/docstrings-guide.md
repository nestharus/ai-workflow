# Docstrings Guide

This project uses Google-style docstrings and enforces them through `ruff` (with
`pydocstyle`) and `pymarkdown`. Use these conventions for all public modules,
classes, functions, and methods.

## General Rules

* Use triple double quotes (`"""`) and keep the opening summary on one line.
* Write clear, sentence-case summaries ending with a period.
* Prefer type hints in code; avoid duplicating types in docstrings unless it aids clarity.
* Keep docstrings focused on behavior, side effects, and important constraints.
* Include argument, return, and raises sections only when they add information beyond type hints.

## Recommended Structure

1. Summary line.
2. Optional blank line when additional detail follows the summary.
3. Sections in the order: `Args`, `Returns`, `Yields`, `Raises`, `Examples`.

## Function Example

```python
def fetch_user(user_id: str, *, include_inactive: bool = False) -> User:
    """Retrieve a user record from storage.

    Args:
        user_id: Identifier of the user to fetch.
        include_inactive: When true, also allow inactive users to match.

    Returns:
        User: The matching user instance.

    Raises:
        UserNotFoundError: No user matched the provided id and filters.
    """
```

## Class Example

```python
class TaskQueue:
    """Queue wrapper that limits concurrent tasks."""

    def __init__(self, capacity: int) -> None:
        """Create a queue with a maximum in-flight capacity."""

    def acquire(self) -> None:
        """Block until a slot is available, then reserve it."""
```

## Additional Guidance

* Modules: Provide a brief description when the module exposes public APIs or
  significant setup logic.
* Properties: Document behavior in the getter; setters rarely need separate
  docstrings unless they perform non-trivial work.
* Async functions: Document awaited side effects and cancellation behavior if relevant.
* Examples: Use fenced code blocks with the language set (` ```python `) and keep
  them minimal and runnable when possible.

For more details on Google-style docstrings, see the
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
