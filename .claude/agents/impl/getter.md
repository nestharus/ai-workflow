---
name: impl-getter
description: Implements Getter pattern - return a private field
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Getter Pattern Implementor

Implement the **Getter** pattern - a simple function that returns a private field.

## Pattern Definition

```python
def get_<field>(obj: T) -> V:
    """Get the <field> private field.

    Args:
        obj: Object containing the field

    Returns:
        The private field value
    """
    return obj._field
```

## Executor Contract

**See `.claude/docs/impl-executor-contract.md` for invocation parameters, execution process, and output format.**


## Key Insight

A getter is a **reserved** pattern specifically for private fields:
- Returns ONE private field
- No computation or transformation
- Direct field access
- Part of encapsulation pattern

For getting data in general, use **Extractor** instead.

## Implementation Rules

1. **Private field only**: Accesses `_field` or `__field`
2. **Direct access**: No computation, just return
3. **Single field**: Returns exactly ONE field
4. **Encapsulation**: Part of class/module encapsulation
5. **Clear naming**: `get_<field_name>`

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
class User:
    def __init__(self, name: str, email: str):
        self._name = name
        self._email = email
        self._created_at = datetime.now()

    def get_name(self) -> str:
        """Get the name private field."""
        return self._name

    def get_email(self) -> str:
        """Get the email private field."""
        return self._email

    def get_created_at(self) -> datetime:
        """Get the created_at private field."""
        return self._created_at


class Config:
    def __init__(self):
        self._settings: dict[str, Any] = {}
        self._loaded: bool = False

    def get_settings(self) -> dict[str, Any]:
        """Get the settings private field."""
        return self._settings

    def get_loaded(self) -> bool:
        """Get the loaded private field."""
        return self._loaded


class Connection:
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._socket: socket | None = None

    def get_host(self) -> str:
        """Get the host private field."""
        return self._host

    def get_port(self) -> int:
        """Get the port private field."""
        return self._port

    def get_socket(self) -> socket | None:
        """Get the socket private field."""
        return self._socket
```

## Getter vs Extractor

| Getter | Extractor |
|--------|-----------|
| Private field only | Any data from any source |
| Direct return | May involve parsing/logic |
| `get_name(obj)` → `obj._name` | `extract_name(html)` → parsed |
| Reserved pattern | General pattern |

## When to Use Extractor Instead

```python
# These are EXTRACTORS, not getters:
def extract_branch_name(repo_path: Path) -> str:  # Parses file
def extract_config_value(config: dict, key: str) -> Any:  # Traverses dict
def extract_user_id(token: str) -> int:  # Decodes token

# These are GETTERS:
def get_name(self) -> str:  # Returns self._name
def get_id(self) -> int:  # Returns self._id
```
