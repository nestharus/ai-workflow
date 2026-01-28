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
| Toolchain drift | Medium | env capture + tool fingerprints + workflow-defined tool commands |
| Schema drift | Medium | explicit migrate tool + loud failure on unknown schema_version |
| Notification deduplication window inappropriate | Low | default 60s window, configurable; users may need to adjust based on workflow patterns |

