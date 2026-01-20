# Pattern Specification for Gen3 RAG Patches

## Annotation Syntax (Canonical)

- Declaration: `([=ID])`
- Reference (related): `(@[+ID])`
- Reference (label-attached): `(@[=ID])`
- Legacy forms to normalize: `[(=ID)]`, `(=[ID])`, `(+[ID])`

## Canonical ID Formats

- Patch: `P#` (e.g., P1, P10)
- Patch section: `P#.#` (e.g., P8.10, P10.4)
- Patch invariant: `P#I#` (e.g., P6I5)
- Patch claim: `P#C#` (e.g., P4C3)
- Algorithm: `Algorithm #` (e.g., Algorithm 41)
- Goal: `G#` (e.g., G12)
- Claim (global): `C#` (e.g., C3)
- Statement: `S#` (e.g., S1)
- Topic: `T#` (e.g., T6)
- Component: `Comp#` (e.g., Comp18)
- Data structure: `D#` (e.g., D27)
- Lean skeleton: `Lean#` (e.g., Lean11)
- Non-functional goal: `NFG#` (e.g., NFG1)
- Gap: `Gap G#.#` (e.g., Gap G9.3)

## Declaration Placement

- Plan and library sections declare their canonical ID in the header line with `([=ID])`.
- libs.md uses list entries in the form `- ([=ID])`, followed by `primary` and `related`.

## Label Extraction Regex Patterns

```python
DECLARATION = r"\(\[=([^\]]+)\]\)"
REF_RELATED = r"\(@\[\+([^\]]+)\]\)"
REF_LABEL = r"\(@\[=([^\]]+)\]\)"

ID_PATTERNS = {
    "patch": r"P\d+",
    "patch_section": r"P\d+\.\d+",
    "invariant": r"P\d+I\d+",
    "claim_patch": r"P\d+C\d+",
    "algorithm": r"Algorithm \d+",
    "goal": r"G\d+",
    "claim": r"C\d+",
    "statement": r"S\d+",
    "topic": r"T\d+",
    "component": r"Comp\d+",
    "data_structure": r"D\d+",
    "lean": r"Lean\d+",
    "nfg": r"NFG\d+",
    "gap": r"Gap G\d+\.\d+",
}
```

## Normalization Rules

- Use `Lean#` without spaces.
- Use `P#.#` for patch sections (no `P10.M#`).
- Do not use legacy annotation forms; normalize them to the canonical syntax.
