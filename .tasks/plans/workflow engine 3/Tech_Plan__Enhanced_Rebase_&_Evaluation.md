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

### 2.3 Resolution option format (trust)
Resolvers MUST output at least two options when feasible:
- Option A: conservative / minimal change
- Option B: higher-level refactor (if it improves correctness)

The user may select, or the system may choose if one is strictly dominated by constraints. Choice rationale is persisted.

## 3) Patch quality gates (ties rebase + patch generation together)

### 3.1 Stage 1: Hunk-lint (fast reject, per patch)
- validate patch format
- dry-run apply patch to hydrated base
- optional syntax check on changed files
- repeated identical failure signature twice → force sandbox mode or escalate

### 3.2 Stage 2: Sandbox validation (required at ticket close)
- create sandbox workspace from ticket tip
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

## 5) Test selection (workflow-defined, evidence-backed)

### 5.1 Selected default (Phase 1)
- changed-package + smoke tests (heuristic)
- record selection rationale as durable artifact

Required artifact:
`workspace/runs/<run_id>/artifacts/test_selection_rationale.json`

### 5.2 Optional improvements (user-enabled)
- symbol → test reverse dependency mapping
- higher precision, lower runtime, but adds indexing complexity

## 6) Risk register (rebase/eval layer)

| Risk | Severity | Control(s) |
|---|---:|---|
| Conflict resolution repeats without learning | Medium | persist conflict records + conclusions; consult before investigating |
| Validation results are not reproducible | Medium | env capture + tool fingerprints; workflow-defined commands |
| Evaluation artifacts drift from reality | Medium | source truth from logs + jj stack, not memory |
| Tool output is noisy | Low | persist raw output + structured summary; avoid silent filtering |
