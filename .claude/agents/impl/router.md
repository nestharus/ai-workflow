---
name: impl-router
description: Implements Router pattern - route to one of N functions via labeled conditions
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Router Pattern Implementor

Implement the **Router** pattern - a function that routes to one of N functions using labeled conditions.

## Pattern Definition

```python
def route_<what>(input: T) -> R:
    """Route input to appropriate handler.

    Args:
        input: Input to route

    Returns:
        Result from selected handler
    """
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

A router routes to one of N functions using labeled conditions:
- **If-else chains**: Conditions labeled with classifier functions
- **Switch/match statements**: Conditions labeled via case values
- ONE branch executes per call
- Replaces embedded routing logic with named function

## Implementation Rules

1. **Labeled conditions**: Use classifiers or match values
2. **Direct dispatch**: Call handler functions directly
3. **Always default**: Include else/default clause for fallback
4. **Clear naming**: `route_<what_is_being_routed>`
5. **No business logic**: Just routing, logic lives in handlers

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## If-Else Style (Classifier Labels)

```python
def route_git_command(command: str, args: list[str]) -> int:
    """Route git command to handler.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        Exit code
    """
    if is_rebase_command(command):
        return handle_rebase(args)
    elif is_merge_command(command):
        return handle_merge(args)
    elif is_commit_command(command):
        return handle_commit(args)
    else:
        return handle_unknown(command, args)
```

## Switch/Match Style (Value Labels)

```python
def route_operation(op_type: OperationType, data: Any) -> Result:
    """Route operation by type.

    Args:
        op_type: Operation type enum
        data: Operation data

    Returns:
        Operation result
    """
    match op_type:
        case OperationType.CREATE:
            return handle_create(data)
        case OperationType.UPDATE:
            return handle_update(data)
        case OperationType.DELETE:
            return handle_delete(data)
        case _:
            return handle_unknown(op_type, data)


def route_message(message: dict) -> None:
    """Route message by type field.

    Args:
        message: Message with 'type' field
    """
    match message.get("type"):
        case "error":
            process_error(message)
        case "warning":
            process_warning(message)
        case "info":
            process_info(message)
        case _:
            process_default(message)


def route_http_method(method: str, request: Request) -> Response:
    """Route HTTP request by method.

    Args:
        method: HTTP method
        request: Request object

    Returns:
        Response
    """
    match method.upper():
        case "GET":
            return handle_get(request)
        case "POST":
            return handle_post(request)
        case "PUT":
            return handle_put(request)
        case "DELETE":
            return handle_delete(request)
        case _:
            return handle_method_not_allowed(method)
```

## Router vs Orchestrator

| Router | Orchestrator |
|--------|--------------|
| Conditional dispatch | Sequential steps |
| One branch runs | All steps run |
| If-else or switch | No conditionals |
| `route_command()` | `orchestrate_flow()` |

