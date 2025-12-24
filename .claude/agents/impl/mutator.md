---
name: impl-mutator
description: Implements Mutator pattern - set/modify one piece of data
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Mutator Pattern Implementor

Implement the **Mutator** pattern - a function that sets or modifies one specific piece of data.

## Pattern Definition

```python
def mutate_<what>(target: T, value: V) -> None:
    """Mutate <what> on target.

    Args:
        target: Target to modify
        value: Value to set
    """
```

## Key Insight

A mutator sets ONE specific piece of data:
- Applies to ANY data (not just private fields)
- Sets exactly ONE thing
- Has side effects (mutation)
- General pattern for data modification

For private fields specifically, use **Setter** instead.

## Implementation Rules

1. **One thing**: Modifies exactly ONE piece of data
2. **Any target**: Can mutate dicts, files, env vars, etc.
3. **Side effect**: Has mutation side effect
4. **Clear naming**: `mutate_<what_is_being_mutated>`
5. **Idempotent**: Same call twice has same effect

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def mutate_config_value(config: dict, key: str, value: Any) -> None:
    """Mutate config value at key.

    Args:
        config: Config dictionary (mutated)
        key: Key path (supports dot notation)
        value: Value to set
    """
    parts = key.split(".")
    current = config
    for part in parts[:-1]:
        if part not in current:
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def mutate_file_content(path: Path, content: str) -> None:
    """Mutate file content.

    Args:
        path: File path
        content: New content
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def mutate_env_var(name: str, value: str) -> None:
    """Mutate environment variable.

    Args:
        name: Variable name
        value: New value
    """
    os.environ[name] = value


def mutate_json_field(path: Path, field: str, value: Any) -> None:
    """Mutate field in JSON file.

    Args:
        path: JSON file path
        field: Field path (dot notation)
        value: New value
    """
    data = json.loads(path.read_text()) if path.exists() else {}
    mutate_config_value(data, field, value)
    path.write_text(json.dumps(data, indent=2))


def mutate_git_config(repo_path: Path, key: str, value: str) -> None:
    """Mutate git config value.

    Args:
        repo_path: Repository path
        key: Config key (e.g., "user.name")
        value: Config value
    """
    subprocess.run(
        ["git", "config", key, value],
        cwd=repo_path,
        check=True,
    )


def mutate_list_item(items: list, index: int, value: Any) -> None:
    """Mutate list item at index.

    Args:
        items: List to mutate
        index: Index to modify
        value: New value
    """
    items[index] = value
```

## Mutator vs Setter

| Mutator | Setter |
|---------|--------|
| Any data | Private field only |
| `mutate_config(cfg, k, v)` | `set_name(obj, v)` → `obj._name = v` |
| General pattern | Reserved pattern |
| External data | Internal state |

## Mutator vs Visitor

| Mutator | Visitor |
|---------|---------|
| One piece of data | Each element in iterable |
| Direct mutation | Callback-based |
| `mutate_field(obj, v)` | `visit_items(list, fn)` |

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
