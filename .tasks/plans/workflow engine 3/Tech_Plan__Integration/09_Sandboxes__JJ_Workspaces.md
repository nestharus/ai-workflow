# Tech Plan: Integration — Sandboxes (jj Workspaces)

- **Doc**: Tech_Plan__Integration/09_Sandboxes__JJ_Workspaces.md
- **Updated**: 2026-01-26
- **Shard**: Integration §9–§9.4
- **Libraries / packages**:
  - `scripts/core/sandbox/workspace_runner.py` — sandbox create/run/destroy
  - `scripts/core/vcs/jj_adapter.py` — baseline revset resolution + jj operations
  - `workflow_engine` subcommands `sandbox_create|sandbox_run|sandbox_destroy`
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (sandbox TTL semantics, retention, error model)

## 9) Sandboxes (cross-platform, low-friction)

### 9.1 Principle: sandboxes are jj workspaces
Sandboxes are implemented as **jj workspaces** (materialized working copies backed by a single repo store).

JJ workspaces are designed for parallel working copies:
- Working copy docs: https://docs.jj-vcs.dev/latest/working-copy/
- `jj workspace add` supports controlling sparse patterns (`--sparse-patterns`) (v0.22+):
  - https://man.archlinux.org/man/extra/jujutsu/jj-workspace-add.1.en
  - release note excerpt (v0.22): https://github.com/jj-vcs/jj/discussions/4568

Sparse patterns are controlled via `jj sparse`:
- https://docs.jj-vcs.dev/latest/cli-reference/ (see `jj sparse`)
- `jj sparse set` man page: https://man.archlinux.org/man/extra/jujutsu/jj-sparse-set.1.en

### 9.2 Sandbox creation algorithm

A **sandbox** is an ephemeral `jj` workspace created under the repo runtime root:

`~/.workflow/repos/<repo_uid>/sandboxes/<run_id>/<sandbox_id>/`

A sandbox is used to:
- execute tool commands in a materialized working copy
- preserve tool outputs as durable evidence (logs, exit codes)
- avoid mutating the user’s primary working copy

#### 9.2.1 Inputs

Sandbox creation is called with:

- `repo_root` (absolute path)
- `baseline_revset` (string; resolves to a single revision)
- `purpose` (string enum): `step_edit|validation|rebase_conflict|evaluation`
- `sparse_mode` (string enum): `copy|full|empty`
- optional `include_patterns` (array of strings)

#### 9.2.2 Pattern syntax and normalization

- Patterns are passed **verbatim** to `jj sparse set --add <pattern>`.
- The runner does not interpret pattern semantics beyond basic safety checks.

Normalization rules applied by the runner:

