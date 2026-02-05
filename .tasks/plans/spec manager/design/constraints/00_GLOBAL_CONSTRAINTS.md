# Global Design Constraints

## Constraint Registry

- CON-0001  Evidence atoms are immutable (append-only revisions; no in-place edits)
- CON-0002  100% atom accounting (each atom ∈ {mapped, remainder, excluded}; no silent drop)
- CON-0003  No parsing heuristics on raw input (no hardcoded phrases/regex on uncontrolled text)
- CON-0004  Regex and fixed strings permitted only for system-owned output templates/contracts
- CON-0005  Every derived element MUST cite evidence (directly or via derivation chain)
- CON-0006  Many-to-many membership supported (atom↔element is not 1:1)
- CON-0007  Order and multiplicity preserved for membership comparisons (no set-of-lines)
- CON-0008  Deterministic IDs and stable referents across revisions (with explicit remap tables)
- CON-0009  Progress guarantee: every phase has a total fallback that produces a valid state
- CON-0010  Authority model: Evidence Layer is ultimate; Derived Libraries are working authority; Projections are non-authoritative
- CON-0011  All automated outputs are contract-validated; invalid outputs are quarantined and do not overwrite authoritative artifacts
- CON-0012  Every detected gap becomes an explicit GapElement with evidence and resolution path
- CON-0013  Drift detection is mandatory at every projection boundary
- CON-0014  Spec refinement is continuous during implementation; unknowns discovered in code become spec gaps + new evidence
- CON-0015  Strategy evolution is allowed but gated: experimental strategies cannot become authoritative without tests + audits
- CON-0016  Workspace snapshots are versioned; any state is reproducible from manifests + operation logs
- CON-0017  Files fit in context windows; no chunking required; all intermediate results persisted to disk
- CON-0018  Human-in-the-loop is optional but supported; unresolved items are never forced into false precision
- CON-0019  Tagging outputs use local_id for new items; system resolves to stable IDs and rewrites relation endpoints
- CON-0020  Spec item hashes are evidence-only by default (EVIDENCE_IDS_ONLY); labels excluded to prevent churn on renames
- CON-0021  Evidence citation safety: contract-level lint rejects non-EVID values in evidence fields; warns on derived-artifact tokens (runs/, views/, etc.) in free text
- CON-0022  Patch safety: protected paths enforced; all-or-nothing apply; apply logs recorded; implementation blocks + emits NEED on failure

## Constraint Severity

- Hard: CON-0001..CON-0014, CON-0019..CON-0022
- Soft: CON-0015..CON-0018
