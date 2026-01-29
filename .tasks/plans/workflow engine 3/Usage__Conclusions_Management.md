# Usage — Conclusions Management

- **Doc**: Usage__Conclusions_Management.md
- **Updated**: 2026-01-29
- **Primary responsibility**: User-facing guidance for inspecting, disabling, measuring, exporting, and importing conclusions (“known failure → known fix” records).
- **Related specs**:
  - Monitoring §7: Conclusions lifecycle (`Tech_Plan__Monitoring_&_Investigator.md`)
  - Core Infrastructure — WSS §5.5: Conclusion document schema (`Tech_Plan__Core_Infrastructure/04_WSS_Workspace_State_Store.md`)
  - Integration §2: CLI contract (`Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md`)
  - Core Infrastructure §12: Privacy and secrets (`Tech_Plan__Core_Infrastructure/12_Privacy_Secrets_and_Export.md`)

## Overview

Conclusions are durable, evidence-backed “known failure → known fix” records that help the system:
- avoid repeating investigations for the same failure signature,
- auto-apply safe remediations once promoted,
- and share knowledge across repos via export/import.

Lifecycle states (Monitoring §7):
- `draft`: created from a single incident (unverified)
- `confirmed`: reproduced across distinct runs with the same signature
- `promoted`: repeatedly successful remediation; safe for auto-application

## Inspect conclusions

List conclusions by state:

```bash
workflowctl conclusions list --state promoted
```

Show a specific conclusion:

```bash
workflowctl conclusions show <conclusion_id>
```

Force-apply for debugging (records outcome for audit):

```bash
workflowctl conclusions apply <conclusion_id> --run <run_id>
```

## Measure effectiveness (stats)

Show effectiveness metrics over the last 30 days (default window):

```bash
workflowctl conclusions stats
```

Compute stats over a custom window:

```bash
workflowctl conclusions stats --since-days 7
```

Machine-readable output:

```bash
workflowctl conclusions stats --format json
```

## Temporarily disable a conclusion

Disable until a specific time (RFC3339 UTC):

```bash
workflowctl conclusions disable <conclusion_id> --until 2026-02-15T00:00:00Z --reason "Flaky remediation during dependency upgrade"
```

Disable indefinitely (defaults to a far-future timestamp):

```bash
workflowctl conclusions disable <conclusion_id> --reason "Known-bad after tool update; awaiting new fix"
```

Notes:
- Automatic application skips conclusions where `disabled_until > current_time`.
- Disabled conclusions remain visible for audit and can still be manually inspected.

## Share conclusions across repos (export/import)

Export all conclusions:

```bash
workflowctl conclusions export --out ./conclusions.export.json
```

Export only promoted conclusions and redact secrets:

```bash
workflowctl conclusions export --out ./conclusions.promoted.json --state promoted --redact-secrets
```

Import into another repo (default merge strategy: `skip`):

```bash
workflowctl conclusions import ./conclusions.promoted.json
```

Dry-run an import:

```bash
workflowctl conclusions import ./conclusions.promoted.json --dry-run
```

Overwrite existing conclusions:

```bash
workflowctl conclusions import ./conclusions.promoted.json --merge-strategy overwrite
```

Update-in-place (merge `applications[]` and `reproductions[]`):

```bash
workflowctl conclusions import ./conclusions.promoted.json --merge-strategy update
```

Important import rules (Monitoring §7.5.4):
- Imported conclusions start in `draft` state (require re-confirmation in the new repo).
- Disable state is not imported (`disabled_until` / `disabled_reason` are cleared).

## Best practices

- Disable quickly when a remediation becomes unsafe; always include a concrete reason.
- Export with `--redact-secrets` before sharing outside the repo boundary.
- Treat imported conclusions as suggestions until re-confirmed locally.

