# Gen3 RAG Scripts

These scripts operate on the gen3 rag plan/libraries using the current
annotation formats defined in `pattern_spec.md`.

- `check_duplicate_declarations.py`: flags duplicate `([=ID])` declarations in `plan.md`.
- `check_gaps.py`: compares patch files to `applied.md` to identify unapplied labels.
- `check_sequences.py`: scans for numbering gaps/duplicates across algorithms, goals, invariants, claims, math, and lean entries.
- `compare_ids.py`: compares `libs.md` IDs against `plan.md` headers and reports mismatches.
- `detect_duplicates_conflicts.py`: reports IDs duplicated across library files and IDs placed outside their primary library in `libs.md`.
- `extract_to_libs.py`: inserts missing `plan.md` sections into their primary library files from `libs.md`.
- `find_duplicate_headers.py`: finds exact/near-duplicate headers and pattern issues in `plan.md`.
- `find_empty_stubs.py`: reports library sections with empty bodies, cross-checking `plan.md`.
- `find_headers_missing_declarations.py`: lists headers missing a `([=ID])` declaration in `plan.md`.
- `find_missing.py`: lists `plan.md` headers not represented in `libs.md`.
- `find_missing_assignments.py`: lists library sections missing from `libs.md`.
- `find_references.py`: reports ID references in prose missing `(@[=ID])` or `(@[+ID])`.
- `find_undefined_functions.py`: lists undefined pseudocode function calls across `plan.md` and libraries.
- `find_unique_library_lines.py`: finds library-only text blocks and associates them with declared IDs.
- `fix_duplicates.py`: removes duplicate library sections, keeping the primary library entry from `libs.md`.
- `lint_patterns.py`: validates label formatting against `pattern_spec.md`.
- `move_to_correct_library.py`: relocates library sections to their primary library per `libs.md`.
- `normalize_annotations.py`: normalizes legacy annotations to the canonical `([=ID])`, `(@[=ID])`, and `(@[+ID])` formats.
- `sort_libraries_by_id.py`: sorts library sections by ID.
- `sync_body_from_plan.py`: syncs library section bodies to match `plan.md`.
- `verify_content.py`: compares library content against `plan.md` and reports mismatches.
