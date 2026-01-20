# Gen3 RAG Scripts

These scripts operate on the gen3 rag plan/libraries using the current
annotation formats defined in `pattern_spec.md`.

- `check_duplicate_declarations.py`: flags duplicate `([=ID])` declarations in `plan.md`.
- `detect_duplicates_conflicts.py`: reports IDs duplicated across library files and IDs placed outside their primary library in `libs.md`.
- `find_headers_missing_declarations.py`: lists headers missing a `([=ID])` declaration in `plan.md`.
- `find_unique_library_lines.py`: finds library-only text blocks and associates them with declared IDs.
- `fix_duplicates.py`: removes duplicate library sections, keeping the primary library entry from `libs.md`.
- `normalize_annotations.py`: normalizes legacy annotations to the canonical `([=ID])`, `(@[=ID])`, and `(@[+ID])` formats.
