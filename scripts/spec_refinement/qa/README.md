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

## Outputs

- Per-case reports:
  - `runs/<run_id>/audits/qa/<session_id>/cases/<case_id>/report.md`
- Global scoreboard (JSONL, append-only):
  - `runs/_qa_scoreboard.jsonl`

