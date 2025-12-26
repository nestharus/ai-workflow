---
name: impl-extractor
description: Implements Extractor pattern - get one specific piece of data from any source
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Extractor Pattern Implementor

Implement the **Extractor** pattern - a function that gets one specific piece of data from any source.

## Pattern Definition

```python
def extract_<what>(source: S) -> T:
    """Extract <what> from source.

    Args:
        source: Any data source

    Returns:
        The extracted data (single value or collection)

    Raises:
        ExtractionError: If extraction fails
    """
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

An extractor gets ONE specific thing from any source:
- Applies to ANY data (objects, files, strings, APIs, etc.)
- Gets exactly ONE piece of data (could be a collection itself)
- May involve parsing, traversing, or computation
- General pattern for data access

For private fields specifically, use **Getter** instead.
For iterating through elements, use **Walker** instead.

## Implementation Rules

1. **One thing**: Extracts exactly ONE piece of data
2. **Any source**: Can extract from any type of source
3. **May compute**: Can involve parsing, decoding, traversing
4. **Clear naming**: `extract_<what_is_being_extracted>`
5. **Pure function**: Typically no side effects

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def extract_branch_name(repo_path: Path) -> str:
    """Extract current branch name from git repository.

    Args:
        repo_path: Path to repository

    Returns:
        Branch name

    Raises:
        ExtractionError: If not a git repo or detached HEAD
    """
    git_head = repo_path / ".git" / "HEAD"
    if not git_head.exists():
        raise ExtractionError(f"Not a git repository: {repo_path}")

    content = git_head.read_text().strip()
    if content.startswith("ref: refs/heads/"):
        return content[16:]
    raise ExtractionError("Detached HEAD state")


def extract_config_value(config: dict, key: str) -> Any:
    """Extract value from config by key path.

    Args:
        config: Configuration dict
        key: Key path (dot notation)

    Returns:
        Value at key path

    Raises:
        ExtractionError: If key not found
    """
    parts = key.split(".")
    current = config
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            raise ExtractionError(f"Key not found: {key}")
        current = current[part]
    return current


def extract_user_id(token: str) -> int:
    """Extract user ID from JWT token.

    Args:
        token: JWT token string

    Returns:
        User ID from token payload
    """
    payload = jwt.decode(token, verify=False)
    return payload["user_id"]


def extract_imports(source_code: str) -> list[str]:
    """Extract import statements from Python source.

    Args:
        source_code: Python source code

    Returns:
        List of imported module names
    """
    imports = []
    for line in source_code.split("\n"):
        line = line.strip()
        if line.startswith("import "):
            imports.append(line[7:].split()[0])
        elif line.startswith("from "):
            imports.append(line[5:].split()[0])
    return imports


def extract_error_message(exception: Exception) -> str:
    """Extract error message from exception.

    Args:
        exception: Exception object

    Returns:
        Error message string
    """
    return str(exception)


def extract_file_extension(path: Path) -> str:
    """Extract file extension.

    Args:
        path: File path

    Returns:
        Extension without dot (or empty string)
    """
    return path.suffix.lstrip(".")
```

## Extractor vs Getter

| Extractor | Getter |
|-----------|--------|
| Any source | Private field only |
| May compute | Direct access |
| `extract_branch(repo)` | `get_name(obj)` → `obj._name` |
| General pattern | Reserved pattern |

## Extractor vs Walker

| Extractor | Walker |
|-----------|--------|
| Gets one thing | Yields many elements |
| Returns result | Returns Iterator |
| `extract_config(file)` | `walk_lines(file)` |
| Any source | Iterables only |

## Extractor vs Collector

| Extractor | Collector |
|-----------|-----------|
| From any source | From iterable/stream |
| Direct extraction | Aggregates stream |
| `extract_imports(code)` | `collect_into_list(walker)` |
