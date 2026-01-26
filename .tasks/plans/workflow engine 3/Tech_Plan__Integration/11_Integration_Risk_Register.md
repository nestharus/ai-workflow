# Tech Plan: Integration — Risk Register

- **Doc**: Tech_Plan__Integration/11_Integration_Risk_Register.md
- **Updated**: 2026-01-26
- **Shard**: Integration §11
- **Libraries / packages**: all (cross-cutting)

## 11) Integration risk register (residual risks + controls)

| Risk | Severity | Control(s) |
|---|---:|---|
| Workflow schema drift | Medium | schema validation + versioned schema + gateway `help` contract tests |
| Sandbox drift across OSes | Medium | single primary mechanism (jj workspaces) + sparse patterns + fallback ladder |
| Gateway schema rot | Medium | reject unknown fields; schema snapshots tested; `help` output included in tests |
| Accidental secret capture | High | outbound scanning + prompt manifests + export scrubber |
| Logging overhead | Low | shard per step; chunk stdout/stderr; retention/GC |
