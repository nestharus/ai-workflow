# Merge PR Command

---

description: Merge a PR via GitHub and perform cleanup (worktree removal, branch sync, ticket completion)
allowed-tools: Task, Read, Glob, Bash

---

Merge PR: $ARGUMENTS

## Arguments

* Empty: Use current branch (must be on PR branch)
* PR ID (`17` or `#17`): Get branch from GitHub PR
* Ticket ID (`NES-87`): Look up branch from Linear
* Branch name: Use directly

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

Returns JSON with:
- `branch_name`: Git branch (may contain slashes, e.g., `mrasolomon/nes-87-...`)
- `worktree_path`: Path to worktree, or `null` if on branch directly
- `working_directory`: Where to run commands - `.` or worktree path
- `is_worktree`: Boolean - `true` if using worktree
- `pr_number`, `pr_url`: PR identifiers
- `base_branch`: Target branch (e.g., `main`, `develop`) - NOT hardcoded to `main`

### 2. Extract Ticket ID and Get Repo Root

```bash
uv run pr extract-ticket-id {{branch_name}}
git rev-parse --show-toplevel
```

Set variables:
- `ticket_id`: From output (may be `null`)
- `repo_root`: From git command
- `working_dir`: `{{repo_root}}/{{working_directory}}` (absolute path)

### 3. Merge and Cleanup

```bash
uv run pr merge --pr {{pr_number}} --working-dir {{working_dir}} --branch {{branch_name}} --base-branch {{base_branch}} {{#if ticket_id}}--ticket {{ticket_id}}{{/if}} {{#if is_worktree}}--is-worktree{{/if}}
```

## Sandbox Merge (merge main INTO feature branch)

Merges target INTO your feature branch (not PR into main). Runs in `.git/sandbox/` checkout, leaves main checkout untouched.

**Prerequisites**: Sandbox server starts via `uv run dev.ensure-env`. Manual start:
```bash
docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d
```

**Execute**:
```bash
uv run pr sandbox-merge --branch {{branch_name}} --target main -v
```

**Exit codes**: `0` success, `2` conflicts (resolve in `.git/sandbox/`, push manually), `1` error.

**Socket**: Default `/tmp/sandbox-sockets/sandbox.sock`. Override with `--socket <path>`.

See `docs/development/sandbox-architecture.md` for details.

## Rules

* **Refs must match before merge** - Step 3 verifies this; block if mismatch
* Remote branch auto-deletes after merge - do NOT delete manually
* Does NOT checkout target branch - do that manually if needed
* Sandbox merge is separate from GitHub PR merge - use the right one for your use case