- Convert Windows `\` separators to `/`
- Reject absolute paths
- Reject paths containing `..` segments
- Reject empty strings

Notes:

- Current `jj` sparse patterns are effectively an **unordered list of path prefixes** (e.g., `src/`, `README.md`). Future `jj` versions may support richer include/exclude rules; this system treats patterns as opaque strings and relies on `jj` for interpretation.

#### 9.2.3 Sparse pattern selection and derivation

Patterns are selected from one of the following sources, in priority order:

1. **Workflow explicit include patterns**  
   - Workflow YAML step: `sandbox.include_patterns: [...]` (Workflow schema §7.2.5)  
   - If present, these patterns are applied exactly.

2. **Step-plan declared file inputs**  
   - If the step is derived from a step plan, use `step.inputs.files[*].path` (Project & Ticket System §6.4).

3. **Fallback defaults by sandbox purpose**  
   - Used only when neither (1) nor (2) is available.

Default derivation (normative):

- If `purpose` is `validation`, `rebase_conflict`, or `evaluation`:
  - Use a full working copy (`sparse_mode = full`)
  - Do not apply derived include patterns (full means full).

- If `purpose` is `step_edit`:
  - Use an empty working copy (`sparse_mode = empty`)
  - Derive `include_patterns` from the declared step file list:
    - For each file `p`:
      - add `p`
      - add the immediate parent directory of `p` (e.g., `src/` for `src/app/main.py`)
    - Add toolchain “root” files to increase tool correctness:
      - `.editorconfig`, `.gitignore`
      - `pyproject.toml`, `requirements.txt`, `poetry.lock`
      - `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`
      - `go.mod`, `go.sum`
      - `Cargo.toml`, `Cargo.lock`
      - `Makefile`
  - If the step file list is missing or empty, fail loudly with `E_SPARSE_DERIVATION_FAILED` (Core §8.2.5).

#### 9.2.4 Algorithm

Given `(repo_root, baseline_revset, purpose, sparse_mode, include_patterns)`:

1. Allocate `sandbox_id` (ULID)
2. Create directory:
   `~/.workflow/repos/<repo_uid>/sandboxes/<run_id>/<sandbox_id>/`
3. Create a `jj` workspace:
   - `jj workspace add <sandbox_path> --name <sandbox_id> --revision <baseline_revset> --sparse-patterns <copy|full|empty>`
4. Apply sparse patterns (if any):
   - If `include_patterns` is present and non-empty:
     - `jj sparse set --clear --add <pattern> ...` inside the sandbox (jj workspace)
5. Record sandbox metadata:
   - `sandbox_id`, `run_id`, `repo_uid`
   - baseline revset / resolved commit id
   - `purpose`
   - `sparse_mode` and the final applied pattern list
   - `jj` version and platform info
   - → `workspace/runs/<run_id>/artifacts/env/sandbox_<sandbox_id>.json`

#### 9.2.5 Additivity and expansion within a step

- Sandboxes are **per step** by default. Sparse patterns are **not** additive across steps.
- Within a single step execution, sparse patterns may be expanded **monotonically** if:
  - a tool command fails due to missing files that the runner can deterministically identify, and
  - the step’s sandbox policy allows expansion (`x_allow_sparse_expand: true`).

Any expansion MUST:
- be recorded in the sandbox manifest for the step run
- be visible to the user (notification at `info` severity)
- only ever **add** patterns (never remove)

##### Detecting “missing file due to sparse patterns” (normative)

After a sandbox tool invocation fails (non-zero exit code), the runner MAY attempt sparse expansion only if it can extract one or more repo-relative missing paths from the tool output.

Deterministic extraction rules (v1):
- Scan the combined `stdout+stderr` for lines matching common “missing file” patterns, including:
  - `No such file or directory` with a path
  - `cannot open` / `file not found` with a path
- Extract candidate paths and normalize:
  - convert to repo-relative paths (strip sandbox absolute prefix if present)
  - reject absolute paths, paths containing `..`, or paths that escape the repo root
- If zero safe paths are extracted, DO NOT expand; treat the failure as a normal tool failure.

Expansion action (v1):
- Add each extracted file path AND its parent directory pattern to the sandbox sparse set:
  - `jj sparse set --add <path> --add <parent_dir/>`
- Re-run the tool exactly once after the expansion.
- If the second run also fails with missing file output:
  - do not loop;
  - surface `E_SPARSE_DERIVATION_FAILED` and include the extracted paths in error `details`.

The runner MUST NOT automatically remove patterns during a run.
### 9.3 Copy/full fallback (enabled by default; guarded)

Some repos/tools require more files than sparse heuristics capture. The system supports a guarded fallback path to reduce user friction.

Config:
- `[sandbox].copy_fallback = true` by default (Core Infrastructure §11.4)

#### 9.3.1 When fallback triggers (normative)

Fallback may trigger only when ALL are true:

1. The failing step is running inside a sandbox with sparse patterns (i.e., not already `sparse_mode="full"`), AND
2. The tool invocation fails, AND
3. The failure looks like “missing file due to sparse patterns” per §9.2.5, AND
4. Sparse expansion (if allowed) did not resolve the failure OR was not allowed.

If the failure does not match missing-file patterns, fallback MUST NOT trigger.

#### 9.3.2 Fallback algorithm (v1; bounded) (normative)

When fallback triggers, the runner MUST attempt at most two fallback escalations in this order:

1. **Copy fallback**  
   - Recreate the sandbox with `sparse_mode="copy"` (copy sparse patterns from the source workspace)
   - Apply the current include pattern list (if any)
   - Re-run the tool once

2. **Full fallback**  
   - If the copy fallback still fails with missing-file output:
     - Recreate the sandbox with `sparse_mode="full"`
     - Re-run the tool once

If full fallback fails, the runner MUST fail loudly with `E_SPARSE_DERIVATION_FAILED` and include:
- the tool command
- the extracted missing paths (if any)
- the sandbox modes attempted (`empty|copy|full`)

#### 9.3.3 User visibility and evidence

Every fallback escalation MUST:
- write a notification (`warn`) describing the fallback and the mode used
- record the fallback in the sandbox manifest artifact (Integration §9.2.4)
### 9.4 Sandbox destruction (mandatory cleanup)
- Destroy tool subprocesses
- Flush sandbox logs and persist required artifacts
- Remove workspace directory
- Run `jj workspace forget` if required by jj state
All actions are logged.
