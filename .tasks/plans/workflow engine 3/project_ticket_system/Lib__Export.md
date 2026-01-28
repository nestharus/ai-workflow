# Library: Ticket Completion & Export (`export`)

- **Primary responsibility**: Define the rules and mechanisms for completing a ticket, exporting patch stacks, and producing shareable evidence bundles.
- **Depends on**: `wss_surfaces`, `lifecycle`, `validate`
- **Used by**: `tm`

## 1) Ticket completion requirements (normative)

Ticket completion requires:
1. Required validation workflow passes.
2. Export the ticket stack using an explicit export policy.
3. Record export metadata in `ticket.json`.
4. Mark ticket `done`.

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

- `squash` policy: Create no commit; record `exported_tip: null` and `no_change: true` in metadata
- `linear` policy: Create no commits; record `exported_tip: null` and `no_change: true` in metadata

The export is still considered successful, and the ticket may transition to `done`.

Concurrency (normative):
- Export and ticket state updates MUST be performed under:
  - `locks/ticket.<ticket_id>.lock`
  - `locks/branch.<name>.lock` for the export target bookmark/ref (Core §6.3)

## 2) Export policy selection (normative)

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
    "exported_at": "<rfc3339>",
    "validated": true
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
   - ticket transitions to `done`

2. Review export (allowed when blocked)
   - allowed even when validation is failing
   - exports current patch stack to `review/<ticket_id>`
   - ticket remains `blocked` and MUST be explicitly labeled:
     - `ticket.json.export.validated = false`
     - include a link to the failing validation report
