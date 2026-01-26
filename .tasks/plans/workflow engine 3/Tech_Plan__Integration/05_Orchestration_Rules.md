# Tech Plan: Integration — Orchestration Rules

- **Doc**: Tech_Plan__Integration/05_Orchestration_Rules.md
- **Updated**: 2026-01-26
- **Shard**: Integration §5
- **Libraries / packages**:
  - `scripts/core/runtime/root.py` — root runtime process control plane
  - `scripts/core/runtime/step.py` — step process lifecycle boundary
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (durable control actions, evidence)

## 5) Flat orchestration rule (enforced)

- Root runtime is the only process allowed to spawn step/agent processes.
- Steps may spawn **tool subprocesses** (linters/tests/build) internally, but must:
  - record PIDs in logs and step doc
  - stop them during PAUSE using the documented ladder
