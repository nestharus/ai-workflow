---
name: impl-mapper
description: Implements Mapper pattern - map data between formats
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Mapper Pattern Implementor

Implement the **Mapper** pattern - a function that maps data from one format to another.

## Pattern Definition

```python
def map_<what>(input_data: T) -> R:
    """Map <input> to <output> format.

    Args:
        input_data: The data to map

    Returns:
        The mapped data

    Raises:
        MappingError: If mapping fails
    """
```

## Key Insight

A mapper is a pure transformation:
- ONE input → ONE output
- No side effects
- Deterministic (same input → same output)
- Converts between formats/representations

## Implementation Rules

1. **Pure function**: Input → Output, no side effects
2. **Deterministic**: Same input always produces same output
3. **Preserve information**: Don't lose data unless specified
4. **Type-safe**: Full typing with covariance where appropriate
5. **Clear naming**: `map_<from>_to_<to>` or `map_<what>`

## CREATE Example

```python
def map_snake_to_camel(text: str) -> str:
    """Map snake_case string to camelCase.

    Args:
        text: The snake_case string to map

    Returns:
        The camelCase equivalent
    """
    if not text:
        return text
    parts = text.split("_")
    return parts[0] + "".join(word.capitalize() for word in parts[1:])


def map_dict_to_model(data: dict[str, Any], model_cls: type[T]) -> T:
    """Map dictionary to model instance.

    Args:
        data: Dictionary data
        model_cls: Target model class

    Returns:
        Model instance
    """
    return model_cls(**data)


def map_commit_to_summary(commit: GitCommit) -> CommitSummary:
    """Map full commit to summary format.

    Args:
        commit: Full git commit object

    Returns:
        Condensed commit summary
    """
    return CommitSummary(
        sha=commit.sha[:7],
        message=commit.message.split("\n")[0],
        author=commit.author.name,
        date=commit.committed_date,
    )
```

## Mapper vs Projector

| Mapper | Projector |
|--------|-----------|
| Converts format | Extracts subset |
| Full transformation | Field selection |
| `map_user_to_dto(user)` | `project_user_name(user)` |

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
