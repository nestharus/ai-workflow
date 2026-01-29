# Usage — Backup and Restore

- **Doc**: Usage__Backup_and_Restore.md
- **Updated**: 2026-01-29
- **Primary responsibility**: User-facing guidance for creating and restoring portable backups of durable workflow engine state.
- **Related specs**:
  - Core Infrastructure §15.3: Backup/restore behavior and `backup_manifest.json`
  - Core Infrastructure §12: Secrets policy (OS keychain; never exported)
  - Configuration & Onboarding §7: CLI commands summary

## Overview

`workflowctl backup` creates a portable ZIP snapshot of **durable** state under the repo runtime root.
`workflowctl backup restore` restores that snapshot into the runtime root for the **current** `repo_uid` and then runs integrity checks.

Backups intentionally **do not** export secrets (they remain in the OS keychain). Backups include `backup_manifest.json` at the ZIP root to document scope, provenance, and the secrets policy.

## When to back up

Use backups for:
- Migrating to a new machine
- Disaster recovery after disk corruption
- Capturing a known-good state before risky operations (large refactors, workflow changes)
- Sharing reproducible evidence (logs + WSS) without sharing secrets

Do NOT use backups for:
- Sharing secret material (API keys, tokens) — reconfigure secrets via OS keychain on the target machine

## Create a backup (step-by-step)

1) Ensure the repo is initialized (repo binding exists under `~/.workflow/repos/<repo_uid>/`):
```bash
workflowctl init
```

2) Optionally validate health before snapshotting:
```bash
workflowctl fsck
workflowctl doctor
```

3) Create the backup ZIP:
```bash
workflowctl backup create --output /path/to/backup.zip
```

What this captures (durable state):
- `workspace/**` (entire WSS)
- `logs/**` (all JSONL shards)
- `config.toml` (repo machine-local config)
- `repo.json` (repo identity metadata)
- `backup_manifest.json` (ZIP root; documents included/excluded scope, repo_uid, secrets policy, tool version)

What this excludes (ephemeral/non-portable):
- `sandboxes/**`, `caches/**`, `locks/**`, `vcs/**`, and temporary files (`*.tmp`)

## Restore a backup (step-by-step)

1) Ensure the repo checkout exists on the target machine.

2) Initialize the repo binding (ensures a current `repo_uid` context exists):
```bash
workflowctl init
```

3) Restore the backup:
```bash
workflowctl backup restore /path/to/backup.zip
```

Restore behavior:
- Reads and validates `backup_manifest.json` before extracting files.
- Restores into `~/.workflow/repos/<current_repo_uid>/` (overwrites existing durable files in that root).
- Runs `workflowctl fsck` after extraction and fails if integrity checks fail.

If the backup `repo_uid` does not match the current repo context, restore refuses by default. To proceed anyway:
```bash
workflowctl backup restore /path/to/backup.zip --force-repo-uid-mismatch
```

## Portability checklist

Before (or after) restore:
- Repo checkout exists at the same or an equivalent path (see `backup_manifest.json.repo_root` for reference).
- Dependencies are installed and compatible:
```bash
workflowctl doctor
```
- Secrets are reconfigured in the OS keychain on the target machine (backups do not contain secret values).

## Troubleshooting

### Repo UID mismatch

Symptom:
- Restore warns that the backup `repo_uid` differs from the current repo context and refuses to proceed.

What to do:
- Confirm you are in the intended repo checkout.
- If you intentionally want to restore into the current repo binding, rerun with:
```bash
workflowctl backup restore /path/to/backup.zip --force-repo-uid-mismatch
```

### `fsck` fails after restore

Symptom:
- Restore extracts files but then fails integrity verification.

What to do:
- Run `workflowctl fsck --full` to get a complete report.
- If corruption is reported, follow the recovery workflow:
```bash
workflowctl recover
```
- If problems persist, rerun restore from a known-good backup ZIP.

### Missing or incompatible dependencies

Symptom:
- `workflowctl doctor` reports missing tools or unsupported platform constraints.

What to do:
- Install the reported dependencies and rerun `workflowctl doctor` until it reports OK.

## Security considerations

- Backups never export secrets from the OS keychain.
- Treat backups as sensitive artifacts anyway: they contain logs and workspace state which may include file paths and operational metadata.
- Prefer storing backup ZIPs in an encrypted location appropriate for your environment.

