# Core Infrastructure — Metrics and Observability (Derived Aggregations)

- **Doc**: Tech_Plan__Core_Infrastructure/17_Metrics_and_Observability.md
- **Updated**: 2026-01-29
- **Library**: `workflow_engine.metrics`
- **Depends on**: [`03_IDs_and_Time.md`](03_IDs_and_Time.md), [`04_WSS_Workspace_State_Store.md`](04_WSS_Workspace_State_Store.md), [`07_Logs_Store.md`](07_Logs_Store.md), [`12_Privacy_Secrets_and_Export.md`](12_Privacy_Secrets_and_Export.md)
- **Primary responsibility**: On-demand aggregation and export of run/step metrics derived from Logs Store evidence and (when needed) WSS state.

## 17) Metrics and observability (derived, read-only)

Metrics are computed on-demand from the Logs Store (§8) and are **derived** artifacts: the Logs Store remains the source of truth; WSS MAY be consulted to fill gaps when logs are incomplete.

The JSON schemas below are the **machine format** for automation. Table output is a presentation layer only.

### 17.1 Metrics schema (v1)

#### 17.1.1 `workflowctl metrics summary` output

```json
{
  "total_runs": {
    "completed": 0,
    "failed": 0,
    "paused": 0,
    "investigating": 0
  },
  "avg_step_duration_ms": null,
  "total_llm_tokens": 0,
  "time_range": {
    "start": "2026-01-22T00:00:00Z",
    "end": "2026-01-29T00:00:00Z"
  },
  "run_breakdown": [
    {
      "run_id": "01J...",
      "status": "completed",
      "duration_ms": 1234,
      "step_count": 5
    }
  ]
}
```

Field rules:
- `total_runs`: counts per final status.
- `avg_step_duration_ms`: mean of step durations for steps that reached `step_completed`; null when no durations are available.
- `total_llm_tokens`: sum of `data.tokens` from `llm_call_stop` events when present; missing token fields are ignored.
- `time_range.start`: the effective lower bound of the query window (see §17.2.1).
- `time_range.end`: the end of the query window (“now” at aggregation time).
- `run_breakdown`: one entry per run that had any included event within the time range.
  - `status`: derived from the latest observed run lifecycle event (`run_completed|run_failed|run_paused|run_investigating`); if no such event exists in-range, implementations SHOULD consult WSS.
  - `duration_ms`: run duration computed per §17.2.2; null when start/end cannot be paired.
  - `step_count`: number of unique `step_execution_id` values observed for the run within the time range (plus WSS fill-in if used).

#### 17.1.2 `workflowctl metrics failures` output

```json
{
  "grouped_failures": [
    {
      "key": "SIG:...",
      "count": 3,
      "runs": ["01J..."],
      "last_seen": "2026-01-28T12:00:00Z"
    }
  ],
  "total_failures": 3,
  "unique_signatures": 1
}
```

Field rules:
- `total_failures`: total count of failure-class events included (see §17.2.3).
- `unique_signatures`: number of distinct failure groups after applying `--group-by`.
- `grouped_failures[*].key`:
  - `--group-by signature`: failure signature per §17.2.3.
  - `--group-by code`: structured error code (`data.error.code`) when available; otherwise `E_INTERNAL`.
- `grouped_failures[*].runs`: unique run IDs where the failure was observed.
- `grouped_failures[*].last_seen`: max `ts` among failures in this group.

#### 17.1.3 `workflowctl export metrics` output

Export is **raw JSONL** (one JSON object per line). Each line MUST be a Logs Store event (schema v1, §8.2) and MUST be redacted per §17.3.

Export MUST include at minimum:
- Run lifecycle events: `run_started`, `run_completed`, `run_failed`, `run_paused`, `run_resumed`, `run_investigating`
- Step lifecycle events: `step_started`, `step_completed`, `step_failed`, `step_paused`, `step_resumed`
- Any event that embeds a structured error object at `data.error`

Implementations MAY include additional event types needed for offline analysis (e.g. `llm_call_stop` for token accounting), provided redaction rules are applied.

### 17.2 Event aggregation rules

#### 17.2.1 Time filtering

- `--since <rfc3339>`: include events where `ts >= <rfc3339>`.
- `--since-days <N>`: include events where `ts >= (now - N days)`.
- Default: last 7 days.

#### 17.2.2 Duration calculation

- Step duration: `step_completed.ts - step_started.ts`, matched by `step_execution_id`.
- Run duration: terminal run lifecycle event (`run_completed|run_failed`) `ts - run_started.ts`, matched by `run_id`.
- Missing pairs MUST be handled gracefully:
  - If start exists but end does not: duration is null.
  - If end exists but start does not: duration is null.
  - Paused/investigating runs may not have terminal events; duration is null unless a terminal event exists.

WSS fallback:
- When Logs Store data is insufficient to determine status/duration, implementations MAY consult WSS run/step documents (04_WSS...) for `status`, `created_at`, and `updated_at`.

#### 17.2.3 Failure signature extraction

Failure-class events are:
- `run_failed`
- `step_failed`
- Any event with `data.error` (structured error object, §8.2.4)

Failure key derivation:
- Primary: `data.error.failure_signature` if present
- Fallback: `data.error.code` + `:` + first 50 characters of `data.error.message` (UTF-8; whitespace preserved)

### 17.3 Privacy and redaction

Redaction for `workflowctl export metrics` MUST follow `12_Privacy_Secrets_and_Export.md` and additionally:

#### 17.3.1 Redaction rules (minimum)

- Remove `data.env` (if present).
- Remove `data.secrets` (if present).
- Redact user home directory path prefixes (replace with `$HOME`) in all string fields (best-effort).
- Keep: timestamps, run IDs, step execution IDs, error codes, derived failure signatures.

#### 17.3.2 Export modes

`workflowctl export metrics` supports:
- `--redact-secrets` (default): enforce redaction rules.
- `--no-redact-secrets`: local debugging only; MUST print a warning before writing output.

