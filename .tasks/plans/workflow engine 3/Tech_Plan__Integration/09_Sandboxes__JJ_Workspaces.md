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

##### Pattern derivation algorithm (normative)

Given a set of file input paths (from step-plan or derived), the following algorithm computes the final sparse pattern set:

**Input**: `file_inputs = [p1, p2, ... pn]` (array of repo-relative file paths)

**Output**: `include_patterns = []` (array of normalized sparse patterns)

**Step 1**: Initialize empty set `P = {}`

**Step 2**: For each file path `p` in `file_inputs`:
   2.1. Normalize `p` (see §9.2.2 normalization rules)
   2.2. Reject `p` if it violates safety rules (absolute path, contains `..`, empty)
   2.3. Reject `p` if it contains glob metacharacters (`*`, `?`, `[]`, `**`) unless `x_allow_globs_in_inputs = true`:
       - If glob patterns are present and `x_allow_globs_in_inputs` is not true, fail with `E_VALIDATION_FAILED`
       - Include the violating path and requirement for `x_allow_globs_in_inputs: true` in error details
   2.4. If `p` contains glob patterns (`*`, `?`, `[]`, `**`) (only when `x_allow_globs_in_inputs = true`):
       - Extract `non_glob_prefix` by truncating at the first glob metacharacter
       - Add directory pattern `ensure_dir(non_glob_prefix)` to `P` (see TOO_BROAD rules in Step 5)
       - Do not add `p` directly; do not attempt pre-expansion
   2.5. If `p` contains no glob patterns (ordinary path):
       - Add exact file pattern: `P.add(p)`
       - Add parent directory pattern: `P.add(ensure_dir(dirname(p)))`

**Step 3**: Add toolchain root files (conditional):
   - If `[sandbox].include_toolchain_config = true` (default `true`):
     - For each toolchain config file `c` in the standard list (see `DEFAULT_TOOLCHAIN_FILES`):
       - If `c` exists at repo root, add `c` to `P`

**Step 4**: Stable deduplication with first-occurrence preservation:
   4.1. Initialize empty list `include_patterns = []`
   4.2. Initialize empty set `seen_patterns = {}`
   4.3. For each pattern `p` in `P` in insertion order:
       - If `p in seen_patterns`: skip (first occurrence preserved)
       - If `p` is a file path and is covered by an existing directory pattern in `include_patterns`, skip
       - If `p` is a directory and is a prefix of an existing pattern in `include_patterns`, keep both
       - Otherwise, add `p` to `include_patterns` and `p` to `seen_patterns`

**Step 5**: Broadness guard validation:
   5.1. Check for too-broad prefixes from glob-derived patterns:
       - For each pattern in `include_patterns`, check if it is a glob-derived prefix (added in Step 2.4)
       - If any glob-derived prefix is in `TOO_BROAD_PREFIXES` (default `{"", ".", "/"}`), mark pattern as `TOO_BROAD`
   5.2. If `len(include_patterns) > BROADNESS_THRESHOLD` (default 200) OR any pattern is marked `TOO_BROAD`:
       - If `policy.allow_full_fallback = true`:
         - Record deviation: "Escalated to full mode due to broadness (pattern count: X, broad prefixes present: Y)"
         - Emit notification at `warn` severity with deviation details
         - Escalate to full sparse mode (recreate sandbox with `sparse_mode=full`)
         - Return empty include_patterns (full mode takes precedence)
       - Else, fail with `E_SPARSE_DERIVATION_FAILED`
       - Include current pattern count, threshold, broad prefixes detected (if any), and list of broad patterns in error details

**Step 6**: Validate pattern count limit:
   6.1. If `len(include_patterns) > MAX_PATTERNS` (default 1000):
       - Fail with `E_SPARSE_PATTERN_LIMIT_EXCEEDED`
       - Include current count and limit in error details
   6.2. Return `include_patterns`

**Constants**:
- `DEFAULT_TOOLCHAIN_FILES = [".editorconfig", ".gitignore", "pyproject.toml", "requirements.txt", "poetry.lock", "package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "Makefile"]`
- `TOO_BROAD_PREFIXES = {"", ".", "/"}` (configurable via `[sandbox].too_broad_prefixes`)
- `BROADNESS_THRESHOLD = 200` (configurable via `[sandbox].broadness_threshold`)
- `MAX_PATTERNS = 1000` (configurable via `[sandbox].max_patterns`)

**Markers and tool requirements**:
- Marker patterns are included from `step.tool_requirements.markers[*].pattern` when provided
- Markers serve as explicit inclusion hints beyond derived file inputs
- If `tool_requirements` defines markers, add all marker patterns to `P` after Step 3 and before deduplication

##### Wildcard and directory pattern handling (normative)

**Glob patterns** (`*`, `?`, `[]`, `**`):
- Glob patterns are treated as **opaque strings** and passed to `jj sparse set`
- `jj` evaluates globs at sandbox creation time, matching against repo state
- If a glob pattern matches zero files, `jj` will record it with no effect
- The runner does NOT pre-expand globs except in the derivation expansion step (Step 2.4)

