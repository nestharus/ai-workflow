# Tech Plan: Integration — Step Instrumentation Contract

- **Doc**: Tech_Plan__Integration/04_Step_Instrumentation_Contract.md
- **Updated**: 2026-01-26
- **Shard**: Integration §4–§4.1
- **Libraries / packages**:
  - `scripts/core/runtime/step.py` (or equivalent) — step lifecycle + progress guard
  - `scripts/core/storage/logs.py` — per-step log shards
  - `scripts/core/storage/wss.py` — step execution docs
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (durability, schemas, error model)

## 4) Step instrumentation (integration contract)

Every step process MUST:

- emit `step_start` and `step_stop`
- append JSONL events to its own log shard
- maintain step doc liveness (`metrics.heartbeat_ts`)
- honor PAUSE and write an ACK
- treat “unable to pause” as an investigation trigger (loud, evidence-backed)

### 4.1 Minimum `@step` decorator responsibilities
`@step` is the boundary where durability is guaranteed:

- creates/updates: `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- appends to: `logs/runs/<run_id>/writers/<writer_id>.jsonl`
- emits periodic progress markers for long-running work:
  - `event_type="progress"` with `data.progress_key` and `data.progress_value`
