---
name: impl-classifier
description: Implements Classifier pattern - boolean predicate for condition checking
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Classifier Pattern Implementor

Implement the **Classifier** pattern - a boolean predicate function that checks a named condition.

## Pattern Definition

```python
def is_<condition>(data: T) -> bool:
    """Check if data satisfies <condition>.

    Args:
        data: Data to check

    Returns:
        True if condition is met, False otherwise
    """
```

## Key Insight

A classifier is a named boolean expression:
- Returns True or False
- Named for the condition it checks
- Used by routers for dispatch decisions
- Pure function, no side effects

## Implementation Rules

1. **Boolean return**: Always returns True/False
2. **Named condition**: Function name describes what it checks
3. **Pure function**: No side effects
4. **No exceptions**: Returns False instead of throwing
5. **Used by routers**: Classifiers drive routing decisions
6. **Single condition focus**: Keep the classification condition clear and visible

## Flexibility Rules

**Read `.claude/docs/impl-flexibility-rules.md` for universal flexibility rules.**

Keep the classification condition clear and visible. Delegate complex logic to helper functions.

## CREATE Example

```python
def is_valid_email(text: str) -> bool:
    """Check if text is a valid email address.

    Args:
        text: Text to check

    Returns:
        True if valid email format
    """
    return "@" in text and "." in text.split("@")[-1]


def is_detached_head(repo_path: Path) -> bool:
    """Check if repository is in detached HEAD state.

    Args:
        repo_path: Repository path

    Returns:
        True if HEAD is detached
    """
    head_file = repo_path / ".git" / "HEAD"
    if not head_file.exists():
        return False
    content = head_file.read_text().strip()
    return not content.startswith("ref:")


def is_merge_commit(commit: GitCommit) -> bool:
    """Check if commit is a merge commit.

    Args:
        commit: Commit to check

    Returns:
        True if commit has multiple parents
    """
    return len(commit.parents) > 1


def is_feature_branch(branch_name: str) -> bool:
    """Check if branch is a feature branch.

    Args:
        branch_name: Branch name

    Returns:
        True if follows feature branch naming
    """
    return branch_name.startswith(("feature/", "feat/"))


def is_release_ready(pr: PullRequest) -> bool:
    """Check if PR is ready for release.

    Args:
        pr: Pull request

    Returns:
        True if all checks pass and approved
    """
    return (
        pr.mergeable
        and pr.approved
        and all(check.status == "success" for check in pr.checks)
    )


def is_stale_branch(branch: Branch, days: int = 30) -> bool:
    """Check if branch is stale (no recent commits).

    Args:
        branch: Branch to check
        days: Days threshold for staleness

    Returns:
        True if no commits within threshold
    """
    cutoff = datetime.now() - timedelta(days=days)
    return branch.last_commit_date < cutoff
```

## Classifier vs Validator

| Classifier | Validator |
|------------|-----------|
| Returns bool | Throws on failure |
| `is_valid_email(e)` → bool | `validate_email(e)` raises |
| Used in conditionals | Used for assertions |

## Usage with Routers

```python
# Router uses classifiers for dispatch
def route_branch_action(branch: str) -> Action:
    if is_feature_branch(branch):
        return handle_feature(branch)
    elif is_release_branch(branch):
        return handle_release(branch)
    else:
        return handle_default(branch)
```

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
