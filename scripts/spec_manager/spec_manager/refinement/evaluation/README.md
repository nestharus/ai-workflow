# Repair Model Bakeoff

## Purpose
Evaluate repair model cost/quality tradeoffs using real failure modes from the spec refinement workflow.

## Usage
```bash
uv run spec.repair-bakeoff
```

### Optional filters
```bash
uv run spec.repair-bakeoff --models gpt-5.2-none,claude-haiku
uv run spec.repair-bakeoff --fixtures missing_citation,invalid_file_id
uv run spec.repair-bakeoff --output scripts/spec_manager/spec_manager/refinement/evaluation/results/REPAIR_MODEL_SELECTION.md
```

## Fixtures
- Add fixtures to `scripts/spec_manager/spec_manager/refinement/evaluation/fixtures/*.py` in the `FIXTURES` list.
- Ensure each artifact type covers all failure categories:
  `invalid_file_id`, `invented_section`, `missing_citation`, `stray_preamble`,
  `trailing_fence`, and `compound_pointer`.
- Provide `allowlists` with `file_ids` and `sections` (and `library_files` for architecture).

## Interpreting results
- **Pass rate**: percent of fixtures that validate after repair.
- **Avg edit distance**: lower is more minimal repair.
- **Avg latency**: wall-clock time per repair.
- **Total cost**: estimated from token counts and per-1k token pricing in `repair_bakeoff.py`.
  Update the pricing values before making cost-sensitive decisions.

## Maintenance
Re-run the bakeoff whenever:
- model pricing or variants change
- new failure patterns are added to validation
- repair agent instructions are updated
