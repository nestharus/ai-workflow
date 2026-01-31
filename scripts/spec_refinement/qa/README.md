# Spec Refinement QA (Manual, Agent-Step)

This folder contains a manual QA harness for stress-testing individual spec-refinement agents.

These QA cases intentionally do **not** run under pytest because they can invoke external LLMs
and are meant to be run on-demand.

## Commands

List available cases:

```bash
uv run spec qa list
```

Run a single case (creates/uses `runs/<run_id>/` and writes QA artifacts under `runs/<run_id>/audits/qa/<session_id>/`):

```bash
uv run spec qa run <run_id> <case_id> --force
```

Run all cases:

```bash
uv run spec qa run-all <run_id> --force
```

## Phase 0 QA Cases

Phase 0 QA cases are workspace-level validations. They do not invoke LLM agents; instead they
call `WorkspaceManager.initialize()` directly to verify determinism, resume safety, spec snapshot
immutability, and mode detection.

Example (Phase 0 determinism):

```bash
uv run spec qa run phase0_determinism
```

Example (Phase 0 mode detection):

```bash
uv run spec qa run phase0_mode_detection
```

Agent-based QA cases still execute external agents and rely on a judge; Phase 0 cases rely only
on deterministic validators.

## Outputs

- Per-case reports:
  - `runs/<run_id>/audits/qa/<session_id>/cases/<case_id>/report.md`
- Global scoreboard (JSONL, append-only):
  - `runs/_qa_scoreboard.jsonl`
