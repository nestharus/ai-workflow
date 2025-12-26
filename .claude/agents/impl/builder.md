---
name: impl-builder
description: Implements Builder pattern - construct data from parts
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Builder Pattern Implementor

Implement the **Builder** pattern - a function that constructs data from parts.

## Pattern Definition

```python
def build_<what>(*parts, **options) -> T:
    """Build <what> from parts.

    Args:
        *parts: Components to build from
        **options: Build options

    Returns:
        Constructed result
    """
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

A builder constructs data from parts:
- Takes components/parts as input
- Assembles them into a result
- General data construction
- Not specific to iterables

For building from iterables specifically, use **Collector** instead.

## Implementation Rules

1. **Construct from parts**: Takes components, returns assembled result
2. **Pure function**: Typically no side effects
3. **Any data type**: Can build objects, strings, dicts, etc.
4. **Clear naming**: `build_<what_is_being_built>`
5. **Flexible input**: May take variable args or options

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def build_url(base: str, path: str, params: dict[str, str] | None = None) -> str:
    """Build URL from parts.

    Args:
        base: Base URL
        path: URL path
        params: Optional query parameters

    Returns:
        Complete URL
    """
    url = f"{base.rstrip('/')}/{path.lstrip('/')}"
    if params:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{query}"
    return url


def build_commit_message(
    title: str,
    body: str | None = None,
    ticket_id: str | None = None,
) -> str:
    """Build commit message from parts.

    Args:
        title: Commit title
        body: Optional body
        ticket_id: Optional ticket reference

    Returns:
        Formatted commit message
    """
    parts = [title]
    if body:
        parts.append("")
        parts.append(body)
    if ticket_id:
        parts.append("")
        parts.append(f"Refs: {ticket_id}")
    return "\n".join(parts)


def build_config(
    defaults: dict[str, Any],
    overrides: dict[str, Any] | None = None,
    env_prefix: str | None = None,
) -> dict[str, Any]:
    """Build config from defaults, overrides, and environment.

    Args:
        defaults: Default values
        overrides: Optional overrides
        env_prefix: Optional env var prefix to read

    Returns:
        Merged configuration
    """
    config = dict(defaults)
    if overrides:
        config.update(overrides)
    if env_prefix:
        for key in defaults:
            env_key = f"{env_prefix}_{key.upper()}"
            if env_key in os.environ:
                config[key] = os.environ[env_key]
    return config


def build_error_response(
    code: int,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build error response object.

    Args:
        code: Error code
        message: Error message
        details: Optional additional details

    Returns:
        Error response dict
    """
    response = {
        "error": {
            "code": code,
            "message": message,
        }
    }
    if details:
        response["error"]["details"] = details
    return response


def build_sql_query(
    table: str,
    columns: list[str],
    where: dict[str, Any] | None = None,
    order_by: str | None = None,
) -> str:
    """Build SQL SELECT query.

    Args:
        table: Table name
        columns: Columns to select
        where: Optional WHERE conditions
        order_by: Optional ORDER BY column

    Returns:
        SQL query string
    """
    cols = ", ".join(columns)
    query = f"SELECT {cols} FROM {table}"
    if where:
        conditions = " AND ".join(f"{k} = ?" for k in where)
        query = f"{query} WHERE {conditions}"
    if order_by:
        query = f"{query} ORDER BY {order_by}"
    return query
```

## Builder vs Collector

| Builder | Collector |
|---------|-----------|
| Any data from parts | From iterable specifically |
| `build_url(base, path)` | `collect_into_list(walker)` |
| General construction | Iterable aggregation |

## Builder vs Mapper

| Builder | Mapper |
|---------|--------|
| Multiple parts → result | Single input → output |
| Construction | Transformation |
| `build_config(a, b, c)` | `map_to_json(obj)` |
