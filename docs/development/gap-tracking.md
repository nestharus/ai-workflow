# Gap Tracking and Coverage Metrics

This document describes the gap tracking system used during spec refinement,
including the `GapQueue` state, coverage metrics, and remainder handling for
uncited evidence sections.

## Overview

Phase 4 (spec building) runs a gap judge after each integration pass and
synthesizes evidence into `Gap` entries. These gaps are tracked with a
`GapQueue`, which:

- stores the current list of gaps
- detects stagnation across iterations
- reports coverage metrics (open/closed counts and convergence ratio)

Gaps are persisted per library under `runs/<run_id>/libraries/<lib_id>/`.

## GapQueue

`GapQueue` is defined in `scripts/spec_refinement/core/gap_queue.py`.

Key attributes:
- `gaps`: list of current `Gap` entries
- `stagnation_count`: number of consecutive iterations with no changes
- `stagnation_threshold`: maximum iterations before stagnation is flagged
- `last_content_hash`: deterministic hash of gap IDs + statuses
- `is_stagnant`: whether stagnation has been detected

Key methods:
- `update(current_gaps)`: updates state and checks for stagnation
- `mark_progress()`: resets the stagnation counters
- `get_open_gaps()` / `get_closed_gaps()`
- `get_coverage_metrics()`: returns the metrics payload
- `to_dict()` / `from_dict()`: serialization helpers

Gap queue state is persisted as `gap_queue.json` alongside `gaps.md`.

## Coverage Metrics

Coverage metrics are computed from the queue contents:

- `total_gaps`: total entries in the queue
- `open_gaps`: gaps with status `open`
- `closed_gaps`: gaps with status `integrated`
- `convergence_ratio`: `closed_gaps / total_gaps` (defaults to 1.0 if empty)

These metrics are:
- logged in the run history (`gap_coverage_metrics`)
- written into `gaps.md` as a summary section
- aggregated across libraries during Phase 4

## Remainder Handling

Remainder handling detects uncited evidence sections in the spec:

1. Extract evidence pointers from the spec.
2. Compare against known section anchors for each file.
3. Create `GapEvidence` entries for uncited sections with:
   - `invariant_family = "coverage"`
   - `gap_type = "coverage_failure"`
   - `severity = "warning"`

These remainder entries are synthesized with other gap evidence to ensure
coverage gaps are surfaced even when the gap judge reports nothing.

## Phase 4 Integration

During Phase 4 spec building:

- gaps are synthesized per iteration
- the `GapQueue` is updated and stagnation is checked
- convergence occurs when no new gaps are found or stagnation is detected
- coverage metrics are logged and returned in the phase outputs

The CLI surfaces per-library convergence ratios and highlights low convergence
libraries (< 80%).

## Example Workflow

1. Integrate source files into `libraries/<lib_id>/spec.md`
2. Run gap judge and synthesize gaps
3. Update `gap_queue.json` and `gaps.md` with coverage metrics
4. Repeat until converged or stagnant
