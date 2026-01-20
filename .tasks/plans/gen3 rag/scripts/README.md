# Gen3 RAG Scripts

These scripts operate on the gen3 rag plan/libraries using the current
annotation formats defined in `pattern_spec.md`. They are organized by workflow
phase to keep patch prep and merging safe.

See `WORKFLOWS.md` for the high-level staging → planning → merging → verification flow.
Scripts that write to disk default to dry-run; pass `--apply` to persist changes.

## staging/

- `lint_patterns.py`: validates label formatting against `pattern_spec.md`.
- `check_duplicate_declarations.py`: flags duplicate `([=ID])` declarations in `plan.md`.
- `find_headers_missing_declarations.py`: lists headers missing a `([=ID])` declaration in `plan.md`.
- `find_duplicate_headers.py`: finds exact/near-duplicate headers and pattern issues in `plan.md`.
- `find_references.py`: reports ID references in prose missing `(@[=ID])` or `(@[+ID])`.
- `find_undefined_functions.py`: lists undefined pseudocode function calls across `plan.md` and libraries.

## planning/

- `compare_ids.py`: compares `libs.md` IDs against `plan.md` headers and reports mismatches.
- `find_missing.py`: lists `plan.md` headers not represented in `libs.md`.
- `find_missing_assignments.py`: lists library sections missing from `libs.md`.
- `check_sequences.py`: scans for numbering gaps/duplicates across algorithms, goals, invariants, claims, math, and lean entries.

## merging/

- `extract_to_libs.py`: inserts missing `plan.md` sections into their primary library files from `libs.md` (fails if IDs already appear outside the primary library).
- `move_to_correct_library.py`: relocates library sections to their primary library per `libs.md`.
- `fix_duplicates.py`: removes duplicate library sections, keeping the primary library entry from `libs.md`.
- `sort_libraries_by_id.py`: sorts library sections by ID.
- `sync_body_from_plan.py`: syncs library section bodies to match `plan.md` (use only for initial seeding; avoid during patch integration; supports `--min-similarity`).

## verification/

- `verify_content.py`: compares library content against `plan.md` and reports mismatches.
- `detect_duplicates_conflicts.py`: reports IDs duplicated across library files and IDs placed outside their primary library in `libs.md`.
- `find_empty_stubs.py`: reports library sections with empty bodies, cross-checking `plan.md`.
- `find_unique_library_lines.py`: finds library-only text blocks and associates them with declared IDs.
