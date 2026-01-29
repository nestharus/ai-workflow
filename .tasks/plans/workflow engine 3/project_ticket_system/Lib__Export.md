# Library: Ticket Completion & Export (`export`)

- **Primary responsibility**: Define the rules and mechanisms for completing a ticket, exporting patch stacks, and producing shareable evidence bundles.
- **Depends on**: `wss_surfaces`, `lifecycle`, `validate`
- **Used by**: `tm`

## 1) Ticket completion requirements (normative)

Ticket completion requires:
1. Required validation workflow passes.
2. Export the ticket stack using an explicit export policy.
3. Record export metadata in `ticket.json`.
4. Mark ticket `done` (per `project_ticket_system/Lib__Lifecycle.md` §1).

### 1.1 Empty plan ticket close eligibility (normative)

A ticket MAY be closed even if all tasks completed via empty step plans (`steps: []`), provided:

1. All tasks are in `completed` status (empty plan completion counts as `completed`)
2. Ticket validation workflow passes (validation is NOT bypassed for empty plans)
3. Each empty-plan task has a recorded rationale in its evaluation artifacts (§6.2 of `decompose`)

Empty plan tickets:
- Validation still runs even when no code changes were made
- The validation workflow may pass trivially if there are no changes to test
- Export produces a no-op commit or is skipped entirely (policy-dependent, see §1.2)

### 1.2 Export policy for empty plans (normative)

When exporting a ticket where `base_rev == tip_rev` (no actual changes):

- `squash` policy: Create no commit; record `no_change: true` and omit `exported_tip`
- `linear` policy: Create no commits; record `no_change: true` and omit `exported_tip`

The export is still considered successful, and the ticket may transition to `done` (per `project_ticket_system/Lib__Lifecycle.md` §1).

Concurrency (normative):
- All lock acquisition MUST comply with the global lock order defined in `Tech_Plan__Core_Infrastructure/05_Multi_Writer_Correctness.md` §6.4.
- Export operations MUST acquire `locks/branch.<name>.lock` before exporting to a branch/ref.
- Ticket state updates (e.g., writing export metadata to `ticket.json`) MUST occur under `locks/ticket.<ticket_id>.lock`.

### 1.3 Lock acquisition (normative)

- Export typically runs after ticket completion, when the ticket lock is already released, so branch lock acquisition is safe.
- If export needs to read ticket state while holding `locks/branch.<name>.lock`, `locks/ticket.<ticket_id>.lock` MUST NOT be acquired (would violate the global lock order); instead, read ticket state before acquiring the branch lock.

## 2) Export policy selection (normative)

### 2.1 Dependency validation (normative)

Dependencies are declared via `ticket.json.depends_on[]` (see `wss_surfaces` §2.1), the dependency semantics are defined by `tm` §4.2.4, and the `done` transition gating rules are defined by `lifecycle` §1.8.

Before exporting a ticket, TM MUST validate dependencies:

1. Load `ticket.json.depends_on[]`
2. For each dependency ticket ID:
   - Verify the dependency ticket exists
   - Verify the dependency ticket status is `done`
   - Verify the dependency ticket has `export.exported_tip` set (successfully exported)
3. If any dependency is not satisfied:
   - Fail with `E_DEPENDENCY_NOT_EXPORTED`
   - Include unsatisfied dependency IDs in error details
   - Do NOT proceed with export

**Circular dependency detection (normative)**:
- When setting `depends_on[]` (via CLI or ticket creation), perform topological sort
- If a cycle is detected, reject with `E_CIRCULAR_DEPENDENCY`
- Include the cycle path in error details (e.g., `A → B → C → A`)

**Rebase ordering (normative)**:
- Dependencies define a partial order for export
- If multiple tickets are ready to export, any valid topological order is acceptable
- Users MAY export tickets in any order that respects dependencies

### 2.2 Dependency error structures (normative)

`E_DEPENDENCY_NOT_EXPORTED`:
```json
{
  "error_code": "E_DEPENDENCY_NOT_EXPORTED",
  "ticket_id": "<current_ticket>",
  "unsatisfied_dependencies": [
    {"ticket_id": "<dep_id>", "status": "in_progress", "reason": "not_done"},
    {"ticket_id": "<dep_id>", "status": "done", "reason": "not_exported"}
  ]
}
```

`E_CIRCULAR_DEPENDENCY`:
```json
{
  "error_code": "E_CIRCULAR_DEPENDENCY",
  "cycle_path": ["ticket_A", "ticket_B", "ticket_C", "ticket_A"]
}
```

Default export policy: `squash`

Selection mechanisms (highest precedence first):
1. CLI flag:
   - `workflowctl ticket close --export-policy squash|linear`
2. Per-ticket override in `ticket.json`:
   - `ticket.json.export.policy`
3. Global config default:
   - `[export] policy = "squash"`

## 3) Export policy semantics (normative)

### 3.1 Squash
`squash` exports the ticket as a single commit representing the net diff from `base_rev` → `tip_rev`.

- Create a new commit on top of `base_rev` with:
  - message derived from ticket title + step summary
  - content equal to the full diff of the ticket stack
- Create or move export bookmark:
  - `export/<ticket_id>` → squash commit

### 3.2 Linear
`linear` exports the ticket as a linear sequence of commits preserving internal steps.

- Rebase each ticket commit in order onto `base_rev`, producing a new linear chain
- Create or move export bookmark:
  - `export/<ticket_id>` → tip of exported linear chain

## 4) Export target and metadata (normative)

Export produces:
- a bookmark under the local jj repo (default `export/<ticket_id>`)

Minimum export metadata in `ticket.json`:

```json
{
  "export": {
    "policy": "squash|linear",
    "bookmark": "export/<ticket_id>",
    "exported_tip": "<commit id>",
    "source_tip_rev": "<commit id>",
    "exported_at": "<rfc3339>",
    "validated": true,
    "no_change": false
  }
}
```

## 5) Export scrubbing (shareable bundles)

If the user chooses to share run/ticket evidence:
- TM triggers `workflowctl export scrub`
- scrubber runs secret scan + redaction per Core privacy policy
- produces shareable archive + redaction manifest

## 6) Review export (blocked tickets)

To reduce friction while preserving trust, export supports two modes:

1. Validated export (default; required for `done`)
   - only allowed when required validation passes
   - TM transitions the ticket to `done` (per `project_ticket_system/Lib__Lifecycle.md` §1)

2. Review export (allowed when blocked)
   - allowed even when validation is failing
   - exports current patch stack to `review/<ticket_id>`
   - ticket remains in `blocked` state (no transition; see `project_ticket_system/Lib__Lifecycle.md` §1) and MUST be explicitly labeled:
     - `ticket.json.export.validated = false`
     - `ticket.json.export.source_tip_rev` recorded (ticket tip at export time)
     - include a link to the failing validation report
