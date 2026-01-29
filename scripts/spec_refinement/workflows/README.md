# Spec Refinement Workflows

## Sequential execution

```bash
uv run python -m scripts.spec_refinement.cli init my_run_001 ./specs
uv run python -m scripts.spec_refinement.cli spec summarize my_run_001
uv run python -m scripts.spec_refinement.cli spec synthesize my_run_001
```

## Resumability

Workflows write phase state to `runs/<run_id>/state.json`. Re-running a phase will
overwrite its outputs and refresh the phase status, making it safe to resume after
fixing inputs or agent configuration.

## Parallel tuning

Summarization uses a thread pool capped by `MAX_WORKERS` in
`scripts/spec_refinement/workflows/summarization.py`. Adjust this value when
processing large numbers of files.

## Output inspection

- Summaries: `runs/<run_id>/summaries/*.what.md`
- Library index: `runs/<run_id>/libraries/library_index.md`
- Library artifacts: `runs/<run_id>/libraries/<lib_id>/`
- Evidence maps: `runs/<run_id>/libraries/<lib_id>/evidence.json`

## Error recovery

Phase errors and issues are recorded in `runs/<run_id>/state.json`. Investigate
invalid evidence pointers or parsing issues in the recorded `issues` list, then
re-run the phase once corrected.

## Python API

```python
from pathlib import Path
from scripts.spec_refinement.workflows import summarize_all, synthesize_libraries

summarize_all("my_run_001", Path(".tasks.yaml"))
synthesize_libraries("my_run_001", Path(".tasks.yaml"))
```
