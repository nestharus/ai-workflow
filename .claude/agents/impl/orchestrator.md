---
name: impl-orchestrator
description: Implements Orchestrator pattern - sequential integration with no logic
model: haiku
tools: Read, Edit, Write, Grep, Glob
---

# Orchestrator Pattern Implementor

Implement the **Orchestrator** pattern - a function that runs a series of calls sequentially with no business logic.

## Pattern Definition

```python
def orchestrate_<what>(*args, **kwargs) -> R:
    """Orchestrate <what> by running steps sequentially.

    Args:
        *args: Input arguments passed to first step
        **kwargs: Configuration options

    Returns:
        Result from final step
    """
```

## Key Insight

An orchestrator is pure integration:
- Sequential function calls
- NO conditionals (no if/else)
- NO loops (no for/while)
- NO business logic
- Just wires outputs → inputs between steps
- May return final result

## Implementation Rules

1. **Sequential only**: Steps run one after another
2. **No conditionals**: No if/else statements
3. **No loops**: No for/while statements
4. **No business logic**: Just call functions and pass data
5. **Wire states**: Output of step N → input of step N+1
6. **Clear naming**: `orchestrate_<workflow>`

## CREATE Example

```python
def orchestrate_commit_flow(
    repo_path: Path,
    message: str,
) -> CommitResult:
    """Orchestrate the commit flow.

    Args:
        repo_path: Repository path
        message: Commit message

    Returns:
        Commit result with SHA
    """
    # Step 1: Get staged files
    staged = get_staged_files(repo_path)

    # Step 2: Validate commit
    validate_commit_ready(repo_path, staged)

    # Step 3: Create commit
    sha = create_commit(repo_path, message)

    # Step 4: Build result
    result = map_to_commit_result(sha, staged, message)

    return result


def orchestrate_pr_creation(
    repo_path: Path,
    title: str,
    body: str,
    base: str,
) -> PullRequest:
    """Orchestrate PR creation flow.

    Args:
        repo_path: Repository path
        title: PR title
        body: PR body
        base: Base branch

    Returns:
        Created pull request
    """
    # Step 1: Get current branch
    branch = get_current_branch(repo_path)

    # Step 2: Push branch
    push_branch(repo_path, branch)

    # Step 3: Create PR
    pr = create_pull_request(repo_path, title, body, branch, base)

    # Step 4: Add labels
    add_default_labels(pr)

    return pr


def orchestrate_rebase(
    repo_path: Path,
    target_branch: str,
) -> RebaseResult:
    """Orchestrate rebase flow.

    Args:
        repo_path: Repository path
        target_branch: Branch to rebase onto

    Returns:
        Rebase result
    """
    # Step 1: Fetch latest
    fetch_remote(repo_path)

    # Step 2: Get current branch
    current = get_current_branch(repo_path)

    # Step 3: Stash changes
    stash_id = stash_changes(repo_path)

    # Step 4: Rebase
    result = rebase_onto(repo_path, target_branch)

    # Step 5: Pop stash
    pop_stash(repo_path, stash_id)

    # Step 6: Build result
    return map_to_rebase_result(current, target_branch, result)
```

## Orchestrator vs Router

| Orchestrator | Router |
|--------------|--------|
| Sequential steps | Conditional dispatch |
| No branching | If-else chains |
| All steps run | One branch runs |
| `orchestrate_flow()` | `route_command()` |

## Output Contract

```yaml
status: <success|failure>
file_path: <path to created/modified file>
exports: [<function names exported>]
error: <error message if failure>
```
