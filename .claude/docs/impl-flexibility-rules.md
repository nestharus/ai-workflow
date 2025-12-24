# Universal Flexibility Rules for Atomic Components

These rules apply to most atomic component patterns (excludes: guard, entity, projection).

## Core Principle

Atomic components have limited flexibility for accomplishing their purpose without creating tiny control flow functions that provide no value. However, complexity must not obscure the component's primary purpose. When logic becomes complex, delegate to dedicated functions.

## Allowed

### Simple 1-Dimensional Loops
```python
for item in items:
    result = process(item)
    results.append(result)
```

### List Comprehensions / Streams
Preferred over traditional loops. Enables 2D iteration through flattening:
```python
# OK: flattened 2D iteration
all_items = [item for group in groups for item in group.items]

# OK: multi-step where each step does ONE thing
valid = [normalize(x) for x in items if is_active(x)]
#       ^one thing^                  ^one thing^
```

### Inline Simple Operations
```python
result = transform(get_data(source))
items = [item.name for item in collection]
```

### Short Single-Dimension Nesting (≤6 lines)
```python
for item in items:
    result = process(item)
    if result.valid:
        results.append(result)
```

## Prohibited

### Nested Loops
```python
# NOT OK
for outer in outers:
    for inner in outer.inners:  # Use list comprehension instead
        handle(inner)
```

### Nested If-Statements
```python
# NOT OK
if condition_a:
    if condition_b:
        do_thing()
```

### Complex Boolean Expressions
```python
# NOT OK: concatenated boolean in single statement
if item.active and item.score > threshold and item.type in allowed_types:
    process(item)

# NOT OK: complex boolean packed in comprehension
bad = [x for x in items if x.active and x.score > 5 and x.type == "A"]
```

## Delegate Complexity

When logic becomes complex, extract to helper functions to keep the component's purpose clear:
```python
# OK: complex logic delegated
def is_deployable(release: Release) -> bool:
    return (
        passes_safety_checks(release)
        and has_required_approvals(release)
        and is_within_deployment_window()
    )
```

## Summary

| Allowed | Prohibited |
|---------|------------|
| Simple 1D loops | Nested loops |
| List comprehensions | Nested if-statements |
| Inline simple operations | Complex boolean expressions |
| Short nesting (≤6 lines) | Logic that obscures purpose |
