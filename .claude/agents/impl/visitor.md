---
name: impl-visitor
description: Implements Visitor pattern - accept callback for each element (typically mutations)
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Visitor Pattern Implementor

Implement the **Visitor** pattern - a function that accepts a callback and calls it for each element.

## Pattern Definition

```python
def visit_<what>(source: S, fn: Callable[[T], None]) -> None:
    """Visit each element in source, calling fn for each.

    Args:
        source: Source to traverse
        fn: Callback function to call for each element
    """
```

## Key Insight

A visitor accepts a callback and applies it to each element:
- Visitor controls the iteration (not the caller)
- Typically used for mutations/side effects
- Callback decides what to do with each element
- Follows the visitor design pattern

## Implementation Rules

1. **Accept callback**: Takes a function as parameter
2. **Call for each**: Invokes callback on every element
3. **Visitor controls traversal**: Not the caller
4. **Clear naming**: `visit_<what_is_being_visited>`
5. **Typically mutations**: Callbacks often modify state

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

## CREATE Example

```python
def visit_files(directory: Path, fn: Callable[[Path], None]) -> None:
    """Visit each file in directory.

    Args:
        directory: Root directory
        fn: Callback for each file
    """
    for path in directory.rglob("*"):
        if path.is_file():
            fn(path)


def visit_tree_nodes(root: TreeNode, fn: Callable[[TreeNode], None]) -> None:
    """Visit each node in tree depth-first.

    Args:
        root: Root node
        fn: Callback for each node
    """
    fn(root)
    for child in root.children:
        visit_tree_nodes(child, fn)


def visit_json_keys(
    data: dict,
    key: str,
    fn: Callable[[dict, str], None],
) -> None:
    """Visit each occurrence of key in nested dict.

    Args:
        data: Nested dictionary
        key: Key to find
        fn: Callback receiving (parent_dict, key)
    """
    if isinstance(data, dict):
        if key in data:
            fn(data, key)
        for value in data.values():
            visit_json_keys(value, key, fn)
    elif isinstance(data, list):
        for item in data:
            visit_json_keys(item, key, fn)


def visit_lines(file_path: Path, fn: Callable[[int, str], None]) -> None:
    """Visit each line in file with line number.

    Args:
        file_path: File to read
        fn: Callback receiving (line_number, line_content)
    """
    with file_path.open() as f:
        for i, line in enumerate(f, 1):
            fn(i, line.rstrip())


def visit_commits(
    repo_path: Path,
    fn: Callable[[GitCommit], None],
    since: str | None = None,
) -> None:
    """Visit each commit in repository history.

    Args:
        repo_path: Repository path
        fn: Callback for each commit
        since: Optional date filter
    """
    cmd = ["git", "log", "--format=%H"]
    if since:
        cmd.extend(["--since", since])

    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    for sha in result.stdout.strip().split("\n"):
        if sha:
            commit = get_commit(repo_path, sha)
            fn(commit)
```

## Mutation Example

```python
# Visitor pattern for mutations
def update_all_versions(directory: Path, new_version: str) -> None:
    """Update version in all package.json files."""

    def update_version(path: Path) -> None:
        if path.name == "package.json":
            data = json.loads(path.read_text())
            data["version"] = new_version
            path.write_text(json.dumps(data, indent=2))

    visit_files(directory, update_version)


# Visitor for collecting (though walker is preferred for this)
def collect_errors(log_path: Path) -> list[str]:
    """Collect all error lines from log."""
    errors = []

    def collect_if_error(line_num: int, line: str) -> None:
        if "ERROR" in line:
            errors.append(f"{line_num}: {line}")

    visit_lines(log_path, collect_if_error)
    return errors
```

## Visitor vs Walker

| Visitor | Walker |
|---------|--------|
| Accepts callback | Yields elements |
| Visitor controls iteration | Caller controls iteration |
| `visit_*(src, fn)` | `for x in walk_*(src)` |
| Typically for mutations | Typically read-only |

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
