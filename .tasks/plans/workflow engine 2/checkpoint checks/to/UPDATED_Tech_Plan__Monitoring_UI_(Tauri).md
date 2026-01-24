# Tech Plan: Monitoring UI (Tauri)

## Overview

This spec defines the optional desktop UI for monitoring. After the migration, the MVP UI is **notifications-only**:

- no database
- no ports required
- UI does not gate workflows

The UI consumes durable notifications from the filesystem Notifications Store via a helper command and writes requests back via the Control Actions Queue.

**Constraints & Invariants**

- Local-only, single-machine execution. Not distributed, not cloud.
- Runtime artifacts are local and not committed to git.
- Prefer robustness over micro-optimizing I/O.
- Step logging is always on (step enter/exit + key events).
- Dynamic tracing is optional and enabled per-step when needed.
- Root orchestration is flat: root directly owns/controls all step/agent processes (no grandchildren).
- Pause is mandatory: on PAUSE, processes must stop promptly; enforcement is inside each process.
- Patch-Stream code-change model (jj-backed change graph). Persistent worktrees are not required for the system to function.
- Lint/tests/build run in ephemeral sandboxes (queued execution).
- UI is optional and must not gate workflows; MVP UI surfaces out-of-band notifications only.
- Users do not search logs by text; logs are retrieved and navigated by IDs.
- Keyword/fuzzy search is sufficient for project and ticket lookup; no embedding-model requirement.
- We avoid fixed iteration caps as termination criteria (progress-based circuit breakers instead).
- The system must support many concurrent writers without a single-writer bottleneck.
- All runtime files live under a single predictable root for easy cleanup and backup.


## Goals

- Provide a snappy, low-friction notification center for out-of-band issues:
  - sandbox failures
  - escalated conflicts
  - investigator requests for user action
- Allow simple responses:
  - acknowledge
  - retry
  - pause/resume
  - request trace for a step
- Avoid heavy always-on services, port conflicts, and firewall prompts.

## Philosophy

- The UI is optional; the system must function fully without it.
- Notifications are the minimal stable surface; deeper logs remain file-based and ID-addressed.
- Use a helper interface so the UI does not need direct filesystem access to runtime roots across WSL/Windows boundaries.

## Architectural decision: UI consumes Notifications stream (no DB, no ports)

### Data flow

- UI spawns a helper process:
  - Windows host: `wsl.exe workflowctl notifications tail --jsonl --repo <repo_uid>`
  - Linux/macOS: `workflowctl notifications tail --jsonl --repo <repo_uid>`
- Helper streams JSONL notifications to stdout.
- UI parses and renders them.
- UI sends actions back by invoking helper:
  - `workflowctl control send <action_file>`
  - or `workflowctl control write --json <payload>`

The helper is the only component that needs to know the runtime root layout.

## MVP capabilities

### Notification Center

- list notifications (newest first)
- filter by severity and repo/project/ticket
- open referenced artifacts (paths displayed; “open file” is optional and platform-specific)
- acknowledge notification (local-only UX state is allowed)

### Actions

- send PAUSE to a run/step
- send RESUME to a run/step
- request trace escalation for a step (write trace override)
- request RETRY for a failed step (control action)
- mark “user resolved” for a notification that requires manual action

All actions are expressed as control action requests in the Control Actions Queue.

## Backend (Rust) responsibilities

- spawn helper process and stream stdout
- handle reconnects (helper restart on failure)
- de-duplicate notifications by `notification_id`
- rate-limit rendering updates if needed
- expose minimal IPC to frontend (list, filter, act)

## Frontend (React) structure

Minimum components:

- `RepositorySelector`
- `NotificationCenter`
- `NotificationDetails`
- `ActionBar` (pause, resume, trace, retry)
- `LocalPreferences` (filters, acked notifications)

## Configuration

Stored in a local config file (example):

```json
{
  "schema_version": 1,
  "repositories": [
    {
      "repo_uid": "e7b4c3d2a1f09c88",
      "display_name": "ai-workflow",
      "helper_mode": "wsl",
      "wsl_distro": "Ubuntu"
    }
  ],
  "preferences": {
    "poll_interval_ms": 1500,
    "acknowledged_notifications": []
  }
}
```

## Security and hardening

Even for local-only apps, the WebView to Rust boundary is a trust boundary.

Constraints:

- no arbitrary shell execute from the WebView
- helper invocations are allowlisted commands with fixed argument structure
- UI does not get direct filesystem read access beyond opening referenced artifacts via platform shell open (optional)

## References

- Core infrastructure: Tech_Plan__Core_Infrastructure_&_Data_Model.md
- Monitoring and self-healing: Tech_Plan__Monitoring_&_Self-Healing.md
