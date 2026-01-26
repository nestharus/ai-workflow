# Library: Validation (`validate`)

- **Primary responsibility**: Define the sandbox-based validation workflow contract required for ticket completion.
- **Depends on**: `wss_surfaces`, `workflow_resolver`
- **Used by**: `tm`, `export`, `lifecycle`

## 1) Validation is required

Validation is a workflow (default `ticket_validate_v1`) and MUST block ticket close on failure (see `lifecycle` and `export`).

## 2) Minimum required behavior (normative)

Validation MUST:
1. Create sandbox (jj workspace) from ticket tip.
2. Capture environment metadata (`env_capture.json`).
3. Run configured commands (see §3).
4. Persist raw outputs as artifacts:
   - stdout/stderr
   - junit/json reports when available
5. Produce a structured summary:
   - pass/fail
   - failing commands
   - key error excerpts (bounded)
6. Block ticket close on failure.

Artifacts:
```text
workspace/runs/<run_id>/artifacts/sandbox/validation_summary.json
workspace/runs/<run_id>/artifacts/sandbox/commands/<cmd_id>/{stdout,stderr,meta}.*
```

## 3) Validation command result interpretation (normative)

A validation workflow executes an ordered list of commands. Each command record MUST include:
- `cmd_id` (string)
- `argv` (array of strings)
- `cwd` (repo-relative path; optional)
- `timeout_ms` (int; optional)
- `success_exit_codes` (array of ints; default `[0]`)
- `optional` (bool; default `false`)
- `fail_on_stderr` (bool; default `false`)

Interpretation:
- Command **pass** if:
  - `exit_code ∈ success_exit_codes`, AND
  - if `fail_on_stderr=true`, `stderr` is empty
- Command **fail** if:
  - `exit_code` not in `success_exit_codes`, OR
  - it times out, OR
  - the process cannot be started

Timeout handling:
- timeout is failure with:
  - `status: "timeout"`
  - `exit_code: null`
  - `timed_out: true`

Overall result:
- `validation_summary.status = "pass"` only if all **non-optional** commands pass.
- any failing non-optional command makes the summary `fail`.
- optional command failures MUST be recorded but MUST NOT block ticket close; they produce a `warn` notification.

stdout/stderr:
- stdout and stderr are always captured as artifacts.
- stderr alone does not fail a command unless `fail_on_stderr=true`.

## 4) Recovery when validation fails (normative)

On validation failure, TM MUST:
- set `ticket.json.status = "blocked"`
- write a human-readable `validation_report.md` alongside the structured summary
- emit a notification with:
  - failing command(s)
  - artifact paths (stdout/stderr, reports)
  - the recommended next action

Supported user actions:
1. Create follow-up task from report:
   - `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`
2. Run a repair workflow:
   - `workflowctl run --workflow ticket_repair_v1 --ticket <ticket_id> --run <run_id>`
   - repair MUST validate in a sandbox before proposing RESUME/RETRY
3. Export for review without closing:
   - allowed: export to `review/<ticket_id>` while blocked
   - not allowed: marking ticket `done` while required validation is failing

Invariant:
- Ticket close remains blocked until required validation passes; any unvalidated export MUST be clearly labeled and MUST NOT flip ticket to `done`.
