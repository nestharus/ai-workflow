# Core Infrastructure — Repo Identity (`repo_uid`)

- **Doc**: Tech_Plan__Core_Infrastructure/02_Repo_UID_Identity.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.runtime.identity`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`01_Runtime_Root_Layout.md`](01_Runtime_Root_Layout.md)
- **Primary responsibility**: Define how a repo is bound to a machine-local runtime root via a stable `repo_uid`.

## 3) Identity: `repo_uid` (stable per repo per machine)

`repo_uid` identifies “this repo on this machine”. It is used to locate the repo binding directory under the runtime root.

### 3.1 Derivation (first init only; normative)

Default derivation:

`repo_uid = sha256(canonical_repo_root_path + "\n" + git_remote_url_or_empty).hexdigest()[:16]`

Where:

**`canonical_repo_root_path`** (string):
- Compute `repo_root` via `git rev-parse --show-toplevel`.
- Convert to an absolute path.
- Normalize:
  - resolve `..` / `.` segments
  - resolve symlinks when the OS provides a stable realpath (best-effort; do not fail if resolution fails)
  - on Windows: normalize drive letter to uppercase and use `/` as separator in the canonical string
  - remove any trailing slash

**`git_remote_url_or_empty`** (string):
- If `origin` exists: `git remote get-url origin`
- Otherwise: empty string
- Normalize by stripping surrounding whitespace.

### 3.2 Persistence rule (authoritative after creation)

- On `workflowctl init`, the derived `repo_uid` is written to `~/.workflow/repos/<repo_uid>/repo.json`.
- After `repo.json` exists, its stored `repo_uid` is authoritative.
- If the git remote changes later, DO NOT change `repo_uid` automatically (avoid orphaning state). A manual migration tool may be added later.
### 3.3 Collision handling (normative)

`repo_uid` collisions are extremely unlikely, but the runtime MUST handle them deterministically.

On `workflowctl init`:

1. Derive the candidate `repo_uid` per §3.1.
2. If `~/.workflow/repos/<repo_uid>/repo.json` does not exist → use it.
3. If it exists:
   - Load the existing `repo.json`.
   - If `repo.json.repo_root` matches the discovered `repo_root` (after the same canonicalization) → reuse it.
   - Otherwise, a collision (or user copy) has occurred.

Collision resolution rule (v1):
- Append a counter suffix: `<repo_uid>-<n>` where `n` starts at `1` and increments until a free directory is found.
- The final `repo_uid` MUST be written to the new `repo.json` and is authoritative thereafter.

### 3.4 Handling manual edits to `repo.json` (normative)

`repo.json` is authoritative after creation (§3.2), but manual edits may orphan state.

If the runtime detects that `repo.json.repo_uid` does not match its directory name, it MUST fail loudly with:
- error code: `E_VALIDATION_FAILED`
- details: `path`, `expected_repo_uid`, `actual_repo_uid`

The error message MUST instruct the user to either:
- restore `repo.json` from version control / backups, or
- re-run `workflowctl init` (which creates a new binding directory).

