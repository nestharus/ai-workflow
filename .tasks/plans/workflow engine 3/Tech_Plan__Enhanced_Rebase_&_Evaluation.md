# Tech Plan: Enhanced Rebase & Evaluation (Restructured)

- **Doc**: Tech_Plan__Enhanced_Rebase_&_Evaluation.md
- **Updated**: 2026-01-24
- **Component**: Rebase Engine + Evaluation Engine
- **Primary responsibility**: Make integration pain evidence-backed and repeatable (conflicts as data; validation and gap analysis as durable artifacts).

## 1) Enhanced rebase (jj Patch-Stream)

### 1.1 Purpose
Rebase a ticket’s jj change stack onto a new parent revision while:

- treating conflicts as resolver jobs (not “repo breakage”)
- gathering evidence from planning docs, deviations, prior conflict records
- persisting durable resolution records so the system learns

### 1.2 JJ capabilities relied upon
- colocated repos and normal repos are supported
- multiple workspaces (worktrees) are supported (`jj workspace add`)
- reading file contents at revisions (`jj file show`) is supported

References:
- CLI reference: https://docs.jj-vcs.dev/latest/cli-reference/
- Working copy / workspaces: https://docs.jj-vcs.dev/latest/working-copy/

### 1.3 Rebase workflow (high-level)
This is executed via workflow `rebase_enhanced_v1` by default.

1. Acquire `locks/ticket.<ticket_id>.lock`
2. Invoke jj rebase operation for the ticket stack (pointer move + replay)
3. If jj reports conflicts:
   - enumerate conflicts
   - create a resolver job per conflict (step executions)
4. For each conflict:
   - gather evidence:
     - hydrated versions of conflicted files on both sides
     - relevant WSS docs (project, ticket, task steps, deviations)
     - relevant conclusions (tool/perf)
     - past conflict resolution records
   - spawn investigator/resolver to propose options
5. Apply chosen resolution as a new patch on top of the stack
6. Persist a conflict resolution record referencing evidence
7. If unresolved automatically:
   - persist an escalated record
   - emit notification with concrete user instructions and artifact paths

### 1.4 Evidence gathering for conflicts (normative)

When a rebase produces a conflict, the system MUST gather bounded, relevant evidence to support:
- automated resolution proposals
- durable learning (Conflict Resolution Records, §2)
- post-mortems and reproducibility

#### 1.4.1 Evidence bundle location

For each conflict, create an evidence bundle directory:

```text
workspace/runs/<run_id>/artifacts/rebase/<bundle_id>/
  manifest.json
  files/
    <path_hash>/
      base.txt
      ours.txt
      theirs.txt
      conflict.txt
      meta.json
  wss/
    ticket.json
    project.json
    step_plan.yaml
    deviations.jsonl
  refs/
    prior_conflicts.jsonl
```

`bundle_id` MUST be a ULID.

#### 1.4.2 Relevance rules (v1)

The evidence bundle MUST include:

Always:
- the ticket document `workspace/tickets/<ticket_id>/ticket.json`
- the project document `workspace/projects/<project_id>/project.json`
- the current step plan used to produce the patch (`step_plan.yaml`) if available
- the most recent deviations log for the ticket (`deviations.jsonl`) (bounded to last 200 lines)

Per conflicted file path:
- “base/ours/theirs/conflict” text snapshots when the file is UTF-8 text and <= 1 MiB
- a `meta.json` containing:
  - repo-relative path
  - detected type: `text|binary|oversize`
  - byte size
  - sha256 of each snapshot (or of the working file if binary/oversize)

Prior conflict records (bounded):
- Include up to the last 10 conflict resolution records from:
  - `workspace/tickets/<ticket_id>/rebase/conflicts/`
  filtered by:
  - matching file path (exact match), OR
  - matching `failure_signature` when available (Hunk-lint §3.1.1)

#### 1.4.3 Bounding rules (v1)

The evidence gatherer MUST be bounded:

