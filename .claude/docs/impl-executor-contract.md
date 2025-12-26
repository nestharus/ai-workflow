# Impl-Executor Contract

This document defines the standard invocation parameters, execution process, and output contract shared by all implementation pattern agents.

## Invocation Parameters

When invoked by impl-executor, you receive:
```yaml
workspace: <path>        # Design workspace (e.g., .tmp/design/NES-123)
unit_id: <id>           # Unit identifier
worktree_path: <path>   # Git worktree where changes should be made
```

## Execution Process

1. Read `{workspace}/agent_input.yaml` to get full unit specification:
   - `units[unit_id].plan` contains the implementation plan
   - `units[unit_id].pattern` is your pattern type
   - `units[unit_id].children` lists child unit IDs (if composition needed)

2. Perform implementation in the worktree (NOT main repo):
   - All file operations must target `{worktree_path}/`
   - Read existing code from worktree
   - Write/edit files in worktree

3. Return result to stdout or write to workspace as needed by impl-executor

## Output Contract

Return YAML to stdout:
```yaml
status: success|failure
file_path: <path relative to worktree_path, or array of relative paths if multiple files produced>
exports: [<array of exported symbol names (function/class names as strings)>]
error: <error message if failure>
```

### Examples

**Single file (success):**
```yaml
status: success
file_path: "app/services/user_service.py"
exports: ["UserService", "create_user", "get_user_by_id"]
```

**Multiple files (success):**
```yaml
status: success
file_path: ["app/models/user.py", "app/services/user_service.py"]
exports: ["User", "UserService", "create_user"]
```

**Failure case:**
```yaml
status: failure
file_path: null
exports: []
error: "Failed to parse unit specification: missing required field 'plan'"
```

Note: `file_path` values are relative to `worktree_path` (the directory where code changes are made), not relative to the design workspace or repository root.
