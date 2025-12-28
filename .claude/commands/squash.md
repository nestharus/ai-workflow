# Squash Commits

---

description: Squash commits in a worktree and force push
argument-hint: "`ticket-id` (e.g., `NES-124`)"
allowed-tools: Bash

---

Squash commits for: $ARGUMENTS

This command squashes all commits in a worktree into one and force pushes.

## Prerequisites

- **git** (2.43.7+ or latest stable): Required for worktree and force-push operations. Install via package manager (`apt install git`, `brew install git`) or from [git-scm.com](https://git-scm.com/downloads). **Note:** Older unpatched Git releases have known security vulnerabilities (CVE-2025-48384, CVE-2025-48385, CVE-2025-48386). Patched releases include 2.43.7, 2.44.4, 2.45.4, 2.46.4, 2.47.3, 2.48.2, 2.49.1, and 2.50.1+.
- **uv** (0.9+): Python package manager and task runner. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or see [docs.astral.sh/uv](https://docs.astral.sh/uv/)
- **pr CLI plugin**: The `uv run pr` commands require the pr module in this repository. Ensure you have run `uv sync` in the repo root
- **Bash**: Commands are executed in a Bash shell
- **GitHub authentication**: Required for push operations. Verify with `gh auth status`

### Verify Prerequisites

Run the following commands to confirm your environment is correctly configured:

```bash
git --version      # Expected: git version 2.43.7 or higher
uv --version       # Expected: uv 0.9.0 or higher
gh auth status     # Expected: Logged in to github.com
uv run pr --help   # Expected: Shows pr CLI usage; fails if plugin missing
```

If any version is below the minimum, authentication fails, or the pr CLI plugin is not available, update the tool, re-authenticate, or run `uv sync` in the repo root before proceeding.

## Steps

### 1. Get PR Info

```bash
uv run pr get-pr $ARGUMENTS
```

Parse the JSON output to extract:
- `working_directory`: Directory used for running git commands
- `worktree_path`: Path to the worktree (for display/context only, does not override working_directory)
- `base_branch`: PR's target branch
- `branch_name`: Current branch name

#### Working Directory Resolution

The `uv run pr get-pr` command determines the effective working directory using this precedence: (1) if CWD is inside a worktree, use the nearest worktree root; (2) otherwise, use the `working_directory` from get-pr output; (3) fallback to repo root. The `worktree_path` field is display-only and does not override git operations.

**Important:** The `uv run pr get-pr` command returns a `working_directory` value even when run from outside a worktree. All subsequent git commands in Steps 2-5 must be executed from this returned `working_directory` to ensure consistent behavior.

**Example: Inside a worktree** — CWD `/home/user/project/.worktrees/NES-124` results in git commands running in `/home/user/project/.worktrees/NES-124`.

**Example: From repo root** — CWD `/home/user/project` uses `working_directory` from get-pr output (e.g., `/home/user/project/.worktrees/NES-124`).

> **Caution:** Do not run Steps 2-5 from a different worktree or a subdirectory of another worktree. Always `cd` into the `working_directory` returned by `uv run pr get-pr` (or the repo root fallback) before executing git commands. Running from an unexpected location can cause git to operate on the wrong repository or branch, leading to inconsistent or destructive behavior.

If no PR exists, report error and exit.

### 2. Preflight Checks

Before squashing, perform these safety checks:

#### 2.1 Fetch Remote Base Branch

```bash
cd <working_directory> && git fetch origin <base_branch>
```

If fetch fails, abort and report network or authentication issue.

#### 2.2 Validate Clean Worktree

```bash
cd <working_directory> && git status --porcelain
```

If output is non-empty, abort and report that uncommitted changes or untracked files must be resolved first.

#### 2.3 Check for Unresolved Merge Conflicts

```bash
cd <working_directory> && git ls-files -u
```

If output is non-empty, abort and report that merge conflicts must be resolved before squashing.

#### 2.4 Check for Commits to Squash

```bash
cd <working_directory> && git log --oneline origin/<base_branch>..HEAD
```

If output is empty (no commits between HEAD and origin/<base_branch>), report the following message and exit early. Do not proceed to Step 3:

> **No commits to squash** — your branch is up-to-date with `origin/<base_branch>`.
> If you expected commits, verify with `git log origin/<base_branch>..HEAD` or push new commits before squashing.

#### 2.5 Verify Remote Branch State

Before resetting, verify the local branch matches the remote tracking ref:

```bash
cd <working_directory> && git fetch origin <branch_name>
```

If fetch fails, abort and report network or authentication issue.

Then compare local HEAD with the remote:

```bash
cd <working_directory> && git rev-parse HEAD
cd <working_directory> && git rev-parse origin/<branch_name>
```

If the two SHAs differ, the remote branch has commits not present locally. Alert the user:

> **Warning**: Remote branch `origin/<branch_name>` has diverged from local HEAD.
> Remote commits would be discarded by this squash. Aborting to prevent data loss.
>
> To investigate: `git log HEAD..origin/<branch_name>` to see remote-only commits.
> To proceed anyway: manually run `git push --force` after reviewing the commits.

Abort the operation. Do NOT proceed to Step 3.

If the remote branch does not exist (first push), this check passes and squash proceeds normally.

### 3. Get Commit Message

Get the oldest ticket-prefixed commit message (to preserve the original intent of the PR):

<!-- Pipeline breakdown:
     1. git log --oneline origin/<base_branch>..HEAD — lists commits between origin/<base_branch> and HEAD
     2. cut -d' ' -f2- — strips the commit hash, leaving only the message
     3. grep -E '^[A-Z]+-[0-9]+( |:|$)' — filters messages with ticket IDs at start, followed by space, colon, or end-of-line
     4. tail -1 — selects the oldest matching commit -->

```bash
cd <working_directory> && git log --oneline origin/<base_branch>..HEAD | cut -d' ' -f2- | grep -E '^[A-Z]+-[0-9]+( |:|$)' | tail -1
```

The regex `^[A-Z]+-[0-9]+( |:|$)` matches ticket prefixes at the start of the message (e.g., `NES-124 Add feature`, `NES-124: Fix bug`, or bare `NES-124`), preventing false matches on messages that merely contain ticket-like patterns elsewhere.

**Fallback behavior:** If no ticket-prefixed commit is found, the oldest commit message in the range is used intentionally. This preserves the first meaningful commit message when no ticket prefix exists:

```bash
cd <working_directory> && git log --oneline origin/<base_branch>..HEAD | tail -1 | cut -d' ' -f2-
```

This command gets the last line of the log (oldest commit), then strips the commit hash to leave only the message.

**Override option:** If the auto-selected message is undesired, you can manually specify a commit message by replacing `<commit_message>` in Step 4 with your preferred message.

**Optional post-squash refinement:** If you want to change the squashed commit message after finishing Step 4, use `git commit --amend -m "Your preferred message"` followed by `git push --force-with-lease`. This is purely optional and only needed if the auto-selected or manually specified message is unsatisfactory after the squash is complete.

### 4. Squash and Force Push

The `git reset --soft origin/<base_branch>` command moves HEAD to the base branch commit while preserving all changes in the staging area (index). This allows all branch commits to be recommitted as a single squashed commit.

Verify you intentionally want to rewrite history before proceeding with force push.

```bash
cd <working_directory> && git reset --soft origin/<base_branch> && git commit -m "<commit_message>" && git push --force-with-lease
```

If any step fails, see the **Error Handling** section for diagnosis and recovery steps.

### 5. Output Summary

Replace `<worktree_path>`, `<branch_name>`, and `<commit_message>` placeholders with the values extracted in Step 1 and Step 3:

```text
================================================================================
SQUASH COMPLETE
================================================================================

Worktree: <worktree_path>
Branch: <branch_name>
Commit: <commit_message>
================================================================================
```

## Example

```bash
/squash NES-124
```

## Error Handling

- **No PR found**: Report that a PR must be open for the branch
- **No commits to squash (HEAD == base_branch)**: When `git log --oneline origin/<base_branch>..HEAD` returns empty output, report "No commits to squash — your branch is up-to-date with origin/<base_branch>" and exit early; skip the squash (Step 4) and force push entirely since `git reset --soft` followed by `git commit` would fail with nothing to commit. Remediation: verify with `git log origin/<base_branch>..HEAD` to confirm no commits exist, or push new commits before squashing
- **Missing or invalid remote branch**: Report that the specified remote/branch does not exist or is unreachable; verify remote name and branch exist with `git remote -v` and `git branch -r`
- **Commit creation fails**: The `git commit` step after `git reset --soft` can fail due to:
  - Pre-commit hook failure: A hook rejected the commit (e.g., linting, formatting, tests). Remediation steps:
    1. **Investigate the failure**: Read the hook output to identify which check failed. Run the hook command directly (e.g., `pre-commit run --all-files` or the specific linter/formatter) to get detailed diagnostics.
    2. **Fix the underlying issue**: Address lint errors, apply formatting fixes, or resolve test failures. Stage any auto-fixed files with `git add`.
    3. **Retry the commit**: Run `git commit -m "<commit_message>"` again after fixing.
    4. **Last resort — bypass with caution**: Only use `git commit --no-verify` if you have investigated and confirmed the hook failure is a false positive or transient issue. This bypasses all pre-commit checks and may violate repository or CI policies. Bypassing hooks should require explicit reviewer or maintainer approval before merging.
  - Merge conflicts during reset: Conflicts can occur if the soft reset creates an inconsistent index state. Remediation: run `git status` to identify conflicting files, resolve them manually, stage with `git add`, then commit
  - Empty commit: If all changes were already in the base branch, nothing to commit. Remediation: verify the branch has diverged from base with `git log origin/<base_branch>..HEAD`
- **Remote branch diverged (preflight check)**: The preflight check (Step 2.5) detected that `origin/<branch_name>` has commits not present locally. This prevents the squash from silently discarding remote work. Remediation: run `git log HEAD..origin/<branch_name>` to see what commits exist on the remote; either incorporate them with `git pull --rebase` before squashing, or if they should be discarded, manually run `git push --force` after the squash
- **Force push rejected**: The `git push --force-with-lease` can fail due to:
  - Branch protection rules: The remote repository has branch protection enabled that blocks force pushes. Remediation: use a non-protected branch, or contact repository admins to temporarily allow force push or add an exception
  - Remote ref mismatch (--force-with-lease): The remote branch has new commits not present locally, causing the lease check to fail. To diagnose:
    ```bash
    git fetch origin <branch_name>
    git log --oneline HEAD..origin/<branch_name>  # Remote-only commits
    git log --oneline origin/<branch_name>..HEAD  # Local-only commits
    ```
    If remote has unexpected commits (someone else pushed, or you pushed from another machine), do NOT retry force-push as this would discard those commits. Integrate remote changes first with `git pull --rebase origin <branch_name>`, then re-run the squash. Using `git push --force` (without lease) is only safe when: (1) you intentionally rewrote local history, (2) you verified no unexpected remote commits exist, and (3) you coordinated with any collaborators on this branch.
  - Permission errors: The authenticated user lacks push permissions. Remediation: verify authentication with `gh auth status` and check repository access permissions
  - Network errors: Wait and retry after verifying GitHub connectivity (`ping github.com`) or verify your GitHub authentication with `gh auth status`
- **Protected branch + --force-with-lease**: When the branch is protected AND using `--force-with-lease`, rejection can occur from either protection rules or ref mismatch. Remediation: first verify if protection is the issue (check repo settings); if not, fetch and compare with `git fetch origin && git log origin/<branch_name>..HEAD` to diagnose ref mismatch
- **Uncommitted changes in worktree**: Report that local modifications must be stashed or committed before squashing; run `git stash` or `git commit` first
- **Failure of uv run pr get-pr**: Surface the underlying command error; suggest retrying, checking UV CLI installation, or verifying GitHub authentication