- Max conflicted paths to snapshot: 20  
  - If more, store only:
    - `manifest.json` listing all paths and hashes
    - snapshot the first 20 paths in deterministic order (lexicographic)

- Max per-file snapshot size: 1 MiB  
  - If larger: mark `oversize` and do not include full contents (store hash + path only)

Binary handling:
- If a file is detected as binary (NUL byte in first 8 KiB), mark `binary` and do not include full contents.

Any time content cannot be captured (binary/oversize), the resolver MUST treat the conflict as requiring user involvement (i.e., do not attempt speculative automated edits).
## 2) Conflict resolution records (durable learning)

### 2.1 Storage
```text
workspace/tickets/<ticket_id>/rebase/conflicts/<resolution_id>.md
```

### 2.2 Required fields
- `resolution_id`, `ticket_id`
- baseline + target stack identifiers
- affected paths
- `resolution_type`: `auto | manual | escalated`
- rationale (why this resolution)
- evidence refs:
  - run_id, step_execution_id, writer_id + seq ranges
  - WSS paths
  - jj change IDs

### 2.3 Resolution option format and selection policy

Resolvers MUST output at least two options when feasible:

- Option A: conservative / minimal change
- Option B: higher-level refactor (only when it improves correctness)

Each option MUST be a fully specified patch proposal that can be validated by the same gates as normal patch creation (hunk-lint, scope rules, etc.).

#### 2.3.1 Hard constraints

Before any option can be selected, it MUST satisfy all applicable hard constraints:

- Patch applies cleanly to the current ticket stack tip (or produces a resolvable conflict record)
- Stage 1 hunk-lint passes (see §3.1)
- Patch touches only allowed paths:
  - the conflict set paths, plus
  - explicitly allowed adjacent context paths (if declared)
- No new unresolved conflicts are introduced (unless the resolution type is explicitly `escalated`)
- Capability gating passes (Integration §7.3)

#### 2.3.2 Strict domination

Option X is **strictly dominated** by option Y if:

- X violates any hard constraint that Y satisfies, OR
- X fails Stage 1 hunk-lint and Y passes, OR
- X touches a strict superset of paths compared to Y while both satisfy all hard constraints

Strict domination is evaluated deterministically from artifacts (patch, hunk-lint results, scope lists).

#### 2.3.3 Selection policy

- If exactly one option satisfies all hard constraints, the system MAY auto-select it.
- If one option strictly dominates all others, the system MAY auto-select the dominating option.
- Otherwise, the system MUST:
  - stop with a `gate` (Workflow schema §7.2.3),
  - notify the user, and
  - require an explicit user selection.

In all cases, the chosen option and its selection rationale MUST be persisted in the conflict record (`resolution_id>.md` + optional `resolution_choice.json`).



## 3) Patch quality gates (ties rebase + patch generation together)

### 3.1 Stage 1: Hunk-lint

Stage 1 is a fast, deterministic gate that rejects invalid or unsafe patches **before** they are applied.

Required checks:

- Validate unified diff format
- Dry-run apply patch to the hydrated base (Mode A) or sandbox base (Mode B)
- Enforce scope: patch MUST NOT modify paths outside the step’s allowed write set
- Optional syntax checks on changed files (tooling is workflow-defined)

#### 3.1.1 Failure signature

When hunk-lint fails, it MUST produce a stable `failure_signature` for convergence detection.

Normative computation:

1. Build a JSON object:

```json
{
  "schema_version": 1,
  "kind": "hunk_lint_failure",
  "error_code": "<enum>",
  "patch_sha256": "<sha256 of patch.diff bytes>",
  "base_rev": "<resolved base commit id>",
  "tool_fingerprint": "<fingerprint string>",
  "stderr_sha256": "<sha256 of normalized stderr>"
}
```

2. Normalize stderr:
- UTF-8 decode with replacement
- Convert `\r\n` → `\n`
- Strip absolute paths that point inside sandboxes / temp dirs
- Strip line/column numbers (`:<digits>[:<digits>]`) to reduce noise