**Directory patterns** (trailing `/`):
- Patterns ending in `/` denote directory prefix matching
- `src/` matches all files under `src/` recursively
- Exact file patterns (`src/app.py`) have precedence over directory patterns

**Pattern overlap resolution**:
- Multiple patterns may reference the same files—this is acceptable
- `jj` evaluates sparse patterns as a union, not as overrides
- No deduplication beyond algorithm Step 4 is performed

##### Binary vs text file handling

The pattern derivation algorithm does **not** distinguish between binary and text files:
- File type is determined by extension and content during tool execution
- Binary files can be materialized in the sandbox if matched by patterns
- The `jj` sparse system treats all content uniformly

If a workflow needs to exclude binary files:
- Use workflow-level `sandbox.exclude_patterns` (未来的jj版本) when available
- Or use explicit directory patterns rather than wildcards for fine control

**Binary and oversize file edit escalation**:
- If a step requires editing a binary file or a file exceeding edit size limits (e.g., >10MB):
  - The system MUST force Mode B (sandbox with `sparse_mode=full`) OR escalate to `needs_user` state
  - No speculative automated patching of binary/oversize files is permitted
  - This requirement applies regardless of the derived sparse patterns or `sparse_mode` setting

##### Worked examples

**Example 1: Simple file inputs**

Input file inputs:
```
["src/main.py", "src/utils/helper.py", "README.md"]
```

Algorithm execution:
- Step 2.1-2.3: Normalize and validate all paths
- Step 2.5: Add exact patterns and parent dirs to `P` (no glob patterns): `{src/main.py, src/, src/utils/helper.py, src/utils/, README.md, /}`
- Step 3: (assume toolchain config enabled) Add `pyproject.toml` → `{..., pyproject.toml}`
- Step 4: Stable deduplication with insertion order:
  - In insertion order, preserve first occurrence of each unique pattern
  - Final `include_patterns` (after dedup): `[src/main.py, src/, src/utils/helper.py, src/utils/, README.md, /, pyproject.toml]`
- Step 5: Broadness guard check:
  - No glob-derived patterns, no too-broad prefixes detected
  - Pattern count (7) < BROADNESS_THRESHOLD (200)
  - Proceed with derived `include_patterns`

**Example 2: Overlap handling**

Input file inputs:
```
["src/app/feature.py", "src/app/", "src/app/common.py"]
```

Algorithm execution:
- Step 2.5: Add exact patterns and parent dirs to `P`: `{src/app/feature.py, src/app/, src/app/, src/app/common.py, src/app/}`
  - Note: `src/app/` appears multiple times (once as explicit input, once as parent)
- Step 4 Stable deduplication in insertion order:
  - `src/app/feature.py` → add to `include_patterns`
  - `src/app/` (first explicit input) → add to `include_patterns`
  - Subsequent `src/app/` entries → skip (already in `seen_patterns`)
  - `src/app/common.py` → skip (covered by existing `src/app/` directory pattern)
  - Final `include_patterns`: `[src/app/feature.py, src/app/]`

**Example 3: Glob rejection (default behavior)**

Input file inputs (without `x_allow_globs_in_inputs: true`):
```
["src/**/*.py", "README.md"]
```

Algorithm execution:
- Step 2.3: `src/**/*.py` contains glob metacharacters
- Reject with `E_VALIDATION_FAILED`: "Glob patterns in file inputs require `x_allow_globs_in_inputs: true`. Invalid path: src/**/*.py"

**Example 4: Too-broad detection**

Input file inputs:
```
["file1.txt", "file2.txt", ..., "file201.txt"] (201 files)
```

Assume `BROADNESS_THRESHOLD = 200`, `policy.allow_full_fallback = true`:

Algorithm execution:
- Step 5: Broadness guard detects 201 patterns exceeds threshold
- Since `policy.allow_full_fallback = true`: escalate to full sparse mode
- Recreate sandbox with `sparse_mode=full`, return empty `include_patterns`

##### Pattern breadth limits and escalation

When derived patterns are too broad (approaching full checkout):

**Detection**:
- If `len(include_patterns) > BREADTH_THRESHOLD * total_files_in_repo` (default `BREADTH_THRESHOLD = 0.5`)
- Emit a warning at `info` severity:
  - "Derived sparse patterns include ~X% of repo files; consider using `sparse_mode=full`"

**Automatic escalation to full mode** (optional, opt-in):
- If `[sandbox].auto_escalate_to_full = true` (default `false`):
  - When breadth threshold exceeded, recreate sandbox with `sparse_mode=full`
  - Log escalation and skip pattern derivation entirely

**User override**:
- Workflow declarer can set `sandbox.sparse_mode = full` explicitly to override derivation

##### Default derivation by sandbox purpose (normative apply of algorithm)

**If `purpose` is `validation`, `rebase_conflict`, or `evaluation`**:
- Use a full working copy (`sparse_mode = full`)
- Do not apply derived include patterns (full means full).

**If `purpose` is `step_edit`**:
- Use an empty working copy (`sparse_mode = empty`)
- Run the derivation algorithm above on the declared step file list
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
