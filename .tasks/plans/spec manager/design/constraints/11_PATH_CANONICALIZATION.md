# Path Canonicalization

All file path values that participate in comparison, lookup, or
cross-artifact reference must be normalized to a canonical form before use.
The canonical form must be: absolute or project-relative (one consistent
choice per context), POSIX-style separators, resolved (no `.` or `..`
segments), and confined to project root (reject paths that escape the
project boundary).

Path identity is string equality on the canonical form. Two paths that refer
to the same file but differ in representation (relative vs absolute, mixed
separators, unresolved segments) are a source of phantom mismatches —
entities that should match don't, entities that shouldn't match do.
