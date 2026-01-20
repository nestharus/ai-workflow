# Gen3 RAG Script Workflows

This folder is organized around safe patch preparation and incremental merging.
We do not assume legacy annotations exist; inputs should be brought to the
current `pattern_spec.md` formats before merging.

## 1. Staging (clean + legalize inputs)

Goal: ensure incoming plan/patch content is legal, annotated, and consistent.

- Validate IDs, header formats, and annotations.
- Add missing declarations in headers and missing references in prose.
- Identify duplicate headers or undefined pseudocode calls.
- If the input lacks annotations, annotate it incrementally and rewrite into
  the expected artifacts before any merge.

## 2. Planning (decompose the change)

Goal: turn a large patch into small, safe batches.

- Compare plan vs libraries and libraries vs libs to find gaps.
- Identify missing assignments and sequencing problems.
- Break the change into batches sized for AI to apply safely.
- If the input introduces new artifact types (e.g., UX/UI/animation/theme),
  define new ID types and update scripts/specs before merging.

## 3. Merging (apply batches)

Goal: apply only the prepared batches.

- Use extraction/move/dedupe/sort tools to place content correctly.
- Avoid bulk sync operations during patch integration.
- `sync_body_from_plan.py` is only for initial seeding, not ongoing patch merges.
- Merging scripts default to dry-run; pass `--apply` after reviewing output.
- `extract_to_libs.py` fails if any ID is already outside its primary library to avoid silent auto-moves.

## 4. Verification (post-merge checks)

Goal: confirm no drift or duplication.

- Compare libraries against plan content.
- Detect duplicates, conflicts, and empty stubs.
- Confirm library-only lines are intentional and assigned.