3. Canonicalize JSON:
- Sort object keys lexicographically
- Emit minified UTF-8 JSON (no whitespace)

4. Compute:
- `failure_signature = "sha256:" + sha256(canonical_json_bytes).hexdigest()`

The `failure_signature` MUST be stored in `hunk_lint.json`.

Storage (normative):
- Per attempt: `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/hunk_lint.json`
- Per ticket history (append-only): `workspace/tickets/<ticket_id>/indices/hunk_lint_failures.jsonl`

The per-ticket history record MUST include at least:
- `ts`, `ticket_id`, `step_id`, `run_id`, `step_execution_id`, `mode` (`A` or `B`), and `failure_signature`.


#### 3.1.2 Repeated failure handling policy

Repeated identical failures are tracked across attempts for the same `(ticket_id, step_id)`.

**Time window (v1)**:
- A failure is considered “repeated” when the same `failure_signature` has occurred **twice within the last 24 hours** for the same `(ticket_id, step_id)`.

**Source of truth for history**:
- `workspace/tickets/<ticket_id>/indices/hunk_lint_failures.jsonl` (append-only)

**Normative handling**:

On every hunk-lint failure:
1. Write `hunk_lint.json` into the current step execution artifacts (see §3.1.1).
2. Append a record to the per-ticket history file.
3. Count matching history records for `(ticket_id, step_id, failure_signature)` where `now - ts <= 24h`.

If the count is **>= 2**:

- If the current attempt was running in **Mode A**:
  - force the next attempt to run in **Mode B** (sandbox required)
  - record a deviation noting the mode change
  - emit a notification (`warn`) describing why Mode B is being forced

- Otherwise (already Mode B, or Mode B cannot be created):
  - escalate: stop the step and require user action

“Force Mode B” means:
- set step sandbox policy `required: true` for the retry attempt
- re-run the step with the same declared file scope

Escalation (normative):
- The step MUST end `failed` with error code `E_TOOL_FAILED` (or a more specific patch-apply code).
- The workflow runner MUST apply the step’s `on_failure` policy (Integration §7.2.9).
- The notification MUST include:
  - `failure_signature`
  - `mode` attempted
  - a pointer to the `hunk_lint.json` artifact path
### 3.2 Stage 2: Sandbox validation (required at ticket close)
- create sandbox (jj workspace) from ticket tip
- capture environment metadata (`env_capture.json`)
- run workflow-defined validation commands
- persist raw outputs + structured summary
- block ticket close on failure

## 4) Evaluation (sandbox-based gap analysis)

### 4.1 Purpose
Produce a durable report comparing:

- planned intent (WSS project/ticket/task docs)
- what was implemented (jj stack + deviations)
- what tools observed (validation artifacts + logs)

### 4.2 Outputs
Ticket-level:
```text
workspace/tickets/<ticket_id>/tasks/<task_id>/evaluation/gaps.md
```

Project-level:
```text
workspace/projects/<project_id>/evaluation/<timestamp>/gaps.md
```

If gaps found:
- raise notification with report path
- Project Manager can create new tickets directly from gaps

### 4.3 Evidence sourcing rule (trust)
Evaluation must source “what happened” from:
- logs shards
- WSS artifacts
- jj stack identifiers
Not from agent memory.

### 4.4 Evaluation algorithm v1

Evaluation is an evidence-backed comparison between:

- **Plan**: step plan + approvals + recorded deviations
- **Reality**: the actual ticket stack and validation artifacts

Normative algorithm:

1. Load plan artifacts (per task):
   - `tasks/<task_id>/steps/step_plan.json`
   - `tasks/<task_id>/steps/approval_decision.json`
   - `tasks/<task_id>/steps/verification_result.json`
   - `tasks/<task_id>/deviations/` (if present)

2. Load reality artifacts:
   - `base_rev` and `tip_rev` from `ticket.json`
   - VCS diff summary for `base_rev..tip_rev` (changed paths + stats)
   - validation summaries from `tasks/<task_id>/validation/` (or run artifacts)

