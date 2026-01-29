# Core Infrastructure — Risk Register

- **Doc**: Tech_Plan__Core_Infrastructure/16_Risk_Register.md
- **Updated**: 2026-01-26
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
