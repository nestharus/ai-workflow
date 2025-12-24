---
name: impl-setter
description: Implements Setter pattern - set a private field
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Setter Pattern Implementor

Implement the **Setter** pattern - a simple function that sets a private field.

## Pattern Definition

```python
def set_<field>(obj: T, value: V) -> None:
    """Set the <field> private field.

    Args:
        obj: Object containing the field
        value: Value to set
    """
    obj._field = value
```

## Key Insight

A setter is a **reserved** pattern specifically for private fields:
- Sets ONE private field
- No computation or transformation
- Direct field assignment
- Part of encapsulation pattern

For setting/mutating data in general, use **Mutator** instead.

## Implementation Rules

1. **Private field only**: Assigns to `_field` or `__field`
2. **Direct assignment**: No computation, just assign
3. **Single field**: Sets exactly ONE field
4. **Encapsulation**: Part of class/module encapsulation
5. **Clear naming**: `set_<field_name>`

## CREATE Example

```python
class User:
    def __init__(self, name: str, email: str):
        self._name = name
        self._email = email
        self._active = True

    def set_name(self, value: str) -> None:
        """Set the name private field."""
        self._name = value

    def set_email(self, value: str) -> None:
        """Set the email private field."""
        self._email = value

    def set_active(self, value: bool) -> None:
        """Set the active private field."""
        self._active = value


class Config:
    def __init__(self):
        self._settings: dict[str, Any] = {}
        self._loaded: bool = False

    def set_settings(self, value: dict[str, Any]) -> None:
        """Set the settings private field."""
        self._settings = value

    def set_loaded(self, value: bool) -> None:
        """Set the loaded private field."""
        self._loaded = value


class Connection:
    def __init__(self, host: str, port: int):
        self._host = host
        self._port = port
        self._timeout = 30

    def set_host(self, value: str) -> None:
        """Set the host private field."""
        self._host = value

    def set_port(self, value: int) -> None:
        """Set the port private field."""
        self._port = value

    def set_timeout(self, value: int) -> None:
        """Set the timeout private field."""
        self._timeout = value
```

## Setter vs Mutator

| Setter | Mutator |
|--------|---------|
| Private field only | Any data mutation |
| Direct assignment | May involve logic |
| `set_name(obj, v)` → `obj._name = v` | `mutate_config(cfg, k, v)` |
| Reserved pattern | General pattern |

## When to Use Mutator Instead

```python
# These are MUTATORS, not setters:
def mutate_config_value(config: dict, key: str, value: Any) -> None:  # Nested update
def mutate_file_content(path: Path, content: str) -> None:  # File write
def mutate_env_var(name: str, value: str) -> None:  # Environment

# These are SETTERS:
def set_name(self, value: str) -> None:  # self._name = value
def set_id(self, value: int) -> None:  # self._id = value
```

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