3. Compute `planned_path_set`:
   - union of `step.inputs.files[*].path` across planned steps

4. Compute `actual_path_set`:
   - changed file paths in `base_rev..tip_rev`

5. Emit gaps:

- **Unplanned change**:
  - `path ∈ actual_path_set` but `path ∉ planned_path_set`
  - and there is no deviation that justifies the change

- **Missing planned change**:
  - a planned step is marked `done` but none of its declared files appear in `actual_path_set`
  - (this is a strong indicator that the plan was not actually implemented)

- **Validation missing**:
  - required validation workflow did not run for the ticket close attempt

- **Validation failed**:
  - validation workflow ran and produced failing status

6. Persist outputs:
   - `gaps.md` (human-readable)
   - `gaps.json` (machine-readable; suitable for ticket creation)

### 4.5 Gap taxonomy

Each gap item in `gaps.json` MUST include:

- `gap_id` (ULID)
- `gap_type` (enum): `unplanned_change|missing_planned_change|validation_missing|validation_failed|deviation_unresolved`
- `severity` (enum): `info|warn|error`
- `evidence_refs[]` (paths + run/step ids)

### 4.6 Invocation

Evaluation is executed:

- automatically during ticket close (after validation), and
- manually via Project Manager for project-level audits.

Evaluation MUST be repeatable from artifacts; it MUST NOT depend on agent memory.



## 5) Test selection (workflow-defined, evidence-backed)

Ticket close requires validation, but validation commands may be expensive. Test selection provides a default, evidence-backed way to choose which commands to run.

Test selection is **not** a silent optimization:
- the selection algorithm must emit a durable rationale artifact
- the user can override selection policy via workflow config or CLI flags

### 5.1 Inputs

- `base_rev` (ticket base)
- `tip_rev` (ticket tip)
- `changed_paths[]` (derived from VCS diff)
- workflow-defined validation commands (Project & Ticket Management §8)

### 5.2 Default algorithm v1

1. Compute `changed_paths` as the set of files changed between `base_rev..tip_rev`.

2. Derive `changed_packages`:
   - For each changed path, walk upward toward repo root until one of these “package root markers” is found:
     - `pyproject.toml`, `setup.cfg`, `setup.py`
     - `package.json`
     - `go.mod`
     - `Cargo.toml`
   - The nearest marker directory is the package root.
   - If no marker is found, the package root is repo root.

3. Select commands:
   - Always include commands tagged `smoke`.
   - Include package-scoped commands tagged `package` once per `changed_package`:
     - The runner sets `PWD` (or `cwd`) to the package root before running.
   - If no commands are tagged, run the full validation command list (loud: emit a warning notification that selection was impossible).

4. Emit rationale artifact:
   - `workspace/runs/<run_id>/artifacts/test_selection_rationale.json`

Minimum fields:

```json
{
  "schema_version": 1,
  "base_rev": "<commit>",
  "tip_rev": "<commit>",
  "changed_paths": ["..."],
  "changed_packages": ["..."],
  "selected_commands": [
    { "name": "pytest_smoke", "reason": "tag:smoke" }
  ]
}
```

### 5.3 Pluggability

Workflows may override the default by providing one of:

- a custom validation workflow (`ticket_validate_v1` override) that implements its own selection, or
- a tool step that writes `test_selection_rationale.json` and a filtered command list artifact.

The runner MUST persist the rationale artifact regardless of selection strategy.



## 6) Risk register (rebase/eval layer)

| Risk | Severity | Control(s) |
|---|---:|---|
| Conflict resolution repeats without learning | Medium | persist conflict records + conclusions; consult before investigating |
| Validation results are not reproducible | Medium | env capture + tool fingerprints; workflow-defined commands |
| Evaluation artifacts drift from reality | Medium | source truth from logs + jj stack, not memory |
| Tool output is noisy | Low | persist raw output + structured summary; avoid silent filtering |