# No-Regex / No-Hardcoded-Phrase Compliance Review

## Deterministic Core (Allowed)

- atomization by newline boundaries
- hashing (sha256)
- sequence alignment for remaps
- coverage accounting
- schema validation for system-owned templates
- ID allocation and uniqueness checks

## LLM-Driven Semantics (Required)

- section discovery
- entity discovery
- decomposition into units
- classification into element types (REQ/FLOW/INV/DEC/ALG/DS)
- library naming and boundary proposals
- semantic contradiction/ambiguity judgments

## Template Parsing (Allowed)

Regex / fixed phrases may be used only for:
- system stamps and IDs (ATOM/SEC/EVID/LIB/REQ/...)
- JSON schemas and explicit output formats
- projection pins and markers owned by the system

## Prohibited Patterns

- scanning raw spec text for keywords like “must/shall” to infer requirements
- regex matching headings like “##” to infer sections as primary logic
- fixed lists of “banned libraries” derived from content semantics

## Auditable Evidence

For each semantic decision, the system stores:
- the atom IDs used as evidence
- the model output under schema
- the confidence score
- the verifier/auditor results

This creates a reviewable chain without relying on hardcoded rules.
