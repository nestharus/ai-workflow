# Sandbox Architecture

## Overview

The sandbox system provides isolated rebase/merge operations separate from the
user's main checkout. This architecture ensures that git operations don't
interfere with the user's working directory.

## Three-Checkout Model

The repository supports three distinct checkout types:

```text
ai-workflow/
├── .git/
│   └── sandbox/          # Sandbox checkout (rebase/merge)
├── .worktrees/           # AI worktrees (development)
│   └── <branch>/         # Individual worktrees
└── (main repo)           # Main checkout (user's working dir)
```

### 1. Main Checkout

* The user's primary working directory
* Located at the repository root
* Unaffected by rebase/merge operations
* User can safely stash, commit, switch branches

### 2. Sandbox Checkout

* Dedicated directory at `.git/sandbox/`
* Used exclusively for rebase/merge operations
* Persistent (not cleaned up between operations)
* Managed by the sandbox server

### 3. AI Worktrees

* Located at `.worktrees/<branch>/`
* Used for AI agent development work
* Created by `/execute-plan` and similar commands
* Separate from sandbox operations

## Components

### Socket Server (`scripts/servers/sandbox/server.py`)

The socket server manages all sandbox operations:

* Runs in Docker container
* Listens on Unix domain socket
* Processes operations sequentially (queue-based)
* Automatically creates sandbox on first use
* Handles conflicts by returning file list

**Start the server:**

The sandbox server starts automatically via `uv run dev.ensure-env` (triggered by
SessionStart hook). If not running, start manually:

```bash
docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d
```

### CLI Client (`scripts/servers/sandbox/client.py`)

The CLI provides commands for interacting with the server:

```bash
# Rebase a branch
uv run pr sandbox-rebase --branch feature-x --target main -v

# Merge main into a branch
uv run pr sandbox-merge --branch feature-x --target main -v

# Check operation status
uv run pr sandbox-status
```

### Protocol (`scripts/servers/sandbox/protocol.py`)

Request/response protocol using JSON over Unix socket:

**Requests:**

* `RebaseRequest`: Rebase branch onto target
* `MergeRequest`: Merge target into branch
* `StatusRequest`: Get operation status
* `CancelRequest`: Cancel queued operation

**Responses:**

* `SuccessResponse`: Operation completed successfully
* `ConflictResponse`: Conflicts need resolution
* `QueuedResponse`: Operation is queued
* `ProgressResponse`: Operation in progress
* `ErrorResponse`: Operation failed

### Operations (`scripts/servers/sandbox/operations.py`)

Git operations for the sandbox:

* `ensure_sandbox_exists()`: Create sandbox if needed
* `sync_sandbox_branch()`: Fetch and checkout branch
* `rebase_in_sandbox()`: Perform rebase
* `merge_in_sandbox()`: Perform merge
* `push_from_sandbox()`: Push changes to origin

## Claude Code Integration

The `/rebase` command uses the sandbox server:

1. Get PR information with `uv run pr get-pr`
2. Execute rebase via `uv run pr sandbox-rebase`
3. Handle conflicts with `conflict-resolver` agent
4. Sync source worktree after success

See `.claude/commands/rebase.md` for full workflow.

## VS Code Integration

VS Code agents use file-based locking:

1. Acquire `.git/sandbox/.sandbox.lock`
2. Execute operations manually in sandbox
3. Use `conflict-resolver` sub-agent for conflicts
4. Release lock on completion

See `.vscode/agents/rebase.md` and `.vscode/agents/merge.md`.

## Conflict Resolution

Both Claude Code and VS Code use the same conflict resolution approach:

1. Identify conflicted files via `git status`
2. For each file, invoke conflict-resolver agent
3. Agent analyzes both sides' intent
4. Agent stitches changes together
5. Stage resolved file with `git add`
6. Continue rebase/merge

The conflict-resolver is designed to NEVER just pick one side - it always
analyzes and merges changes from both sides.

## Server Protocol

Communication uses newline-delimited JSON over Unix socket:

```text
Client -> Server: {"command": "rebase", "branch": "feature-x", "target": "main"}\n
Server -> Client: {"status": "queued", "request_id": "...", "position": 1}\n
... (polling) ...
Server -> Client: {"status": "success", "request_id": "...", "result": {...}}\n
```

## Directory Structure

```text
scripts/servers/sandbox/
├── __init__.py        # Package exports
├── client.py          # CLI client
├── docker-compose.yml # Docker configuration
├── Dockerfile         # Server container
├── operations.py      # Git operations
├── protocol.py        # Request/response types
└── server.py          # Socket server
```

## Security Considerations

* Unix socket provides inherent network isolation
* Server intended for LOCAL DEVELOPMENT ONLY
* No authentication (relies on filesystem permissions)
* For production, implement proper authentication

## Remote Configuration Assumptions

The sandbox system assumes a simple remote configuration:

* **Single `origin` remote**: The sandbox only copies the `origin` remote URL from the
  main repository. Additional remotes (e.g., `upstream`, `fork`) are not automatically
  configured.
* **User configuration**: Only `user.name` and `user.email` are copied from the main repo
  to the sandbox.

If your workflow requires multiple remotes:

1. Manually add remotes to the sandbox after creation:

   ```bash
   cd .git/sandbox
   git remote add upstream https://github.com/upstream/repo.git
   ```

2. Or modify `ensure_sandbox_exists()` in `scripts/servers/sandbox/operations.py` to copy
   additional remotes as needed.

## Migration from Old System

The previous system used per-operation sandboxes at `.git/rebase-sandbox/<branch>`.
The new system uses a persistent sandbox at `.git/sandbox/`.

**Old workflow:**

1. `uv run pr promote-worktree` - Create sandbox
2. Rebase in sandbox
3. `uv run pr cleanup-sandbox` - Remove sandbox

**New workflow:**

1. `uv run pr sandbox-rebase` - Server handles everything
2. (No cleanup needed)

The old commands (`promote-worktree`, `cleanup-sandbox`) remain available for
backward compatibility but are deprecated.
