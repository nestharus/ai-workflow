# Core Infrastructure — Runtime Root Layout

- **Doc**: Tech_Plan__Core_Infrastructure/01_Runtime_Root_Layout.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.runtime.root`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md)
- **Primary responsibility**: Define the durability boundary and the canonical on-disk runtime root layout (cross-platform).

## 2) Runtime root layout (durability boundary)

All runtime artifacts live under a single runtime root:

```text
~/.workflow/
  config.toml                       # user-global config
  tools/                            # optional auto-bootstrapped tools (jj, etc.)
  agents/                           # user-global agent prompts (see Configuration & Onboarding)
  repos/<repo_uid>/
    repo.json
    workspace/                      # WSS (durable docs + artifacts)
      config.toml                   # repo-machine-local overrides (highest non-CLI)
      journals/                     # write-ahead journals for critical mutations
      projects/
      tickets/
        <ticket_id>/
          rebase/
            conflicts/
              <resolution_id>.md          # Canonical conflict records (§2.1)
      runs/
        <run_id>/
          artifacts/
            rebase/
              <bundle_id>/
                refs/
                  prior_conflicts.jsonl   # Reference snapshot (§2.1.2)
      conclusions/
      trace_overrides/
      workflows/                    # WSS-scoped workflows (optional)
    agents/                         # repo machine-local agent prompts
    logs/                           # Logs Store (durable, sharded JSONL)
    notifications/                  # Notifications queue (durable)
    control_actions/                # Control actions queue (durable)
    sandboxes/                      # ephemeral (disposable)
    caches/                         # disposable caches
    vcs/                            # optional jj sidecar mode
    locks/                          # cross-process locks
```

Note: Skills are deployed into CLI-specific locations (e.g., `~/.claude/skills/`), not into `~/.workflow/`. See Configuration & Onboarding §3.

Note: Conflict record storage architecture is specified in Enhanced Rebase & Evaluation §2.1.

This root is the durability boundary. The repository working tree is **not**.

**Project-level overrides** (optional, committed): See **Tech_Plan__Configuration_&_Onboarding.md §1.1** for the `<repo>/.workflow/` structure.

### 2.1 Platform tiers (durability + sandbox expectations)

| Tier | Environment | Durability contract | Sandbox default |
|---|---|---|---|
| **T1** | Linux (native) | Full POSIX (file + directory fsync) + journal recovery | jj workspaces + sparse patterns |
| **T1** | WSL2 with repo on Linux filesystem (ext4-in-VHD) | Same as Linux for files under ext4 | jj workspaces + sparse patterns |
| **T2** | macOS (APFS) | POSIX-like; atomic rename; directory fsync supported; journal recovery | jj workspaces + sparse patterns |
| **T3** | Windows native | File flush supported; directory durability differs; recovery relies on journals | jj workspaces + sparse patterns (copy-on-demand) |

Windows atomic replacement should prefer `ReplaceFile` where available (and the replacement stays on the same volume).
- ReplaceFile docs: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilea
- FlushFileBuffers docs: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers

WSL filesystem guidance (performance + correctness): https://learn.microsoft.com/en-us/windows/wsl/filesystems
