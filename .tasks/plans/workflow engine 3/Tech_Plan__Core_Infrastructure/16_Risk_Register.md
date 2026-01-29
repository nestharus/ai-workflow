# Core Infrastructure — Risk Register

- **Doc**: Tech_Plan__Core_Infrastructure/16_Risk_Register.md
- **Updated**: 2026-01-29
- **Library**: `workflow_engine.risk`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md)
- **Primary responsibility**: Enumerate residual risks and the explicit controls that mitigate them.

## 16) Core risk register (residual risks + controls)

All known risks have explicit controls; none require unspecified future work.

| Risk | Severity | Control(s) |
|---|---:|---|
| Cross-platform durability differences | Medium | tiered durability + journals + recover/fsck |
| Evidence bloat | Medium | retention + compression + GC; block GC on active runs |
| Secrets exfiltration | High | keyring secrets + outbound scanning + network policy + export scrubber |
| Concurrency hazards | Medium | ownership enforcement + expected_rev + locks |
| RISK-LOCK-001 Lock Order Violation Detection | Medium | lock acquisition wrapper validates order before acquiring; integration tests verify lock order enforcement; runtime diagnostics log all lock acquisitions with stack traces; residual risk: developer may bypass lock wrapper, code review required |
| Toolchain drift | Medium | env capture + tool fingerprints + workflow-defined tool commands |
| Schema drift | Medium | explicit migrate tool + loud failure on unknown schema_version |
| ULID cross-process ordering misuse | Low | Explicit per-process monotonicity scope in §4.1.2; anti-pattern warnings in §4.1.2a; validation checklist in 03a; log `seq` ordering enforced in §8.2.1 |
| Notification deduplication window inappropriate | Low | default 60s window, configurable; users may need to adjust based on workflow patterns |
| Backup contains secrets | High | Secrets never exported (OS keychain only); config contains references not values; `backup_manifest.json.secrets_policy="references_only"`; manifest records `included_paths`/`excluded_paths`; secret scanning on export (§12.3) |
| Restore overwrites valid state | Medium | Restore validates `backup_manifest.json` before extraction; repo_uid mismatch warning + `--force-repo-uid-mismatch`; fsck runs after restore; no automatic restore; user must explicitly invoke |
| Backup portability assumptions | Medium | Doctor validates dependencies; `backup_manifest.json` records `repo_uid`, `repo_root`, and `tool_version`; documentation specifies portability requirements |
| Backup size bloat | Low | ZIP compression; logs and workspace are bounded by retention policy (§11); user controls backup frequency |
